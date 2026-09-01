"""표준지공시지가 OpenAPI 의 실제 주소를 포털에서 찾아온다.

탐침이 후보 서비스 이름 30개를 전부 400 으로 돌려받았다. 이름을 계속
추측하는 것은 값싸 보이지만 답이 없는 길이다. 포털 페이지에 정답이
적혀 있으므로 그것을 읽는다.

www.data.go.kr 은 해외에서 막혀 있어 서울 중계기를 거친다.

  python scripts/landprice_find.py [검색어]
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
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return f"__ERR__ {type(exc).__name__} {exc}"


def strip_tags(html: str) -> str:
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"<[^>]+>", "\n", body)
    return re.sub(r"\n{2,}", "\n", body)


def search(keyword: str) -> list[tuple[str, str]]:
    """포털 검색에서 (데이터셋ID, 제목) 을 뽑는다. API 유형만 본다."""
    url = ("https://www.data.go.kr/tcs/dss/selectDataSetList.do?"
           + urllib.parse.urlencode({"keyword": keyword, "dType": "API",
                                     "perPage": "20", "currentPage": "1"}))
    page = fetch(url)
    if page.startswith("__ERR__"):
        print("  검색 실패:", page[:200])
        return []
    found: list[tuple[str, str]] = []
    seen = set()
    for m in re.finditer(r'/data/(\d+)/openApi\.do', page, re.I):
        ds = m.group(1)
        if ds in seen:
            continue
        seen.add(ds)
        # 링크 주변 텍스트에서 제목을 줍는다.
        around = page[max(0, m.start() - 400): m.start() + 400]
        title = ""
        for t in re.findall(r">([^<>]{6,90})<", around):
            t = t.strip()
            if "공시지가" in t or "국토교통부" in t:
                title = t
                break
        found.append((ds, title))
    return found


# 상세기능 표에서 오퍼레이션 주소와 파라미터 이름이 드러나는 자리들
URL_RE = re.compile(r"https?://apis?\.(?:data\.go\.kr|odcloud\.kr)/[^\s\"'<>]+")
OP_RE = re.compile(r"\b(get[A-Za-z]{4,60})\b")


# 포털 링크는 openApi.do 로 적혀 있지만 실제 주소는 소문자 openapi.do 다.
# 링크를 그대로 옮겨 적었다가 404 를 받았다.
PAGE_PATHS = ["openapi.do", "openApi.do", "fileData.do", "standard.do"]


def describe(ds: str) -> None:
    print(f"\n===== {ds} =====")
    page = ""
    for path in PAGE_PATHS:
        page = fetch(f"https://www.data.go.kr/data/{ds}/{path}")
        if not page.startswith("__ERR__"):
            print(f"  경로: {path}")
            break
        print(f"  {path}: {page[:80]}")
    if page.startswith("__ERR__"):
        return
    text = strip_tags(page)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    title = next((ln for ln in lines[:400]
                  if "국토교통부_" in ln or "데이터명" in ln), "")
    print("  제목:", title[:120] if title else "(못 찾음)")

    urls = sorted(set(URL_RE.findall(page)))
    if urls:
        print("  주소:")
        for u in urls[:15]:
            print("   ", u[:160])
    else:
        print("  주소를 못 찾았습니다.")

    ops = sorted(set(OP_RE.findall(page)))
    if ops:
        print("  오퍼레이션:", ", ".join(ops[:20]))

    # 응답 필드 후보 — 좌표·연도·용도지역이 있는지 여기서 미리 본다.
    hints = [ln for ln in lines
             if any(k in ln for k in ("좌표", "경도", "위도", "기준연도", "기준년도",
                                      "용도지역", "지목", "공시지가", "PNU", "필지"))]
    if hints:
        print("  필드 힌트:")
        for h in dict.fromkeys(hints[:30]):
            print("   ", h[:110])
    else:
        print("  필드 힌트 없음. 본문 앞부분:")
        for ln in lines[:60]:
            print("   ", ln[:110])


def main() -> None:
    if not RELAY or not TOKEN:
        sys.exit("RELAY_URL / RELAY_TOKEN 이 필요합니다.")
    keyword = sys.argv[1] if len(sys.argv) > 1 else "표준지공시지가"
    print(f"검색어: {keyword}")
    hits = search(keyword)
    if not hits:
        print("검색 결과가 없습니다. 페이지 구조가 바뀌었을 수 있습니다.")
        return
    for ds, title in hits:
        print(f"  {ds}  {title}")
    for ds, _ in hits[:5]:
        describe(ds)


if __name__ == "__main__":
    main()
