"""토지가격비준표를 기계가 받을 수 있는지 본다 (한국부동산원 열람 서비스).

왜 이 탐침이 있나. 비준표는 시군구 × 용도지역별로 따로 있어서, 사람이
화면에서 하나씩 골라 엑셀을 받으면 **229 시군구 × 용도지역** 을 눌러야 한다.
보고(2026-09-12): "하나하나 찾으면 시간이 너무 많이 걸립니다."

그래서 먼저 **어떤 요청 하나로 표가 나오는지**를 알아낸다. 알아내면 러너가
대신 돌고, 사람은 워크플로를 한 번 누르면 된다.

이 상자에서는 sct.reb.or.kr 로 나갈 수 없다(egress 차단). 서울 중계기를
거친다 — api/relay.js 의 ALLOW 에 이 호스트를 넣어 두었다.

  python scripts/reb_probe.py                     # 기본 탐침
  python scripts/reb_probe.py --sido 41 --sgg 41550   # 안성시로 한 번 더

읽는 것만 한다. 받은 것을 저장하지 않는다 — 무엇이 열려 있는지만 적는다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
TIMEOUT = 40

# 열람 서비스의 쪽들. 어느 것이 폼을 들고 있는지 모르므로 다 본다.
PAGES = [
    "https://sct.reb.or.kr/reading/landReading.do",
    "https://sct.reb.or.kr/reading/landReading2.do",   # 공통비준표
    "https://sct.reb.or.kr/unit/landUnit.do",          # 작성단위
    "https://sct.reb.or.kr/summary/landSummary.do",    # 개요 (항목 목록)
]

# 포털 쪽 파일데이터. 사용자가 화면에서 못 열었다고 했다(2026-09-12) —
# 로그인 벽인지, 내려받기 주소가 따로 있는지를 여기서 가른다.
PORTAL = [
    "https://www.data.go.kr/data/15120064/fileData.do",   # 비준표 정보
    "https://www.data.go.kr/data/15120063/fileData.do",   # 작성단위 정보
    "https://www.data.go.kr/data/15134761/openapi.do",    # 지가변동률
]


def get(url: str, data: bytes | None = None) -> tuple[int, str]:
    relayed = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": url})
    req = urllib.request.Request(relayed, data=data,
                                 headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:800]
    except Exception as exc:                              # noqa: BLE001
        return 0, f"__ERR__ {type(exc).__name__} {exc}"


def shape(url: str, page: str) -> None:
    """폼·선택칸·내려받기 링크를 적는다. 이것이 곧 수집기의 명세다."""
    print(f"  길이 {len(page):,}")
    for m in re.finditer(r"<form[^>]*>", page, re.I):
        print("  form:", re.sub(r"\s+", " ", m.group(0))[:220])
    names = sorted(set(re.findall(r'<(?:input|select)[^>]*name=["\']([^"\']+)',
                                  page, re.I)))
    if names:
        print("  칸:", names[:40])
    # 표를 내려주는 자리. 엑셀·다운로드·excel 이 붙은 주소나 함수 이름.
    hits = sorted(set(re.findall(
        r'(?:href|action|url)\s*[=:]\s*["\']([^"\']*(?:excel|download|xls|file)[^"\']*)',
        page, re.I)))
    for h in hits[:12]:
        print("  내려받기 후보:", h[:160])
    fns = sorted(set(re.findall(r'function\s+(fn[A-Za-z0-9_]*|go[A-Za-z0-9_]*)', page)))
    if fns:
        print("  자바스크립트 함수:", fns[:15])
    # 열람 화면이 값을 어디서 받아오는지 (ajax url)
    ajax = sorted(set(re.findall(r'url\s*:\s*["\']([^"\']+)', page)))
    for a in ajax[:12]:
        print("  ajax:", a[:160])
    if "로그인" in page or "login" in page.lower():
        print("  ! '로그인' 이라는 말이 페이지에 있습니다 — 벽일 수 있습니다")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sido", default="41")
    ap.add_argument("--sgg", default="41550")      # 안성시 — 우리 검증 사례
    ap.add_argument("--year", default="2025")
    args = ap.parse_args()

    if not RELAY or not TOKEN:
        print("RELAY_URL·RELAY_TOKEN 이 없습니다 (러너에서 돌리세요).")
        return 2

    print("1. 열람 서비스 쪽들 — 폼과 내려받기 주소를 찾는다")
    for url in PAGES:
        code, page = get(url)
        print(f"\n===== {code} {url}")
        if page.startswith("__ERR__") or code >= 400:
            print(" ", page[:200])
            continue
        shape(url, page)

    print("\n\n2. 공공데이터포털 — 화면이 안 열린 이유를 가른다")
    for url in PORTAL:
        code, page = get(url)
        print(f"\n===== {code} {url}")
        if page.startswith("__ERR__"):
            print(" ", page[:200])
            continue
        print(f"  길이 {len(page):,}")
        for word in ("로그인", "신청", "중단", "삭제", "비공개", "파일데이터", "오류"):
            if word in page:
                print(f"  '{word}' 있음")
        hits = sorted(set(re.findall(
            r'(?:href|action)\s*=\s*["\']([^"\']*(?:fileDownload|atchFileId)[^"\']*)',
            page, re.I)))
        for h in hits[:8]:
            print("  내려받기 후보:", h[:200])

    print("\n\n3. 표 하나를 실제로 받아 본다 (시도 %s · 시군구 %s · %s년)"
          % (args.sido, args.sgg, args.year))
    # 아직 요청 모양을 모른다. 흔한 이름들로 한 번씩 찔러 보고 상태만 적는다.
    body = urllib.parse.urlencode({
        "searchYear": args.year, "sidoCd": args.sido, "sggCd": args.sgg,
        "year": args.year, "sido": args.sido, "sgg": args.sgg,
    }).encode()
    for url in ("https://sct.reb.or.kr/reading/landReadingList.do",
                "https://sct.reb.or.kr/reading/landReading.do",
                "https://sct.reb.or.kr/reading/landReadingExcel.do"):
        code, page = get(url, data=body)
        head = page[:160].replace("\n", " ")
        print(f"  {code} {url}\n      {head}")

    print("\n무엇이 열렸는지 위 출력을 그대로 문서에 옮기고, 수집기는 그다음에 씁니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
