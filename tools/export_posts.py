"""管理表（sns投稿管理.xlsx）から投稿データを書き出し、画像を JPEG に変換する。

使い方（autopost フォルダで実行）:
    C:\\Users\\sorat\\anaconda3\\python.exe tools\\export_posts.py

- 出力: data/posts.json、images/<記事No>.jpg
- 管理表は読むだけ（書き換えない）
- 画像は元の PNG が新しくなったときだけ変換し直す
"""
import json
import re
import sys
from pathlib import Path

import openpyxl
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent          # autopost/
SNS_DIR = ROOT.parent                                   # sns/
XLSX = SNS_DIR / "sns投稿管理.xlsx"
OUT_JSON = ROOT / "data" / "posts.json"
OUT_IMG = ROOT / "images"

MAX_SIDE = 1440          # Instagram の推奨上限に合わせる
JPEG_QUALITY = 88
PAD_COLOR = (0xFD, 0xF6, 0xED)   # クリーム（投稿方針の配色）

URL_RE = re.compile(r"https?://\S+")


def x_weighted_len(text: str) -> int:
    """X の文字数の数え方（全角=2、URL=23、上限280）。"""
    n = 0
    rest = URL_RE.sub(lambda m: "\0" * 1, text)
    n += 23 * rest.count("\0")
    for ch in rest.replace("\0", ""):
        cp = ord(ch)
        if cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037:
            n += 1
        else:
            n += 2
    return n


def split_tags(cell):
    """「X：#a\\nInsta：#b #c」を {'x': '#a', 'insta': '#b #c'} に分ける。"""
    out = {"x": "", "insta": ""}
    for line in (cell or "").splitlines():
        line = line.strip()
        if line.startswith(("X：", "X:")):
            out["x"] = line[2:].strip()
        elif line.startswith(("Insta：", "Insta:")):
            out["insta"] = line[6:].strip()
    return out


def convert_image(src: Path, dst: Path):
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return False
    im = Image.open(src).convert("RGB")
    w, h = im.size
    # Instagram は縦横比 4:5（0.8）〜 1.91:1 まで。縦長すぎる画像は左右に余白を足す
    if w / h < 0.8:
        nw = round(h * 0.8)
        canvas = Image.new("RGB", (nw, h), PAD_COLOR)
        canvas.paste(im, ((nw - w) // 2, 0))
        im = canvas
        w = nw
    scale = min(1.0, MAX_SIDE / max(w, h))
    if scale < 1.0:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=False)
    return True


def main():
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    ws = wb["投稿管理"]
    rows = ws.iter_rows(values_only=True)
    next(rows)                      # 1行目：見出しのグループ
    header = list(next(rows))       # 2行目：列名
    posts, warnings, converted = [], [], 0

    for values in rows:
        r = dict(zip(header, values))
        pid = (r.get("記事No") or "").strip()
        if not pid:
            continue
        if r.get("ステータス") == "保留":
            continue
        img_src = SNS_DIR / (r.get("画像の参照先") or "")
        img_name = f"{pid}.jpg"
        if not img_src.is_file():
            warnings.append(f"{pid}: 画像が見つかりません（{r.get('画像の参照先')}）")
            img_name = None
        else:
            converted += convert_image(img_src, OUT_IMG / img_name)

        tags = split_tags(r.get("ハッシュタグ"))
        x_text = (r.get("X 本文") or "").strip()
        th_text = (r.get("Threads 本文") or "").strip()
        ig_text = (r.get("Instagram 本文") or "").strip()
        ig_caption = ig_text + ("\n\n" + tags["insta"] if ig_text and tags["insta"] else "")
        pr = r.get("#PR 表記") == "要"

        # 点検
        if x_text and x_weighted_len(x_text) > 280:
            warnings.append(f"{pid}: X本文が長すぎます（{x_weighted_len(x_text)}/280）")
        if len(th_text) > 500:
            warnings.append(f"{pid}: Threads本文が500字を超えています（{len(th_text)}）")
        if len(ig_caption) > 2200:
            warnings.append(f"{pid}: Instagram本文が2,200字を超えています（{len(ig_caption)}）")
        if tags["insta"].count("#") > 5:
            warnings.append(f"{pid}: Instagramのハッシュタグが5個を超えています")
        if pr:
            for name, t in (("X", x_text), ("Threads", th_text), ("Instagram", ig_text)):
                if t and "PR" not in t:
                    warnings.append(f"{pid}: PR投稿ですが {name} 本文に「PR」がありません")

        posts.append({
            "id": pid,
            "url": r.get("サイトURL") or "",
            "page": r.get("ページ名") or "",
            "theme": r.get("テーマ") or "",
            "pattern": r.get("パターン") or "",
            "pr": pr,
            "x_text": x_text,
            "threads_text": th_text,
            "threads_tag": (r.get("Threads タグ") or "").strip(),
            "instagram_caption": ig_caption,
            "image": f"images/{img_name}" if img_name else "",
        })

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"書き出し: {len(posts)}本 → {OUT_JSON.relative_to(ROOT)}")
    print(f"画像の変換: {converted}枚（変更のないものは省略）")
    print(f"Instagram本文あり: {sum(1 for p in posts if p['instagram_caption'])}本 / PR: {sum(p['pr'] for p in posts)}本")
    if warnings:
        print(f"\n注意 {len(warnings)}件:")
        for w in warnings:
            print("  -", w)


if __name__ == "__main__":
    main()
