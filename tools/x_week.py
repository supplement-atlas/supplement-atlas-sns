"""X の週1回まとめ予約のための一覧（1週間分・14本）を作る／予約済みを記録する。

使い方（autopost フォルダで）:
    # 1) 一覧を作る（ユーザーに見せて OK をもらう）
    C:\\Users\\sorat\\anaconda3\\python.exe tools\\x_week.py --from 2026-11-01
    # 2) x.com で予約し終わったら記録する
    C:\\Users\\sorat\\anaconda3\\python.exe tools\\x_week.py --from 2026-11-01 --mark-done

- 一覧: sns/X予約/X予約_<開始日>.html（本文・文字数・予約日時）
- 記録: data/x_log.csv（管理表への反映に使う）
- X は画像を付けない（本文のURLのカード画像で見せる）
"""
import argparse
import csv
import html
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "data" / "posts.json"
SCHEDULE = ROOT / "data" / "schedule.csv"
X_LOG = ROOT / "data" / "x_log.csv"
OUT_DIR = ROOT.parent / "X予約"
X_TIME = {"am": "07:30", "pm": "21:30"}     # X の予約時刻
URL_RE = re.compile(r"https?://\S+")


def x_len(text):
    """X の文字数（全角=2、URL=23 で数えて上限 280）。"""
    n = 23 * len(URL_RE.findall(text))
    for ch in URL_RE.sub("", text):
        cp = ord(ch)
        n += 1 if cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037 else 2
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True, help="1日目 例 2026-11-01")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--mark-done", action="store_true", help="x.com での予約が終わったら記録する")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = start + timedelta(days=args.days - 1)
    posts = {p["id"]: p for p in json.loads(POSTS.read_text(encoding="utf-8"))}
    with SCHEDULE.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if start.isoformat() <= r["date"] <= end.isoformat()]
    if not rows:
        print("この期間の予定はありません")
        return

    if args.mark_done:
        done = set()
        if X_LOG.exists():
            with X_LOG.open(encoding="utf-8", newline="") as f:
                done = {(r["date"], r["slot"]) for r in csv.DictReader(f)}
        new = not X_LOG.exists()
        with X_LOG.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "slot", "time", "id", "status"])
            if new:
                w.writeheader()
            n = 0
            for r in rows:
                if (r["date"], r["slot"]) not in done:
                    w.writerow({"date": r["date"], "slot": r["slot"], "time": X_TIME[r["slot"]],
                                "id": r["id"], "status": "scheduled"})
                    n += 1
        print(f"{n}本を予約済みとして記録しました → {X_LOG.relative_to(ROOT)}")
        return

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"X予約_{start:%Y%m%d}.html"
    items, warns = [], []
    for r in rows:
        p = posts[r["id"]]
        n = x_len(p["x_text"])
        if n > 280:
            warns.append(f"{r['id']} は {n}/280 で長すぎます（短くしてから予約）")
        wd = "月火水木金土日"[date.fromisoformat(r["date"]).weekday()]
        items.append(f"""
<tr class="{'over' if n > 280 else ''}">
 <td class="when">{r['date'][5:].replace('-', '/')}（{wd}）<br>{X_TIME[r['slot']]}</td>
 <td class="id">{html.escape(r['id'])}<br><small>{html.escape(p['pattern'])}{'<br><b>PR</b>' if p['pr'] else ''}</small></td>
 <td class="text">{html.escape(p['x_text'])}</td>
 <td class="len">{n}/280</td>
</tr>""")
    out.write_text(f"""<!doctype html><meta charset="utf-8">
<title>X予約 {start:%m/%d}〜{end:%m/%d}</title>
<style>
body{{font-family:"Yu Gothic UI","Hiragino Sans",sans-serif;background:#FDF6ED;color:#3A302D;margin:16px}}
h1{{font-size:20px}} table{{border-collapse:collapse;width:100%;background:#fff}}
td,th{{border:1px solid #e5d8c8;padding:8px;vertical-align:top;font-size:14px}}
th{{background:#F9D9C8}} .text{{white-space:pre-wrap;line-height:1.6}} .when,.id,.len{{white-space:nowrap}}
tr.over{{background:#fde2e2}} .warn{{color:#b3261e;font-weight:bold}}
</style>
<h1>X 予約一覧 {start:%Y/%m/%d}〜{end:%m/%d}（{len(rows)}本）</h1>
<p>画像は付けず、本文のURLのカード画像で見せます。内容を確認して、OKなら Claude が x.com で予約します。</p>
{''.join(f'<p class="warn">⚠ {html.escape(w)}</p>' for w in warns)}
<table><tr><th>予約日時</th><th>記事No</th><th>本文</th><th>文字数</th></tr>{''.join(items)}</table>
""", encoding="utf-8")
    print(f"{len(rows)}本の一覧を作りました → {out}")
    for w in warns:
        print("  ⚠", w)


if __name__ == "__main__":
    main()
