"""投稿の順番（スケジュール）を作る。

使い方（autopost フォルダで実行）:
    C:\\Users\\sorat\\anaconda3\\python.exe tools\\make_schedule.py --start 2026-11-01

- 出力: data/schedule.csv（日付・朝/夜・記事No …。Excel でそのまま開ける）
- 1日2本（朝 am・夜 pm）。最初はサイト紹介 A-001〜A-005（A-001 が1本目）
- 投稿の型（パターン）ごとに、全期間へ均等に散らす（PR＝⑨も自然に約2割以内で散らばる）
- 同じテーマが続かない／同じページは間をあける／同じページは 共感→影響→習慣→成分→… の順を優先
- 季節もの（SEASONAL）は決まった月の中で均等に散らす
- 2巡目は --start を次の開始日にして --round 2 で作り直す（サイト紹介も混ぜる）
"""
import argparse
import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "data" / "posts.json"
OUT = ROOT / "data" / "schedule.csv"

FIRST = ["A-001", "A-002", "A-003", "A-004", "A-005"]
# 記事No（または頭の部分）→ 投稿してよい月
SEASONAL = {
    "C-012": {12, 1, 2},      # 冬の体調管理
    "pollen-": {2, 3},        # 花粉
}
# お悩みページの中で優先する順番：共感(4) → 影響(5) → 習慣(1) → 成分(2) → 成分解説(I-) → 公的データ(6) → 商品(3)
NAYAMI_ORDER = {"4": 0, "5": 1, "1": 2, "2": 3, "6": 5, "3": 6}
PAGE_MIN_GAP = 16         # 同じページは最低この本数（8日）あける
PR_MIN_GAP = 4            # PR投稿どうしは最低この本数あける
PAGE_PACE_WEIGHT = 0.6    # ページごとの進み具合をどれだけ重視するか


def season_key(pid):
    for prefix, months in SEASONAL.items():
        if pid == prefix or (prefix.endswith("-") and pid.startswith(prefix)):
            return prefix, months
    return None, None


def stage(pid):
    head, _, num = pid.rpartition("-")
    if head == "I":
        return 4
    if head and head not in ("A", "S", "C") and num in NAYAMI_ORDER:
        return NAYAMI_ORDER[num]
    return 0


def slot_date(start, i):
    return start + timedelta(days=i // 2)


def build(posts, start, seed, first):
    rnd = random.Random(seed)
    by_id = {p["id"]: p for p in posts}
    rest = [p for p in posts if p["id"] not in first]
    n_total = len(posts)

    # 型ごと（季節ものは季節ごと）の箱に分ける
    buckets, months_of = {}, {}
    for p in rest:
        skey, months = season_key(p["id"])
        key = f"季節:{skey}" if skey else p["pattern"]
        if skey:
            months_of[key] = months
        buckets.setdefault(key, []).append(p)
    for key, items in buckets.items():
        rnd.shuffle(items)
        items.sort(key=lambda p: stage(p["id"]))   # 同じ段階の中ではランダム

    # 各箱の「次に出したい位置」。間隔＝全体の本数÷箱の本数
    ideal, due, window = {}, {}, {}
    for key, items in buckets.items():
        if key in months_of:
            ok = [i for i in range(n_total + 120) if slot_date(start, i).month in months_of[key]]
            window[key] = (ok[0], ok[-1]) if ok else (10**9, 10**9)
            lo, hi = window[key]
            ideal[key] = (hi - lo) / len(items)
            due[key] = lo + ideal[key] / 3
        else:
            ideal[key] = n_total / len(items)
            due[key] = len(first) + rnd.uniform(0, ideal[key])

    # ページごとの進み具合（投稿の多いページが最後に詰まらないように）
    page_size = {}
    for p in rest:
        page_size[p["url"]] = page_size.get(p["url"], 0) + 1
    page_ideal = {u: n_total / n for u, n in page_size.items()}
    page_due = {u: len(first) + rnd.uniform(0, page_ideal[u]) for u in page_size}

    slots = [by_id[i] for i in first if i in by_id]
    page_last = {}
    for j, p in enumerate(slots):
        page_last[p["url"]] = j
    last_pr = -99
    skipped = []

    i = len(slots)
    while any(buckets.values()):
        prev = slots[-1] if slots else None
        prev2 = slots[-2] if len(slots) >= 2 else None
        best = None
        for key, items in buckets.items():
            if not items:
                continue
            if key in window and not (window[key][0] <= i <= window[key][1]):
                continue
            for p in items:
                pen = due[key] + PAGE_PACE_WEIGHT * (page_due[p["url"]] - i)
                if prev and p["theme"] == prev["theme"]:
                    pen += 1000
                if prev2 and p["theme"] == prev2["theme"]:
                    pen += 20
                if prev and p["pattern"] == prev["pattern"]:
                    pen += 30
                gap = i - page_last.get(p["url"], -999)
                if gap < PAGE_MIN_GAP:
                    pen += 300 + (PAGE_MIN_GAP - gap) * 20
                if p["pr"] and i - last_pr < PR_MIN_GAP:
                    pen += 1000
                # 同じページで、前の段階（共感など）がまだなら後回し
                earlier = [q for b in buckets.values() for q in b
                           if q["url"] == p["url"] and stage(q["id"]) < stage(p["id"])]
                if earlier:
                    pen += 15
                # 1日2本のうち1本は Instagram に出せる投稿にする
                if i % 2 == 1 and prev:
                    if not prev["instagram_caption"] and not p["instagram_caption"]:
                        pen += 40
                    if prev["instagram_caption"] and p["instagram_caption"]:
                        pen += 15
                # 季節ものは、季節が終わる前に出し切る
                if key in window and len(items) * 2 > window[key][1] - i:
                    pen -= 500
                if best is None or pen < best[0]:
                    best = (pen, key, p)
        if best is None:
            # 季節ものだけが残り、季節が来ていない／過ぎた → 今回は入れない
            for items in buckets.values():
                skipped += [p["id"] for p in items]
                items.clear()
            break
        _, key, p = best
        buckets[key].remove(p)
        slots.append(p)
        page_last[p["url"]] = i
        page_due[p["url"]] += page_ideal[p["url"]]
        due[key] += ideal[key]
        if p["pr"]:
            last_pr = i
        i += 1
    return slots, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="1本目の日付 例: 2026-11-01")
    ap.add_argument("--round", type=int, default=1, help="何巡目か（2巡目以降はサイト紹介も混ぜる）")
    ap.add_argument("--seed", type=int, default=20261018)
    args = ap.parse_args()

    posts = json.loads(POSTS.read_text(encoding="utf-8"))
    start = date.fromisoformat(args.start)
    first = FIRST if args.round == 1 else []
    slots, skipped = build(posts, start, args.seed + args.round, first)

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "slot", "id", "theme", "pattern", "pr", "instagram", "page"])
        for i, p in enumerate(slots):
            w.writerow([slot_date(start, i).isoformat(), "am" if i % 2 == 0 else "pm", p["id"], p["theme"],
                        p["pattern"], "PR" if p["pr"] else "", "○" if p["instagram_caption"] else "", p["page"]])

    # 点検
    same_theme = sum(1 for a, b in zip(slots, slots[1:]) if a["theme"] == b["theme"])
    same_pattern = sum(1 for a, b in zip(slots, slots[1:]) if a["pattern"] == b["pattern"])
    pr_idx = [j for j, p in enumerate(slots) if p["pr"]]
    min_pr_gap = min((b - a for a, b in zip(pr_idx, pr_idx[1:])), default=0)
    page_gaps, seen = [], {}
    for j, p in enumerate(slots):
        if p["url"] in seen:
            page_gaps.append(j - seen[p["url"]])
        seen[p["url"]] = j
    days = (len(slots) + 1) // 2
    ig_days = sum(1 for k in range(0, len(slots), 2) if any(p["instagram_caption"] for p in slots[k:k + 2]))
    print(f"{len(slots)}本 / {days}日分（{start} 〜 {slot_date(start, len(slots) - 1)}）→ {OUT.relative_to(ROOT)}")
    print(f"テーマが続いた箇所: {same_theme} / 型が続いた箇所: {same_pattern}")
    print(f"PR: {len(pr_idx)}本（{len(pr_idx) / len(slots):.0%}）最小間隔 {min_pr_gap}本")
    print(f"同じページの最小間隔: {min(page_gaps, default=0)}本（{PAGE_MIN_GAP}本未満: {sum(g < PAGE_MIN_GAP for g in page_gaps)}箇所）")
    print(f"Instagramに出せる日: {ig_days}/{days}日")
    # PR の月ごとの割合
    by_month = {}
    for j, p in enumerate(slots):
        m = slot_date(start, j).strftime("%Y-%m")
        by_month.setdefault(m, [0, 0])
        by_month[m][0] += 1
        by_month[m][1] += p["pr"]
    print("月ごとのPR割合: " + " / ".join(f"{m[2:]} {pr / n:.0%}" for m, (n, pr) in by_month.items()))
    seasonal = [(slot_date(start, j).isoformat(), p["id"]) for j, p in enumerate(slots) if season_key(p["id"])[0]]
    print("季節もの: " + ", ".join(f"{pid} {d}" for d, pid in seasonal))
    if skipped:
        print(f"季節が合わず今回入らなかった投稿: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
