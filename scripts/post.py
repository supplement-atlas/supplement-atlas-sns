"""スケジュールに従って Threads・Instagram に投稿し、data/log.csv に記録する。

GitHub Actions から 1日2回（朝・夜）呼ばれる。手元で試すときは:
    python scripts/post.py --date 2026-11-01 --slot am --dry-run

環境変数（GitHub Secrets から渡す。無い SNS は飛ばす）
    THREADS_ACCESS_TOKEN, THREADS_USER_ID（省略可）
    IG_ACCESS_TOKEN, IG_USER_ID（省略可）
    IMAGE_BASE_URL（省略可。省略時は GitHub の公開リポジトリの画像URL）
    IG_STORY=1 で Instagram のストーリーズにも同じ画像を出す
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "data" / "posts.json"
SCHEDULE = ROOT / "data" / "schedule.csv"
LOG = ROOT / "data" / "log.csv"
LOG_FIELDS = ["posted_at", "date", "slot", "id", "platform", "status", "media_id", "permalink", "note"]
JST = timezone(timedelta(hours=9))

THREADS_API = "https://graph.threads.net/v1.0"
IG_API = "https://graph.instagram.com/v23.0"


class ApiError(Exception):
    pass


def call(method, url, params):
    data = None
    if method == "GET":
        url = url + "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            err = json.loads(body).get("error", {})
            msg = f"{err.get('message')}（code {err.get('code')}/{err.get('error_subcode')}）"
        except ValueError:
            msg = body[:300]
        raise ApiError(f"HTTP {e.code}: {msg}") from None


def wait_ready(get_status, label, tries=20, interval=6):
    """メディアの準備（画像の取り込み）が終わるまで待つ。"""
    for _ in range(tries):
        status, detail = get_status()
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise ApiError(f"{label} の準備に失敗: {detail or status}")
        time.sleep(interval)
    raise ApiError(f"{label} の準備が時間内に終わりませんでした")


# ---------- Threads ----------
def post_threads(post, image_url, token, user_id):
    params = {"media_type": "IMAGE", "image_url": image_url, "text": post["threads_text"], "access_token": token}
    if post.get("threads_tag"):
        params["topic_tag"] = post["threads_tag"]
    cid = call("POST", f"{THREADS_API}/{user_id}/threads", params)["id"]

    def status():
        r = call("GET", f"{THREADS_API}/{cid}", {"fields": "status,error_message", "access_token": token})
        return r.get("status"), r.get("error_message")
    time.sleep(5)
    wait_ready(status, "Threads")
    mid = call("POST", f"{THREADS_API}/{user_id}/threads_publish", {"creation_id": cid, "access_token": token})["id"]
    try:
        link = call("GET", f"{THREADS_API}/{mid}", {"fields": "permalink", "access_token": token}).get("permalink", "")
    except ApiError:
        link = ""
    return mid, link


# ---------- Instagram ----------
def ig_publish(params, token, user_id, label):
    params = dict(params, access_token=token)
    cid = call("POST", f"{IG_API}/{user_id}/media", params)["id"]

    def status():
        r = call("GET", f"{IG_API}/{cid}", {"fields": "status_code,status", "access_token": token})
        return r.get("status_code"), r.get("status")
    wait_ready(status, label)
    mid = call("POST", f"{IG_API}/{user_id}/media_publish", {"creation_id": cid, "access_token": token})["id"]
    try:
        link = call("GET", f"{IG_API}/{mid}", {"fields": "permalink", "access_token": token}).get("permalink", "")
    except ApiError:
        link = ""
    return mid, link


def post_instagram(post, image_url, token, user_id):
    return ig_publish({"image_url": image_url, "caption": post["instagram_caption"]}, token, user_id, "Instagram")


def post_instagram_story(post, image_url, token, user_id):
    return ig_publish({"image_url": image_url, "media_type": "STORIES"}, token, user_id, "ストーリーズ")


# ---------- 共通 ----------
def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_log(row):
    new = not LOG.exists()
    with LOG.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def image_base_url():
    base = os.environ.get("IMAGE_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}" if repo else ""


def check_image(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as res:
            ctype = res.headers.get("Content-Type", "")
            if res.status != 200 or "image" not in ctype:
                raise ApiError(f"画像URLが画像を返しません（{res.status} {ctype}）: {url}")
    except urllib.error.HTTPError as e:
        raise ApiError(f"画像URLが開けません（HTTP {e.code}）: {url}") from None
    except (urllib.error.URLError, ValueError) as e:
        raise ApiError(f"画像URLが開けません（{e}）: {url}") from None


def resolve_user_id(api, token, fields):
    r = call("GET", f"{api}/me", {"fields": fields, "access_token": token})
    return r.get("user_id") or r.get("id")


def check_tokens():
    """投稿せずに、鍵が使えるか（どのアカウントにつながっているか）と画像URLを確かめる。"""
    ok = True
    th = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    ig = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    for name, token, api, fields in (("Threads", th, THREADS_API, "id,username"),
                                      ("Instagram", ig, IG_API, "user_id,username,account_type")):
        if not token:
            print(f"{name}: 鍵が未設定です")
            ok = False
            continue
        try:
            r = call("GET", f"{api}/me", {"fields": fields, "access_token": token})
            extra = f"（{r['account_type']}）" if r.get("account_type") else ""
            print(f"{name}: OK @{r.get('username')}{extra}")
        except ApiError as e:
            print(f"::error::{name}: 鍵が使えません: {e}")
            ok = False
    url = f"{image_base_url()}/images/A-001.jpg"
    try:
        check_image(url)
        print(f"画像URL: OK {url}")
    except ApiError as e:
        print(f"::error::{e}")
        ok = False
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="投稿日（JST）例 2026-11-01。省略時は今日")
    ap.add_argument("--slot", choices=["am", "pm"], help="省略時は今の時刻（15時より前は am）")
    ap.add_argument("--only", choices=["threads", "instagram"], help="片方だけ投稿する")
    ap.add_argument("--dry-run", action="store_true", help="投稿せずに内容だけ表示する")
    ap.add_argument("--check", action="store_true", help="投稿せずに鍵と画像URLだけ確かめる")
    args = ap.parse_args()
    if args.check:
        return check_tokens()

    now = datetime.now(JST)
    day = args.date or now.date().isoformat()
    slot = args.slot or ("am" if now.hour < 15 else "pm")
    dry = args.dry_run or os.environ.get("DRY_RUN") == "1"

    if os.environ.get("AUTOPOST_PAUSED") == "1":
        print("一時停止中（AUTOPOST_PAUSED=1）なので投稿しません")
        return 0

    sched = [r for r in read_csv(SCHEDULE) if r["date"] == day and r["slot"] == slot]
    if not sched:
        print(f"{day} {slot} の予定はありません")
        return 0
    pid = sched[0]["id"]
    posts = {p["id"]: p for p in json.loads(POSTS.read_text(encoding="utf-8"))}
    post = posts.get(pid)
    if not post:
        print(f"::error::{pid} が posts.json にありません")
        return 1

    done = {(r["platform"]) for r in read_csv(LOG)
            if r["date"] == day and r["slot"] == slot and r["status"] == "ok"}
    image_url = f"{image_base_url()}/{post['image']}" if post["image"] else ""
    print(f"{day} {slot}: {pid}（{post['page']}／{post['pattern']}）")
    print(f"画像: {image_url or 'なし'}")

    jobs = []
    th_token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    ig_token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if args.only in (None, "threads"):
        if not th_token and not dry:
            print("Threads: 鍵（THREADS_ACCESS_TOKEN）が未設定なので飛ばします")
        elif "threads" in done:
            print("Threads: この枠は投稿済みです")
        else:
            jobs.append("threads")
    if args.only in (None, "instagram"):
        if not post["instagram_caption"]:
            print("Instagram: この投稿は Instagram 本文がないので出しません")
        elif not ig_token and not dry:
            print("Instagram: 鍵（IG_ACCESS_TOKEN）が未設定なので飛ばします")
        else:
            if "instagram" in done:
                print("Instagram: この枠は投稿済みです")
            else:
                jobs.append("instagram")
            if os.environ.get("IG_STORY") == "1" and "instagram_story" not in done:
                jobs.append("instagram_story")

    if dry:
        for j in jobs:
            text = post["threads_text"] if j == "threads" else post["instagram_caption"] if j == "instagram" else "（画像のみ）"
            tag = f"\n[トピックタグ] {post['threads_tag']}" if j == "threads" else ""
            print(f"\n----- {j}（{len(text)}字）-----\n{text}{tag}")
        print("\n（お試し実行なので投稿していません）")
        return 0
    if not jobs:
        return 0

    failed = False
    try:
        if not image_url:
            raise ApiError("画像がありません")
        check_image(image_url)
    except ApiError as e:
        print(f"::error::{e}")
        for j in jobs:
            append_log({"posted_at": now.isoformat(timespec="seconds"), "date": day, "slot": slot, "id": pid,
                        "platform": j, "status": "error", "note": str(e)})
        return 1

    for j in jobs:
        try:
            if j == "threads":
                uid = os.environ.get("THREADS_USER_ID", "").strip() or "me"
                mid, link = post_threads(post, image_url, th_token, uid)
            else:
                uid = os.environ.get("IG_USER_ID", "").strip() or resolve_user_id(IG_API, ig_token, "user_id")
                fn = post_instagram if j == "instagram" else post_instagram_story
                mid, link = fn(post, image_url, ig_token, uid)
            print(f"{j}: 投稿しました {link}")
            row = {"status": "ok", "media_id": mid, "permalink": link, "note": ""}
        except ApiError as e:
            failed = True
            print(f"::error::{j}: {e}")
            row = {"status": "error", "media_id": "", "permalink": "", "note": str(e)}
        append_log(dict(row, posted_at=datetime.now(JST).isoformat(timespec="seconds"),
                        date=day, slot=slot, id=pid, platform=j))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
