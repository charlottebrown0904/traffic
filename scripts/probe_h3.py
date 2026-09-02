"""가설 3 의 원천을 찾는다 — 산업단지·인구·택지지구·사업체.

가설 3: 주변 시군구 인구, 산업단지, 대기업, 택지지구가 들어오면 지가는 오른다.

이게 세 번째 질문이 아니라 **1·2번의 답을 믿을 수 있게 만드는 조건**이다.
IC 가 뚫린 그 해에 옆에 산업단지가 지정됐다면, 산단이 만든 상승을 IC 공으로
돌리게 된다. 지금 1·2번 추정에는 그 통제가 하나도 없다.

무엇이 필요한가
---------------
  이벤트형 (zone_event)   지정일 + 좌표 + 면적. 산업단지·택지지구.
                          '언제 어디서' 가 있어야 개통 이벤트와 같은 방식으로
                          전후를 가를 수 있다.
  패널형   (region_year)  시군구 × 연도 값. 인구·사업체수·종사자수.
                          해마다 값이 있어야 변화율을 통제에 넣을 수 있다.

이 스크립트는 **받아서 적재하지 않는다.** 무엇이 실제로 오는지만 본다.
필드 이름이 아니라 값을 본다 — 이름만 보고 '연도가 있다' 로 읽었다가
브이월드 WFS 에서 크게 당했다(docs/land-price-fallback.md).

  python scripts/probe_h3.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redt.collect.http import get_once            # noqa: E402
from redt.config import keys                      # noqa: E402

DATA_GO = "https://apis.data.go.kr"
ODCLOUD = "https://api.odcloud.kr/api"
PORTAL = "https://www.data.go.kr/data/{}/openapi.do"

# 찾는 것: 지정일 / 좌표 / 면적 / 연도 / 인구·사업체 수
WANT = {
    "지정일": ("지정일", "지정일자", "designat", "승인일", "고시일", "최초지정"),
    "좌표": ("위도", "경도", "lat", "lon", "xcod", "ycod", "x좌표", "y좌표"),
    "면적": ("면적", "area", "지정면적", "규모"),
    "연도": ("기준연도", "기준년도", "연도", "년도", "stdrYear", "year", "기준일"),
    "지역": ("시군구", "행정구역", "소재지", "주소", "법정동", "sigungu", "지역"),
    "규모값": ("인구", "세대", "사업체", "종사자", "고용", "입주"),
}

# 포털 데이터셋 번호. 이름만으로는 못 맞히므로 페이지에서 uddi 를 긁어 쓴다.
ODCLOUD_SETS = {
    "15041930": "전국산업단지현황통계 (산단공)",
    "15037679": "한국산업단지공단_전국산업단지 현황",
    "15005049": "행정안전부_주민등록 인구 및 세대현황",
    "15098680": "전국 도시개발구역 현황",
}


def _hits(fields: list[str]) -> dict[str, list[str]]:
    out = {}
    for label, keys_ in WANT.items():
        found = [f for f in fields if any(k.lower() in f.lower() for k in keys_)]
        if found:
            out[label] = found
    return out


def find_uddis(dataset: str) -> list[str]:
    try:
        resp = get_once(PORTAL.format(dataset), {})
    except Exception as exc:                       # noqa: BLE001
        print(f"    포털 페이지 실패: {exc}")
        return []
    found = sorted(set(re.findall(r"uddi:[0-9a-fA-F-]{8,}", resp.text)))
    if not found:
        print(f"    HTTP {resp.status_code} · uddi 없음 ({len(resp.text):,}바이트)")
    return found


def peek_odcloud(dataset: str, uddi: str) -> dict | None:
    try:
        resp = get_once(f"{ODCLOUD}/{dataset}/v1/{uddi}",
                        {"page": 1, "perPage": 3, "returnType": "JSON",
                         "serviceKey": keys().require("data_go_kr")})
    except Exception as exc:                       # noqa: BLE001
        print(f"    {uddi}: 호출 실패 — {exc}")
        return None
    if resp.status_code != 200:
        # 오류 본문을 버리지 않는다. 답이 그 안에 있던 적이 있다.
        print(f"    {uddi}: HTTP {resp.status_code} — {resp.text[:250]}")
        return None
    try:
        payload = resp.json()
    except ValueError:
        print(f"    {uddi}: JSON 아님 — {resp.text[:200]}")
        return None

    rows = payload.get("data") or []
    if not rows:
        print(f"    {uddi}: 행 없음 (totalCount={payload.get('totalCount')})")
        return None

    fields = list(rows[0].keys())
    hits = _hits(fields)
    print(f"    {uddi}: {payload.get('totalCount'):,}행" if isinstance(payload.get("totalCount"), int)
          else f"    {uddi}: totalCount={payload.get('totalCount')}")
    print(f"      필드 {len(fields)}개 · 찾은 것 {hits or '없음'}")
    print(f"      첫 행: {json.dumps(rows[0], ensure_ascii=False)[:420]}")
    return {"uddi": uddi, "fields": fields, "hits": hits,
            "total": payload.get("totalCount"), "sample": rows[0]}


def probe_odcloud() -> dict:
    out = {}
    for dataset, label in ODCLOUD_SETS.items():
        print(f"\n[{dataset}] {label}")
        uddis = find_uddis(dataset)
        if not uddis:
            continue
        print(f"    uddi {len(uddis)}개")
        for uddi in uddis[:3]:
            hit = peek_odcloud(dataset, uddi)
            if hit:
                out.setdefault(dataset, []).append(hit)
    return out


def probe_stanparks() -> dict | None:
    """산업단지공단 표준 API — 이름이 안정적인 편이라 따로 시도한다."""
    print("\n[apis.data.go.kr] 산업단지 표준 서비스 후보")
    candidates = [
        ("B552584/IndstrlLandService", "getIndstrlLandList"),
        ("1613000/IndustrialComplexService", "getIndustrialComplexList"),
        ("B490001/nationalIndustrialComplex", "getComplexList"),
    ]
    for service, op in candidates:
        url = f"{DATA_GO}/{service}/{op}"
        try:
            resp = get_once(url, {"serviceKey": keys().require("data_go_kr"),
                                  "pageNo": 1, "numOfRows": 3, "type": "json"})
        except Exception as exc:                   # noqa: BLE001
            print(f"    {service}/{op}: 호출 실패 — {exc}")
            continue
        head = resp.text[:250].replace("\n", " ")
        print(f"    {service}/{op}: HTTP {resp.status_code} — {head}")
        if resp.status_code == 200 and "SERVICE" not in resp.text[:200].upper():
            return {"url": url, "body": resp.text[:1500]}
    return None


def main() -> int:
    print("=== 가설3 원천 탐침 ===")
    print("이벤트형(지정일+좌표)과 패널형(시군구×연도)을 가른다.\n")

    found = probe_odcloud()
    probe_stanparks()

    print("\n=== 결론 ===")
    if not found:
        print("어느 원천도 자료를 주지 않았습니다.")
        print("→ 데이터셋 번호가 바뀌었거나 포털 페이지 구조가 달라졌을 수 있습니다.")
        return 1

    event_ready, panel_ready = [], []
    for dataset, hits in found.items():
        for h in hits:
            has = h["hits"]
            if "지정일" in has and ("좌표" in has or "지역" in has):
                event_ready.append((dataset, h["uddi"], has))
            if "연도" in has and "규모값" in has and "지역" in has:
                panel_ready.append((dataset, h["uddi"], has))

    print(f"\n이벤트형으로 쓸 수 있는 것 {len(event_ready)}개")
    for d, u, has in event_ready:
        print(f"  {d} / {u}")
        print(f"    {has}")
    print(f"\n패널형으로 쓸 수 있는 것 {len(panel_ready)}개")
    for d, u, has in panel_ready:
        print(f"  {d} / {u}")
        print(f"    {has}")

    if not event_ready and not panel_ready:
        print("\n자료는 오는데 우리가 필요한 칸(지정일·좌표·연도)이 없습니다.")
        print("위 '첫 행' 출력을 보고 필드 이름 후보를 넓혀야 합니다.")
        return 1

    print("\n주의: 필드가 있다고 값이 채워져 있다는 뜻은 아닙니다.")
    print("      다음 단계에서 결측률과 연도별 distinct 값을 세어 확인합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
