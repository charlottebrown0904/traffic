"""도청·시청·군청·구청 좌표를 어디서 받을 수 있는가.

사장님 지시(2026-09-07): "인구 표시 원의 중심은 도청/시청/구청/군청
소재지가 중심이 되도록 수정해 주세요."

지금 원의 중심은 관청이 아니다. **우리 거래 좌표에서 만든 대표점**이다
(webexport._regions — 법정동 중심점들의 중앙값). 거래가 없는 동네가
많은 시군구는 그만큼 끌려간다. 사장님이 보신 것이 그것이다.

관청 좌표는 우리에게 없다. 어디서 받을지를 **기억으로 정하지 않는다.**
이 저장소는 레이어 이름을 세 번 틀렸고 공시지가 원천도 추측으로
시작했다가 헛돌았다. 실제로 받아서 무엇이 오는지 찍는다.

  1. 브이월드 장소검색 (req/search, type=place)   "수원시청"
  2. 브이월드 주소검색 (req/search, type=address)  같은 질의
  3. 브이월드 지오코더 (req/address)               참고용 — 주소를 알아야 쓴다

까다로운 것만 골라 넣었다.
  · 같은 이름의 구가 여럿이다 (동구·서구·남구·북구 — 광주·대구·부산…)
  · 도청은 이름과 소재지가 다르다 (경기도청은 수원, 남부청사는 안성)
  · 시 아래 구청 (수원시 장안구청)
  · 세종은 시청 하나뿐이다

  python scripts/office_probe.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redt.collect.http import get_json                      # noqa: E402
from redt.config import keys                                # noqa: E402

SEARCH = "https://api.vworld.kr/req/search"
ADDRESS = "https://api.vworld.kr/req/address"

# 하나씩 다른 함정을 밟게 골랐다.
CASES = [
    ("경기도청", "도청 — 이름과 소재지가 다르다 (수원)"),
    ("서울특별시청", "특별시청"),
    ("광주광역시청", "광역시청 — 전남과 코드가 섞여 있던 곳"),
    ("세종특별자치시청", "시청 하나뿐인 곳"),
    ("수원시청", "도 아래 시청"),
    ("수원시 장안구청", "시 아래 구청 — 이름이 두 마디다"),
    ("광주광역시 동구청", "같은 이름의 구가 여럿이다"),
    ("무안군청", "군청 — 도청 소재지이기도 하다"),
    ("안성시청", "우리가 실측한 곳"),
]


def key() -> str:
    try:
        return keys().require("vworld")
    except Exception as exc:                     # noqa: BLE001
        sys.exit(f"VWORLD_KEY 가 없습니다: {exc}")


def show(title: str, params: dict) -> dict | None:
    print(f"    {title}")
    try:
        body = get_json(SEARCH if params.get("service") == "search" else ADDRESS,
                        params, timeout=30)
    except Exception as exc:                     # noqa: BLE001
        print(f"      실패: {type(exc).__name__} {exc}")
        return None
    resp = (body or {}).get("response", {})
    status = resp.get("status")
    n = ((resp.get("record") or {}).get("total")
         if isinstance(resp.get("record"), dict) else None)
    print(f"      status={status} total={n}")
    items = ((resp.get("result") or {}).get("items")
             if isinstance(resp.get("result"), dict) else None)
    if not items:
        # 왜 없는지가 중요하다. 응답을 통째로 짧게 찍는다.
        print(f"      (항목 없음) {json.dumps(resp, ensure_ascii=False)[:300]}")
        return None
    top = items[0]
    pt = top.get("point") or {}
    print(f"      1위: {top.get('title')}")
    print(f"           분류 {top.get('category')}")
    addr = top.get("address") or {}
    print(f"           주소 {addr.get('road') or addr.get('parcel')}")
    print(f"           좌표 {pt.get('y')}, {pt.get('x')}")
    if len(items) > 1:
        print(f"      2위: {items[1].get('title')} "
              f"({(items[1].get('point') or {}).get('y')}, "
              f"{(items[1].get('point') or {}).get('x')})")
    return top


def main() -> None:
    k = key()
    print("=== 관청 좌표 원천 탐침 ===")
    print("  찾는 것: 도청·시청·군청·구청의 위경도")
    print("  쓸 수 있으려면 (1) 1위가 실제 그 관청이고 (2) 좌표가 오고")
    print("  (3) 같은 이름의 구를 시·도 이름으로 가릴 수 있어야 한다.\n")

    hits = 0
    for query, why in CASES:
        print(f"  ── {query}  ({why})")
        got = show("장소검색 (type=place)", {
            "service": "search", "request": "search", "version": "2.0",
            "crs": "EPSG:4326", "size": "5", "page": "1",
            "query": query, "type": "place", "format": "json", "key": k,
        })
        if got is None:
            show("주소검색 (type=address)", {
                "service": "search", "request": "search", "version": "2.0",
                "crs": "EPSG:4326", "size": "5", "page": "1",
                "query": query, "type": "address", "category": "road",
                "format": "json", "key": k,
            })
        else:
            hits += 1
        print()

    print(f"  장소검색이 좌표를 준 것: {hits}/{len(CASES)}")
    if hits == len(CASES):
        print("  → 이 경로로 전국 관청 좌표를 한 번 받아 DB 에 담으면 된다.")
    elif hits:
        print("  → 일부만 온다. 안 오는 것의 이름을 어떻게 바꿔야 하는지"
              " 위 응답에서 읽어야 한다.")
    else:
        print("  → 이 경로로는 안 된다. 다른 원천을 찾아야 한다.")


if __name__ == "__main__":
    main()
