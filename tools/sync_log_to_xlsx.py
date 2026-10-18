"""投稿記録を管理表（sns投稿管理.xlsx）の「最終投稿日」「投稿回数」「ステータス」に反映する。

使い方（autopost フォルダで。先に git pull で最新の記録を取ってくる）:
    git pull
    C:\\Users\\sorat\\anaconda3\\python.exe tools\\sync_log_to_xlsx.py

- 記録: data/log.csv（Threads・Instagram。GitHub Actions が書く）＋ data/x_log.csv（X の予約。x_week.py が書く）
- 投稿回数 ＝ 投稿した枠（日付×朝/夜）の数。どれか1つのSNSに出ていれば1回
- 変更前の管理表は _tools/backups/ に保存する。Excel で開いたままだと保存できない
"""
import csv
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import openpyxl

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SNS_DIR = ROOT.parent
XLSX = SNS_DIR / "sns投稿管理.xlsx"
BACKUP_DIR = SNS_DIR / "_tools" / "backups"
LOGS = [ROOT / "data" / "log.csv", ROOT / "data" / "x_log.csv"]


def main():
    slots = {}     # 記事No → {(日付, 朝夜)}
    today = date.today().isoformat()
    for path in LOGS:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                # X の予約は、予約日時が来たものだけ数える
                if r["status"] in ("ok", "scheduled") and r["date"] <= today:
                    slots.setdefault(r["id"], set()).add((r["date"], r["slot"]))
    if not slots:
        print("反映する記録はまだありません")
        return

    wb = openpyxl.load_workbook(XLSX)
    ws = wb["投稿管理"]
    col = {c.value: c.column for c in ws[2]}
    changed = []
    for row in range(3, ws.max_row + 1):
        pid = ws.cell(row, col["記事No"]).value
        if pid not in slots:
            continue
        count = len(slots[pid])
        last = datetime.fromisoformat(max(d for d, _ in slots[pid]))
        c_count = ws.cell(row, col["投稿回数"])
        c_last = ws.cell(row, col["最終投稿日"])
        c_status = ws.cell(row, col["ステータス"])
        old_last = c_last.value.date() if isinstance(c_last.value, datetime) else c_last.value
        if c_count.value != count or old_last != last.date() or c_status.value != "投稿済み":
            c_count.value = count
            c_last.value = last
            c_last.number_format = "yyyy/mm/dd"
            c_status.value = "投稿済み"
            changed.append(f"{pid}: {count}回・最終 {last.date()}")

    if not changed:
        print("管理表はすでに最新です")
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"sns投稿管理_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    shutil.copy2(XLSX, backup)
    try:
        wb.save(XLSX)
    except PermissionError:
        print("保存できませんでした。sns投稿管理.xlsx を Excel で閉じてから、もう一度実行してください")
        sys.exit(1)
    print(f"{len(changed)}件を反映しました（バックアップ: {backup.name}）")
    for c in changed:
        print("  -", c)


if __name__ == "__main__":
    main()
