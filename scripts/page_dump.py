"""허용된 호스트의 페이지를 중계기로 읽어 폼·링크를 뽑는다.

파일 다운로드가 어떤 요청으로 이뤄지는지 알아내기 위한 도구.

  python scripts/page_dump.py <url> [url ...]
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")


def fetch(url: str) -> str:
    relayed = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": url})
    req = urllib.request.Request(relayed, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return f"__ERR__ {type(exc).__name__} {exc}"


def main() -> None:
    for url in sys.argv[1:]:
        print(f"\n===== {url}")
        page = fetch(url)
        if page.startswith("__ERR__"):
            print(" ", page[:200])
            continue
        print(f"  길이 {len(page)}")

        for m in re.finditer(r"<form[^>]*>", page, re.I):
            print("  form:", re.sub(r"\s+", " ", m.group(0))[:200])

        names = sorted(set(re.findall(r'<input[^>]*name=["\']([^"\']+)', page, re.I)))
        if names:
            print("  input:", names[:40])

        sels = sorted(set(re.findall(r'<select[^>]*name=["\']([^"\']+)', page, re.I)))
        if sels:
            print("  select:", sels[:20])

        # 다운로드로 이어질 법한 함수·주소
        fns = sorted(set(re.findall(r"function\s+(fn[A-Za-z0-9_]*)\s*\(", page)))
        if fns:
            print("  js 함수:", fns[:30])
        acts = sorted(set(re.findall(r"['\"](/portal/[A-Za-z0-9_/]+)['\"]", page)))
        if acts:
            print("  portal 경로:", acts[:30])
        dl = sorted(set(re.findall(r"['\"]([^'\"]*(?:down|Down|excel|Excel|file|File)[^'\"]*)['\"]", page)))
        dl = [d for d in dl if d.startswith("/") and len(d) < 120]
        if dl:
            print("  다운로드 후보:", dl[:20])


if __name__ == "__main__":
    main()
