"""Threads・Instagram の長期トークン（60日）を延長し、GitHub Secrets を新しい値で上書きする。

GitHub Actions から週1回呼ばれる。必要なもの:
    THREADS_ACCESS_TOKEN / IG_ACCESS_TOKEN … 今のトークン（無い方は飛ばす）
    GH_TOKEN … Secrets を書き換えられる GitHub の個人用トークン（Secrets 名: SECRETS_PAT）
    GITHUB_REPOSITORY … Actions が自動で入れる
トークンの値はログに出さない。
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

TARGETS = [
    ("THREADS_ACCESS_TOKEN", "https://graph.threads.net/refresh_access_token", "th_refresh_token"),
    ("IG_ACCESS_TOKEN", "https://graph.instagram.com/refresh_access_token", "ig_refresh_token"),
]


def refresh(url, grant, token):
    q = urllib.parse.urlencode({"grant_type": grant, "access_token": token})
    try:
        with urllib.request.urlopen(f"{url}?{q}", timeout=60) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            body = json.loads(body).get("error", {}).get("message", body)
        except ValueError:
            pass
        raise RuntimeError(f"HTTP {e.code}: {str(body)[:300]}") from None


def main():
    repo = os.environ.get("GITHUB_REPOSITORY")
    failed = False
    for name, url, grant in TARGETS:
        token = os.environ.get(name, "").strip()
        if not token:
            print(f"{name}: 未設定なので飛ばします")
            continue
        try:
            r = refresh(url, grant, token)
            new = r["access_token"]
            print(f"::add-mask::{new}")
            days = int(r.get("expires_in", 0)) // 86400
            subprocess.run(["gh", "secret", "set", name, "--repo", repo], input=new.encode(),
                           check=True, capture_output=True)
            print(f"{name}: 延長しました（あと約{days}日有効）")
        except Exception as e:  # noqa: BLE001
            failed = True
            msg = e.stderr.decode(errors="replace") if isinstance(e, subprocess.CalledProcessError) else str(e)
            print(f"::error::{name}: 延長に失敗しました: {msg}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
