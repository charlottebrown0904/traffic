"""도청·시청·군청·구청 좌표를 어디서 받을 수 있는가.

요구사항(2026-09-07): "인구 표시 원의 중심은 도청/시청/구청/군청
소재지가 중심이 되도록 수정해 주세요."

지금 원의 중심은 관청이 아니다. **우리 거래 좌표에서 만든 대표점**이다
(webexport._regions — 법정동 중심점들의 중앙값). 거래가 없는 동네가
많은 시군구는 그만큼 끌려간다. 보고된 것이 그것이다.

관청 좌표는 우리에게 없다. 어디서 받을지를 **기억으로 정하지 않는다.**
이 저장소는 레이어 이름을 세 번 틀렸고 공시지가 원천도 추측으로
시작했다가 헛돌았다. 실제로 받아서 무엇이 오는지 찍는다.

  1. 공공데이터포털 재정경제부_공공기관 정보 조회 서비스 (15125287)
     지목된 자료(2026-09-07). **문서 페이지를 먼저 읽는다** —
     엔드포인트와 오퍼레이션 이름을 추측하면 404 를 '자료 없음' 으로
     오해한다. 이 저장소가 공시지가에서 실제로 그랬다.
  2. 브이월드 장소검색 (req/search, type=place)   "수원시청"
  3. 브이월드 주소검색 (req/search, type=address)  같은 질의

1번에 대해 미리 적어 두는 의심 — '공공기관' 은 공공기관운영법상
공기업·준정부기관·기타공공기관(약 330곳)을 가리키는 말이고,
지방자치단체(시청·군청·구청)는 그 법의 적용 대상이 아니다. 그러니
한국도로공사·LH 는 있어도 수원시청은 없을 수 있다. **그래도 받아
본다** — 기억으로 답하지 않는다는 것이 이 저장소의 규칙이고,
지사·지점 정보를 함께 준다고 적혀 있어 무엇이 오는지는 봐야 안다.

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
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redt.collect.http import get_json, get_once            # noqa: E402
from redt.config import keys                                # noqa: E402

SEARCH = "https://api.vworld.kr/req/search"
ADDRESS = "https://api.vworld.kr/req/address"

# 지목된 자료. 문서 페이지에서 엔드포인트를 읽어 온다.
PORTAL_DOC = "https://www.data.go.kr/data/15125287/openapi.do"

# 문서에 적힌 서비스URL 을 찾아낼 정규식. 포털 문서는 표 안에 주소를
# 그대로 적어 두므로, 이름을 맞히는 대신 **적혀 있는 것을 줍는다.**
ENDPOINT_RE = re.compile(
    r"https?://(?:apis?|api)\.(?:data\.go\.kr|odcloud\.kr)/[\w./-]+")

# 우리가 이 자료에서 찾는 것. 이름을 모르므로 **뜻으로** 훑는다.
WANTED = {
    "주소·소재지": ("addr", "주소", "소재지", "location"),
    "위도·경도": ("lat", "lon", "위도", "경도", "coord", "x", "y"),
    "기관명": ("name", "기관", "nm"),
    "기관유형": ("type", "유형", "구분", "gubun"),
}

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
        print(f"  브이월드 키가 없습니다 — B 는 건너뜁니다: {exc}")
        return ""


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


def walk(node, path=""):
    """중첩된 응답을 통째로 훑어 (경로, 값) 을 낸다.

    이름을 맞히지 않기 위해서다. 응답 모양이 items 안인지 body 안인지
    모르므로, 잎사귀를 다 꺼내 놓고 뜻으로 고른다.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node[:2]):        # 앞의 두 건이면 모양은 다 보인다
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, node


def probe_portal() -> None:
    """재정경제부_공공기관 정보 조회 서비스 (15125287).

    요구사항(2026-09-07): "공공데이터포털의 재정경제부_공공기관 정보
    조회 서비스 API 확인해 보세요."
    """
    print("=" * 60)
    print("A. 공공데이터포털 — 재정경제부_공공기관 정보 조회 서비스")
    print("=" * 60)

    # ① 문서 페이지를 읽는다. 엔드포인트를 맞히지 않는다.
    print(f"  문서: {PORTAL_DOC}")
    try:
        resp = get_once(PORTAL_DOC, {}, timeout=30)
        html = resp.text
        print(f"    {resp.status_code} · {len(html):,}바이트")
    except Exception as exc:                     # noqa: BLE001
        print(f"    실패: {type(exc).__name__} {exc}")
        return

    found = []
    for m in ENDPOINT_RE.finditer(html):
        u = m.group(0).rstrip(".,)'\"")
        if u not in found:
            found.append(u)
    print(f"    문서에 적힌 서비스URL {len(found)}개")
    for u in found[:12]:
        print(f"      {u}")
    if not found:
        # 문서가 자바스크립트로 그려지면 주소가 HTML 에 없다. 그때는
        # 무엇이 왔는지 앞머리를 찍어 다음 사람이 판단할 수 있게 한다.
        print("    → HTML 에 주소가 없다. 앞머리 400자:")
        print("      " + html[:400].replace("\n", " "))
        return

    # ② 실제로 불러 본다. 응답 칸을 통째로 찍는다.
    for url in found[:6]:
        print(f"\n  호출: {url}")
        params = {"serviceKey": "", "page": 1, "perPage": 10,
                  "pageNo": 1, "numOfRows": 10, "type": "json",
                  "returnType": "JSON", "resultType": "json"}
        try:
            body = get_json(url, params, timeout=30)
        except Exception as exc:                 # noqa: BLE001
            print(f"    실패: {type(exc).__name__} {str(exc)[:200]}")
            continue
        leaves = list(walk(body))
        print(f"    잎사귀 {len(leaves)}개")
        for path, val in leaves[:40]:
            v = str(val)
            print(f"      {path} = {v[:60]}")

        # 찾던 것이 있는가.
        print("    ── 찾던 것 ──")
        for label, needles in WANTED.items():
            hit = [p for p, _ in leaves
                   if any(n.lower() in p.lower() for n in needles)]
            print(f"      {label}: {', '.join(hit[:5]) if hit else '없음'}")

        # 지방자치단체가 들어 있는가. 이것이 이 자료를 쓸 수 있는지를
        # 가르는 유일한 물음이다.
        text = json.dumps(body, ensure_ascii=False)
        gov = [w for w in ("시청", "군청", "구청", "도청", "특별시", "광역시")
               if w in text]
        print(f"      지자체 흔적: {', '.join(gov) if gov else '없음'}")


def main() -> None:
    print("=== 관청 좌표 원천 탐침 ===")
    print("  찾는 것: 도청·시청·군청·구청의 위경도\n")

    try:
        probe_portal()
    except Exception as exc:                     # noqa: BLE001
        # 한 경로가 죽어도 다른 경로는 봐야 한다. 한 번 도는 데
        # 워크플로 한 판이 드는데 절반만 보고 끝내면 두 번 돌게 된다.
        print(f"  포털 탐침이 죽었습니다: {type(exc).__name__} {exc}")

    print()
    print("=" * 60)
    print("B. 브이월드 장소검색")
    print("=" * 60)
    k = key()

    if not k:
        return
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
