"""관청(도청·시청·군청·구청) 위치 수집 — 브이월드 장소검색.

사장님 지시(2026-09-07): "인구 표시 원의 중심은 도청/시청/구청/군청
소재지가 중심이 되도록 수정해 주세요."

## 왜 이 경로인가

탐침(run 39, scripts/office_probe.py)이 9곳 중 9곳에서 좌표를 줬다.
이름·분류·도로명주소·좌표가 함께 온다.

    1위: 안성시청
         분류 지방행정기관
         주소 경기도 안성시 봉산동 31-3
         좌표 37.007907944456846, 127.27998856070545

## 두 가지 함정

**1위가 그 관청이 아닐 수 있다.** '수원시 장안구청' 을 물었더니 1위가
"수원시-장안구청종합구민회관보건소" 였고 분류가 '산업용가스제조업'
이었다(분류가 잘못 붙은 항목이다). 2위가 '장안구청' 이었다.

**같은 이름의 구가 여럿이다.** 동구·서구·남구·북구·중구는 전국에
흩어져 있다. 이름만으로는 어느 것인지 못 가른다.

둘 다 **우리가 이미 가진 대표점**으로 푼다. 대표점은 몇 km 어긋나지만
다른 도시와 헷갈릴 만큼 어긋나지는 않는다. 후보 중에서 대표점에 가장
가까운 것을 고르고, 그래도 너무 멀면 집지 않고 남긴다 — 조용히 틀린
좌표를 쓰는 것보다 빈 것이 낫다.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from ..config import keys
from .http import get_json

SEARCH = "https://api.vworld.kr/req/search"

# 분류에 이 말이 들어간 것만 관청으로 본다. 붙어 있는 세부 분류는
# 여러 가지다 — '지방행정기관', '지방행정기관 > 구청',
# '지방행정기관 > 특별/광역시청'.
GOV_CATEGORY = "지방행정기관"

# 대표점에서 이만큼 넘게 떨어진 것은 다른 곳의 같은 이름 관청으로 본다.
#
# **단위마다 다르다.** 이 검사는 같은 이름을 가른다는 목적 하나뿐인데,
# 이름이 겹치는 정도가 단위마다 다르기 때문이다.
#
#   gu    동구·서구·남구·북구·중구가 전국에 흩어져 있다. 촘촘해야 한다.
#         40km 는 '같은 시군구 안의 오차' 와 '옆 도시' 를 가르는 자리다 —
#         가장 넓은 시군구(홍천군)의 반지름이 그쯤이다.
#   si    겹치는 것이 몇 없다(고성군은 강원·경남에 둘). 그 둘은 200km
#         떨어져 있어 60km 면 충분히 갈린다.
#   sido  17개 이름이 다 다르다. 가를 것이 없다.
#         **여기서 좁게 잡으면 안 된다** — 도청은 인구중심에서 멀리
#         있는 일이 흔하다. 경북도청 안동, 충남도청 홍성, 전남도청 무안.
#         검사 결과 울릉군만 있는 도에서 경북도청(215km)이 걸러졌다.
#         그래도 완전히 끄지는 않는다. 엉뚱한 것을 집으면 알아야 한다.
MAX_KM = {"gu": 40.0, "si": 60.0, "sido": 400.0}
DEFAULT_MAX_KM = 40.0


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 점 사이 거리(km). 후보를 고르는 데만 쓰므로 구면 근사로 충분하다."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def search_place(query: str, size: int = 10) -> list[dict]:
    """장소검색. 좌표가 없는 항목은 버린다."""
    body = get_json(SEARCH, {
        "service": "search", "request": "search", "version": "2.0",
        "crs": "EPSG:4326", "size": str(size), "page": "1",
        "query": query, "type": "place", "format": "json",
        "key": keys().require("vworld"),
    }, timeout=30)
    resp = (body or {}).get("response") or {}
    if resp.get("status") != "OK":
        return []
    result = resp.get("result") or {}
    out = []
    for item in (result.get("items") or []):
        pt = item.get("point") or {}
        try:
            lat, lon = float(pt["y"]), float(pt["x"])
        except (KeyError, TypeError, ValueError):
            continue
        addr = item.get("address") or {}
        out.append({
            "name": item.get("title") or "",
            "category": item.get("category") or "",
            "road_addr": addr.get("road") or addr.get("parcel") or "",
            "lat": lat, "lon": lon,
        })
    return out


def pick(cands: list[dict], anchor: tuple[float, float],
         max_km: float = DEFAULT_MAX_KM) -> dict | None:
    """대표점에 가장 가까운 관청을 고른다.

    분류가 '지방행정기관' 인 것을 먼저 본다. 그런 것이 하나도 없으면
    (분류가 잘못 붙은 항목이 그렇다) 전체에서 다시 고른다 — 장안구청이
    실제로 그 경우였고, 좌표는 멀쩡했다.
    """
    lat0, lon0 = anchor
    for pool in ([c for c in cands if GOV_CATEGORY in c["category"]], cands):
        if not pool:
            continue
        best = min(pool, key=lambda c: km_between(lat0, lon0, c["lat"], c["lon"]))
        d = km_between(lat0, lon0, best["lat"], best["lon"])
        if d <= max_km:
            return dict(best, dist_km=round(d, 2))
    return None


def office_name(label: str) -> str:
    """행정구역 이름 → 관청 이름.

    '수원시 장안구' 는 '장안구청' 으로 묻는다. '수원시장안구청' 으로는
    안 나오고, '수원시 장안구청' 으로 물으면 1위가 엉뚱한 것이 온다.
    어느 장안구인지는 대표점이 가른다.
    """
    return label.split()[-1] + "청"


def fetch_one(label: str, anchor: tuple[float, float],
              level: str = "gu") -> dict | None:
    """이름 하나에 대해 관청을 찾는다. 못 찾으면 None.

    두 번 묻는다. 짧은 이름('장안구청')이 먼저인 이유는 그것이 실제
    간판이기 때문이다. 그래도 없으면 붙여 쓴 이름을 시도한다 —
    '광주광역시동구청' 처럼 붙여 등록된 것이 있다.
    """
    limit = MAX_KM.get(level, DEFAULT_MAX_KM)
    for query in (office_name(label), label.replace(" ", "") + "청"):
        got = pick(search_place(query), anchor, limit)
        if got:
            return dict(got, label=label, query=query)
    return None


def sido_of(road_addr: str) -> str:
    """도로명주소의 첫 마디가 시도 이름이다.

    실거래 API 응답에 시도가 없어서(collect/rtms.py) trade.sido 는 늘
    비어 있다. 관청 주소가 우리가 가진 유일한 출처다.
    """
    parts = (road_addr or "").split()
    return parts[0] if parts else ""


def now() -> datetime:
    return datetime.now(timezone.utc)
