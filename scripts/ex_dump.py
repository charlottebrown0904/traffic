"""도로공사 API 문서 페이지를 서울 중계기로 읽어 파라미터 이름을 뽑는다.

목록 페이지는 자바스크립트로 그려져 경로를 못 읽었다. 상세 페이지
(openApiInfoM?apiId=NNNN)가 서버에서 그려지는지 확인하고, 그렇다면
해당 API 의 요청 변수명을 그대로 읽어온다.

  python scripts/ex_dump.py <apiId 시작> <apiId 끝> [찾을 문자열]
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")

# 문서 표에 실릴 법한 camelCase 변수명
IDENT = re.compile(r"\b[a-z][a-zA-Z]{4,28}\b")
NOISE = {
    "function", "return", "document", "window", "script", "getElementById",
    "className", "innerHTML", "addEventListener", "querySelector", "location",
    "javascript", "charset", "content", "stylesheet", "background", "position",
    "display", "margin", "padding", "border", "height", "width", "color",
}


def fetch(url: str) -> str:
    relayed = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": url})
    req = urllib.request.Request(relayed, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return f"__ERR__ {type(exc).__name__}"


def main() -> None:
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    needle = sys.argv[3] if len(sys.argv) > 3 else "trafficAmountByUnit"
    for api_id in range(lo, hi + 1):
        page = fetch(f"https://data.ex.co.kr/openapi/basicinfo/openApiInfoM?apiId={api_id:04d}")
        if page.startswith("__ERR__"):
            print(f"  {api_id:04d}  {page}")
            continue
        hit = needle in page
        korean = len(re.findall(r"[가-힣]", page))
        mark = "★" if hit else " "
        print(f"  {mark} {api_id:04d}  {len(page):>7}자  한글 {korean:>5}  {'일치' if hit else ''}")
        if hit:
            text = re.sub(r"<[^>]+>", " ", page)
            text = re.sub(r"[ \t]+", " ", text)
            for m in re.finditer(re.escape(needle), text):
                lo2 = max(0, m.start() - 400)
                window = text[lo2:m.end() + 400].replace("\n", " ")
                print("      주변:", re.sub(r"\s+", " ", window))
                break
            names = sorted({m for m in IDENT.findall(page) if m not in NOISE})
            print("      변수 후보:", names[:80])


if __name__ == "__main__":
    main()
