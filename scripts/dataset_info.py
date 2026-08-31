"""공공데이터포털 데이터셋 페이지를 서울 중계기로 읽어 요약한다.

어느 데이터셋이 '연도별 × 영업소 단위' 인지 페이지를 봐야 알 수 있는데
www.data.go.kr 이 해외에서 막혀 있어 중계기를 거친다.

  python scripts/dataset_info.py 15043774 15062249 ...
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")

# 우리가 알고 싶은 것: 기간(연도), 갱신주기, 컬럼(영업소·차종·연도)
WANT = ["영업소", "차종", "연도", "년도", "집계", "기간", "갱신", "수록", "일교통량", "코드"]


def fetch(url: str) -> str:
    relayed = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": url})
    req = urllib.request.Request(relayed, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return f"__ERR__ {type(exc).__name__} {exc}"


def text_of(html: str) -> str:
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"<[^>]+>", "\n", body)
    return re.sub(r"\n{2,}", "\n", body)


def main() -> None:
    for ds in sys.argv[1:]:
        page = fetch(f"https://www.data.go.kr/data/{ds}/fileData.do")
        print(f"\n===== {ds} =====")
        if page.startswith("__ERR__"):
            print(" ", page[:160])
            continue
        text = text_of(page)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = next((ln for ln in lines if "한국도로공사" in ln or "국토교통부" in ln), "")
        print("  제목:", title[:120])
        shown = 0
        for i, ln in enumerate(lines):
            if any(w in ln for w in WANT) and 2 < len(ln) < 160:
                print("   ·", ln[:150])
                shown += 1
                if shown >= 22:
                    break
        if not shown:
            print("  (본문에서 단서를 못 찾음)  길이", len(page))

        # 자동으로 받아오려면 내려받기 주소가 필요하다.
        ids = sorted(set(re.findall(r"atchFileId=([A-Za-z0-9_]+)", page)))
        sns = sorted(set(re.findall(r"fileDetailSn=(\d+)", page)))
        links = sorted(set(re.findall(r"(/cmm/cmm/fileDownload\.do[^\"\'<> ]*)", page)))
        js = sorted(set(re.findall(r"fn_fileDataDown\(([^)]{0,80})\)", page)))
        if ids or links or js:
            print("  내려받기 단서:")
            for x in ids[:4]:
                print("    atchFileId =", x)
            for x in sns[:4]:
                print("    fileDetailSn =", x)
            for x in links[:3]:
                print("    링크 =", x[:160])
            for x in js[:3]:
                print("    js =", x[:120])
        # 파일데이터가 오픈API 로 자동변환됐는지
        if "오픈API" in page or "openapi" in page.lower():
            api = sorted(set(re.findall(r"(https://api\.odcloud\.kr[^\"\'<> ]*)", page)))
            for x in api[:3]:
                print("    odcloud =", x[:160])


if __name__ == "__main__":
    main()
