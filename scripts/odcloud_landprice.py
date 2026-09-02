"""공시지가 시계열 원천 찾기 — odcloud 전국개별공시지가 표준데이터(15029071).

왜 이게 필요한가
----------------
브이월드는 좌표와 현재 공시지가를 주지만 **시계열을 안 준다.**
WFS 는 stdrYear 를 받아들이는 척하고 무시하고, 속성 API 는 두세 해만
줍니다 (docs/land-price-fallback.md). 연도 고정효과를 넣은 회귀에는
두세 해로 들어갈 수 없습니다.

앞서 "위약 밴드를 못 추정하면 공시지가로 넘어간다" 를 착수 조건으로
적어 뒀는데, run 7 에서 그 조건이 충족됐습니다.

무엇을 확인하는가
-----------------
odcloud 는 데이터셋을 uddi 로 부릅니다. 그 uddi 는 포털 페이지에만 적혀
있어 추측할 수 없습니다. 그래서 두 단계로 갑니다.

  1. 포털 페이지를 받아 uddi 를 긁는다
  2. 각 uddi 를 perPage=3 으로 불러 **필드 이름과 실제 값**을 본다

값을 봅니다. 건수만 보면 "연도별로 3건씩 온다" 를 '연도가 먹는다' 로
잘못 읽습니다. 브이월드 WFS 에서 정확히 그렇게 당했습니다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redt.collect.http import get_once          # noqa: E402
from redt.config import keys                    # noqa: E402

PORTAL = "https://www.data.go.kr/data/15029071/openapi.do"
ODCLOUD = "https://api.odcloud.kr/api/15029071/v1"

# 연도로 쓸 수 있는 필드 이름 후보. 하나라도 있으면 시계열 가능성이 있다.
YEAR_KEYS = ("기준연도", "기준년도", "stdrYear", "baseYear", "year", "기준일자", "데이터기준일자")
PRICE_KEYS = ("개별공시지가", "공시지가", "지가", "price", "amount")
PNU_KEYS = ("고유번호", "PNU", "pnu", "필지고유번호")


def find_uddis() -> list[str]:
    print(f"1. 포털 페이지에서 uddi 를 찾습니다 — {PORTAL}")
    try:
        resp = get_once(PORTAL, {})
        text = resp.text
    except Exception as exc:                      # noqa: BLE001
        print(f"   실패: {exc}")
        return []
    print(f"   HTTP {resp.status_code} · {len(text):,}바이트")
    found = sorted(set(re.findall(r"uddi:[0-9a-fA-F-]{8,}", text)))
    print(f"   uddi {len(found)}개: {found[:5]}")
    if not found:
        # 페이지 구조가 바뀌었을 수 있다. 본문 일부를 남겨 다음 사람이 보게 한다.
        print("   ⚠ uddi 를 못 찾았습니다. 본문 앞 400자:")
        print("   " + text[:400].replace("\n", " "))
    return found


def peek(uddi: str) -> dict | None:
    url = f"{ODCLOUD}/{uddi}"
    try:
        resp = get_once(url, {"page": 1, "perPage": 3,
                              "returnType": "JSON",
                              "serviceKey": keys().require("data_go_kr")})
    except Exception as exc:                      # noqa: BLE001
        print(f"   {uddi}: 호출 실패 — {exc}")
        return None

    body = resp.text
    if resp.status_code != 200:
        # 오류 본문을 버리지 않는다. 답이 그 안에 있던 적이 있다.
        print(f"   {uddi}: HTTP {resp.status_code} — {body[:300]}")
        return None
    try:
        payload = json.loads(body)
    except ValueError:
        print(f"   {uddi}: JSON 아님 — {body[:200]}")
        return None

    data = payload.get("data") or []
    total = payload.get("totalCount")
    if not data:
        print(f"   {uddi}: 행 없음 (totalCount={total})")
        return None

    fields = list(data[0].keys())
    year_f = [k for k in fields if any(y in k for y in YEAR_KEYS)]
    price_f = [k for k in fields if any(y in k for y in PRICE_KEYS)]
    pnu_f = [k for k in fields if any(y in k for y in PNU_KEYS)]
    print(f"   {uddi}: totalCount={total:,}" if isinstance(total, int)
          else f"   {uddi}: totalCount={total}")
    print(f"      필드 {len(fields)}개: {fields}")
    print(f"      연도 후보 {year_f} · 가격 후보 {price_f} · PNU 후보 {pnu_f}")
    print(f"      첫 행 값: {json.dumps(data[0], ensure_ascii=False)[:400]}")
    return {"uddi": uddi, "total": total, "fields": fields,
            "year": year_f, "price": price_f, "pnu": pnu_f, "sample": data[0]}


def main() -> int:
    uddis = find_uddis()
    if not uddis:
        print("\n결론: uddi 를 못 찾아 확인할 수 없습니다.")
        return 1

    print("\n2. 각 uddi 를 실제로 불러 봅니다")
    hits = [h for h in (peek(u) for u in uddis[:8]) if h]

    print("\n=== 결론 ===")
    if not hits:
        print("어느 uddi 도 자료를 주지 않았습니다.")
        return 1

    usable = [h for h in hits if h["year"] and h["price"]]
    if not usable:
        print("연도와 가격을 함께 주는 데이터셋이 없습니다.")
        print("→ 이 원천으로는 공시지가 '시계열' 을 만들 수 없습니다.")
        print("   남은 길: 연도별 파일(15004246)을 사람이 받아 올리는 것.")
        return 1

    for h in usable:
        print(f"쓸 수 있습니다: {h['uddi']}")
        print(f"  연도 {h['year']} · 가격 {h['price']} · PNU {h['pnu']}")
        print(f"  전체 {h['total']:,}행" if isinstance(h["total"], int) else "")
    print("\n주의: 연도 필드가 있다고 **연도별로 여러 해가 들어 있다는 뜻은 아닙니다.**")
    print("      다음 단계에서 연도별 distinct 값을 세어 확인해야 합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
