"""법원경매·공매 물건(토지·공장·창고)을 자동으로 받아올 길이 있는지 묻는다.

왜 탐침을 먼저 하는가
---------------------
"법원경매 물건을 가져올 수 있냐" 에 기억으로 답하면 안 된다. 이 저장소에서
레이어 이름을 세 번 틀리고(api/tile.js), 공시지가 원천도 추측으로 시작했다가
헛돌았다. **포털에 뭐가 실제로 열려 있는지 목록을 받아 보고** 답한다.

무엇이 다른가 — 경매와 공매
---------------------------
  법원경매(사법경매)  대법원 법원행정처. courtauction.go.kr.
                      채무 불이행 → 법원이 강제집행으로 판다.
  공매               한국자산관리공사(캠코). onbid.co.kr.
                      세금 체납 압류재산·국유재산 등을 판다.

둘은 주체도 근거법도 사이트도 다르다. 사장님이 말씀하신 "법원 경매" 는
앞쪽이지만, 뒤쪽은 공식 오픈API 가 있을 가능성이 높아 같이 본다 — 물건
성격(토지·공장·창고)은 겹치고, 앞쪽이 막혀 있으면 뒤쪽이 대안이 된다.

이 스크립트가 하는 일
--------------------
  1. 공공데이터포털 목록을 키워드로 훑어 제목·제공기관·형태(오픈API/파일)를
     찍는다. 형태가 '파일' 이면 매달 사람이 내려받아야 한다는 뜻이라,
     자동 수집 여부가 여기서 갈린다.
  2. 온비드 오픈API 로 알려진 주소 후보를 한 번씩 두드려 본다.
  3. 법원경매 사이트의 robots.txt 를 읽는다. 오픈API 가 없을 때 남는 길은
     긁는 것뿐인데, 그것이 허용되는지는 우리가 정할 일이 아니다.

러너는 미국이라 한국 공공 API 가 막힌다. 서울 중계기를 거친다
(REDT_RELAY_URL / REDT_RELAY_TOKEN).
"""
from __future__ import annotations

import re
import sys
from html import unescape
from urllib.parse import urljoin

sys.path.insert(0, "src")

from redt.collect import http as H            # noqa: E402
from redt.config import relay                 # noqa: E402

PORTAL = "https://www.data.go.kr/tcs/dss/selectDataSetList.do"
KEYWORDS = ["법원경매", "경매", "공매", "온비드", "압류재산", "경매물건"]

# 온비드 오픈API 주소 후보. 어느 쪽이 살아 있는지 몰라서 후보로 둔다 —
# 추측을 코드에 박지 않고 두드려 본 결과를 적는 것이 이 파일의 목적이다.
ONBID_CANDIDATES = [
    "http://openapi.onbid.co.kr/openapi/services/KamcoPblsalThingInquireSvc"
    "/getKamcoPbctCltrList",
    "https://openapi.onbid.co.kr/openapi/services/KamcoPblsalThingInquireSvc"
    "/getKamcoPbctCltrList",
    "https://apis.data.go.kr/1230000/OnbidThingInquireSvc/getUnifyUsageCltr",
    "https://apis.data.go.kr/B551995/onbid/getPbctCltrList",
]

# 법원경매는 오픈API 가 없을 수 있다. 그때 남는 길이 무엇인지 확인한다.
COURT_HOSTS = [
    "https://www.courtauction.go.kr/robots.txt",
]


def head(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def portal_search(keyword: str, page: int = 1) -> list[dict]:
    """포털 목록 화면을 읽어 제목·기관·형태를 뽑는다.

    포털은 목록 자체를 주는 오픈API 가 따로 있지만 그것도 키가 필요하다.
    목록 화면은 공개라 그대로 읽는다 (중계기 통과 목록에 이미 있다).
    """
    resp = H.get_once(PORTAL, {"keyword": keyword, "currentPage": page,
                               "perPage": 20}, timeout=25)
    if resp.status_code != 200:
        print(f"  [{keyword}] 목록을 못 읽었습니다 — HTTP {resp.status_code}")
        return []
    html = resp.text

    rows: list[dict] = []
    # 목록 한 칸은 <div class="result-list"> 안의 <li> 다. 포털이 화면을
    # 바꾸면 이 정규식은 깨진다 — 깨지면 0건으로 나오므로 조용히 틀리지는
    # 않는다. 그 점을 아래 '뽑은 건수' 로 드러낸다.
    for block in re.findall(r"<li[^>]*>(.*?)</li>", html, re.S):
        link = re.search(r'href="(/data/\d+/\w+\.do[^"]*)"', block)
        title = re.search(r'<a[^>]*>\s*(?:<span[^>]*>.*?</span>)?\s*(.*?)</a>',
                          block, re.S)
        if not link or not title:
            continue
        name = unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip()
        if not name:
            continue
        org = re.search(r'class="[^"]*organ[^"]*"[^>]*>(.*?)<', block, re.S)
        # 상세 주소 끝이 fileData.do 면 파일, openapi.do 면 오픈API 다.
        kind = ("오픈API" if "openapi" in link.group(1).lower()
                else "파일" if "filedata" in link.group(1).lower()
                else "표준/기타")
        rows.append({
            "title": name,
            "org": unescape(re.sub(r"<[^>]+>", "", org.group(1))).strip() if org else "",
            "kind": kind,
            "url": urljoin("https://www.data.go.kr", link.group(1)),
        })
    return rows


def main() -> None:
    cfg = relay()
    print(f"중계기: {'사용' if cfg.enabled else '없음 (직접 호출 — 지오블록 가능)'}")

    head("1. 공공데이터포털에 '경매·공매' 로 무엇이 열려 있는가")
    seen: set[str] = set()
    for kw in KEYWORDS:
        rows = portal_search(kw)
        fresh = [r for r in rows if r["url"] not in seen]
        for r in fresh:
            seen.add(r["url"])
        print(f"\n[{kw}] {len(rows)}건 (새것 {len(fresh)}건)")
        for r in fresh[:12]:
            print(f"   {r['kind']:<8} {r['title'][:52]}")
            print(f"            {r['org'][:36]}  {r['url']}")
        if not rows:
            print("   (없음 — 검색이 막혔거나 화면 구조가 바뀌었을 수 있습니다)")

    head("2. 온비드(공매) 오픈API 주소 후보 두드리기")
    for url in ONBID_CANDIDATES:
        try:
            resp = H.get_once(url, {"numOfRows": 1, "pageNo": 1}, timeout=20)
            body = resp.text[:220].replace("\n", " ")
            print(f"\n   {resp.status_code}  {url}")
            print(f"        {body}")
        except Exception as exc:                       # noqa: BLE001
            print(f"\n   실패  {url}")
            print(f"        {type(exc).__name__}: {str(exc)[:160]}")

    head("3. 법원경매 사이트 — 오픈API 가 없을 때 남는 길")
    for url in COURT_HOSTS:
        try:
            resp = H.get_once(url, {}, timeout=20)
            print(f"\n   {resp.status_code}  {url}")
            print("   " + "\n   ".join(resp.text.splitlines()[:20]))
        except Exception as exc:                       # noqa: BLE001
            print(f"\n   실패  {url}")
            print(f"        {type(exc).__name__}: {str(exc)[:160]}")
            print("        (중계기 통과 목록에 없는 호스트라면 여기서 막힙니다 —")
            print("         api/relay.js 의 ALLOW 와 collect/http.py 의")
            print("         RELAYED_HOSTS 두 곳에 같이 넣어야 합니다.)")

    print()
    print("=" * 72)
    print("읽는 법")
    print("=" * 72)
    print("  오픈API 로 뜨면  → 자동 수집이 된다. 물건 종류(토지·공장·창고)와")
    print("                     소재지·감정가·최저가·매각기일 칸이 있는지가 다음 질문이다.")
    print("  파일로만 뜨면    → 사람이 주기적으로 내려받아야 한다. 자동화하려면")
    print("                     내려받기 주소가 고정인지 확인해야 한다.")
    print("  아무것도 없으면  → 공식 경로가 없다는 뜻이다. 긁는 것은 robots.txt 와")
    print("                     이용약관을 먼저 보고 판단할 일이지 기본값이 아니다.")


if __name__ == "__main__":
    main()
