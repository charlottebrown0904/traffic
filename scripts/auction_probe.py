"""법원경매·공매 물건(토지·공장·창고)을 자동으로 받아올 길이 있는지 묻는다.

왜 탐침을 먼저 하는가
---------------------
"법원경매 물건을 가져올 수 있냐" 에 기억으로 답하면 안 된다. 이 저장소에서
레이어 이름을 세 번 틀렸고(api/tile.js), 공시지가 원천도 추측으로 시작했다가
헛돌았다. **포털에 뭐가 실제로 열려 있는지 받아 보고** 답한다.

무엇이 다른가 — 경매와 공매
---------------------------
  법원경매(사법경매)  대법원 법원행정처. courtauction.go.kr.
                      채무 불이행 → 법원이 강제집행으로 판다.
  공매               한국자산관리공사(캠코). onbid.co.kr.
                      세금 체납 압류재산·국유재산 등을 판다.

둘은 주체도 근거법도 사이트도 다르다. 여기서 말하는 "법원 경매" 는
앞쪽이지만, 뒤쪽은 공식 오픈API 가 있을 가능성이 높아 같이 본다 — 물건
성격(토지·공장·창고)은 겹치고, 앞쪽이 막혀 있으면 뒤쪽이 대안이 된다.

1차 탐침에서 배운 것 (2026-09-04)
--------------------------------
세 갈래가 전부 실패했는데, 실패 이유가 셋 다 우리 쪽이었다.

  · 포털 검색 0건    — 목록을 뽑는 정규식이 안 맞았다. '없다' 가 아니라
                       '못 읽었다' 인데 화면에는 똑같이 0건으로 보였다.
                       그래서 이번에는 **받은 것을 그대로 찍는다.**
  · 온비드 타임아웃  — 중계기 허용 목록에 없어 미국 러너에서 직접 나갔고
                       막혔다. 호스트를 넣었다.
  · 법원경매 타임아웃 — 같은 이유.

한편 apis.data.go.kr 로 두드린 두 주소는 400 NO_OPENAPI_SERVICE_ERROR
("해당 오픈API 서비스가 없거나 폐기됨") 를 제대로 돌려줬다. 중계기와 포털은
멀쩡하고, **내가 찍은 서비스 경로가 틀렸다**는 뜻이다.

러너는 미국이라 한국 공공 API 가 막힌다. 서울 중계기를 거친다
(REDT_RELAY_URL / REDT_RELAY_TOKEN).
"""
from __future__ import annotations

import re
import sys
from html import unescape

sys.path.insert(0, "src")

from redt.collect import http as H            # noqa: E402
from redt.config import relay                 # noqa: E402

PORTAL = "https://www.data.go.kr/tcs/dss/selectDataSetList.do"
KEYWORDS = ["법원경매", "공매", "온비드", "압류재산"]

# 2차에서 찾은 것. 포털 검색으로 실제 존재를 확인한 데이터셋이다.
# 이제 '있는가' 가 아니라 **'어떤 칸이 오는가'** 를 묻는다 — 물건 용도
# (토지·공장·창고)와 소재지·감정가·최저가·입찰기간이 없으면 우리 지도에
# 얹을 수 없다.
ONBID_DATASETS = [
    ("차세대 온비드 부동산 물건목록 조회서비스", "15157207"),
    ("차세대 온비드 공고목록 조회서비스", "15157216"),
    ("체납 압류재산 (캠코)", "15126398"),
]

# 중계기는 https 만 통과시킨다(2차에서 http 로 보내 400 을 받았다).
ONBID_PROBES = [
    ("온비드 오픈API 루트", "https://openapi.onbid.co.kr/openapi/services", {}),
    ("온비드 웹 robots.txt", "https://www.onbid.co.kr/robots.txt", {}),
]

COURT_PROBES = [
    ("법원경매 robots.txt", "https://www.courtauction.go.kr/robots.txt", {}),
    ("법원경매 첫 화면", "https://www.courtauction.go.kr/", {}),
]


def head(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def show(label: str, url: str, params: dict, *, body_chars: int = 400) -> None:
    """두드리고 **받은 것을 그대로** 찍는다.

    1차 탐침의 교훈이다. 파싱에 실패하고 '0건' 이라고만 적으면, 없는 것과
    못 읽은 것이 화면에서 똑같아 보인다. 그 둘은 다음 수가 완전히 다르다."""
    try:
        resp = H.get_once(url, params, timeout=25)
    except Exception as exc:                           # noqa: BLE001
        print(f"\n  실패  {label}")
        print(f"        {url}")
        print(f"        {type(exc).__name__}: {str(exc)[:200]}")
        return
    ctype = resp.headers.get("content-type", "")
    text = resp.text
    print(f"\n  {resp.status_code}  {label}")
    print(f"        {url}")
    print(f"        {ctype} · {len(text):,}자")
    body = re.sub(r"\s+", " ", text[:body_chars]).strip()
    print(f"        {body}")


def portal(keyword: str) -> None:
    """포털 목록 화면에서 데이터셋 제목을 뽑는다."""
    try:
        resp = H.get_once(PORTAL, {"keyword": keyword, "currentPage": 1,
                                   "perPage": 20}, timeout=30)
    except Exception as exc:                           # noqa: BLE001
        print(f"\n[{keyword}] 호출 실패 — {type(exc).__name__}: {str(exc)[:140]}")
        return
    html = resp.text
    print(f"\n[{keyword}] HTTP {resp.status_code} · {len(html):,}자 · "
          f"본문에 '{keyword}' {html.count(keyword)}회")

    # 상세 링크는 /data/<id>/<종류>.do 다. 종류가 openapi / fileData /
    # standard 로 갈린다 — 이 종류가 곧 '자동 수집 되는가' 의 답이다.
    links = re.findall(r'href="(/data/(\d+)/(\w+)\.do)[^"]*"', html)
    if not links:
        # 못 읽었으면 못 읽었다고 적고, 판단할 재료를 남긴다.
        print("   목록 링크를 못 찾았습니다. 받은 앞부분:")
        print("   " + re.sub(r"\s+", " ", html[:500]).strip())
        idx = html.find(keyword)
        if idx > 0:
            print(f"   '{keyword}' 가 나온 자리 주변:")
            print("   " + re.sub(r"\s+", " ", html[max(0, idx - 250):idx + 250]))
        return

    seen: set[str] = set()
    for path, ds_id, kind in links:
        if ds_id in seen:
            continue
        seen.add(ds_id)
        # 제목은 링크 바로 뒤 텍스트에 있다. 링크 위치에서 앞뒤를 떠 본다.
        pos = html.find(path)
        window = html[pos:pos + 600]
        title = re.search(r">\s*([^<>]{4,80}?)\s*<", window[window.find(">"):])
        name = unescape(title.group(1)).strip() if title else "(제목 못 읽음)"
        label = {"openapi": "오픈API", "fileData": "파일",
                 "standard": "표준"}.get(kind, kind)
        print(f"   {label:<7} {name[:54]}")
        print(f"           https://www.data.go.kr{path}")
        if len(seen) >= 12:
            break


TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def dataset_detail(label: str, ds_id: str) -> None:
    """포털 상세 화면에서 **엔드포인트와 항목**을 뽑는다.

    '오픈API 가 있다' 까지는 목록으로 알았다. 그것만으로는 못 쓴다 —
    어떤 주소를 부르고 어떤 칸이 오는지가 붙일 수 있는지를 가른다."""
    url = f"https://www.data.go.kr/data/{ds_id}/openapi.do"
    try:
        resp = H.get_once(url, {}, timeout=30)
    except Exception as exc:                           # noqa: BLE001
        print(f"\n  실패  {label} — {type(exc).__name__}: {str(exc)[:140]}")
        return
    html = resp.text
    print(f"\n  {resp.status_code}  {label}  ({len(html):,}자)")
    print(f"        {url}")

    for pat, name in [(r"https?://[\w.\-]*data\.go\.kr/[\w./\-]+", "엔드포인트 후보"),
                      (r"https?://openapi\.onbid\.co\.kr/[\w./\-]+", "온비드 주소")]:
        hits = sorted({h for h in re.findall(pat, html)
                       if "/data/" not in h and "/tcs/" not in h
                       and not h.endswith((".css", ".js", ".png", ".jpg"))})
        if hits:
            print(f"        [{name}]")
            for h in hits[:8]:
                print(f"          {h}")

    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", TAGS.sub(" ", html)))
    # 물건 성격을 말해 주는 낱말이 실제로 나오는지 센다. 없으면 우리
    # 화면에 얹을 수 없는 자료다.
    for word in ["토지", "공장", "창고", "용도", "감정가", "최저", "입찰",
                 "소재지", "주소", "위도", "경도", "활용신청", "일반 인증키"]:
        n = text.count(word)
        if n:
            print(f"        '{word}' {n}회", end="")
    print()
    idx = text.find("요청변수")
    if idx < 0:
        idx = text.find("응답")
    if idx > 0:
        print("        [항목 설명 주변]")
        print("        " + text[idx:idx + 900])


def main() -> None:
    cfg = relay()
    print(f"중계기: {'사용' if cfg.enabled else '없음 (직접 호출 — 지오블록 가능)'}")

    head("1. 공공데이터포털에 '경매·공매' 로 무엇이 열려 있는가")
    print("  오픈API = 자동 수집 가능 · 파일 = 사람이 주기적으로 내려받아야 함")
    for kw in KEYWORDS:
        portal(kw)

    head("2. 온비드(공매) — 찾은 오픈API 가 어떤 칸을 주는가")
    for label, ds_id in ONBID_DATASETS:
        dataset_detail(label, ds_id)
    for label, url, params in ONBID_PROBES:
        show(label, url, params)

    head("3. 법원경매 (대법원)")
    for label, url, params in COURT_PROBES:
        show(label, url, params)

    print()
    print("=" * 72)
    print("읽는 법")
    print("=" * 72)
    print("  오픈API 로 뜨면  → 자동 수집이 된다. 다음 질문은 물건 종류")
    print("                     (토지·공장·창고)와 소재지·감정가·최저가·")
    print("                     매각기일 칸이 있는가다.")
    print("  파일로만 뜨면    → 사람이 주기적으로 내려받아야 한다.")
    print("  아무것도 없으면  → 공식 경로가 없다. 긁는 것은 robots.txt 와")
    print("                     이용약관을 보고 판단할 일이지 기본값이 아니다.")


if __name__ == "__main__":
    main()
