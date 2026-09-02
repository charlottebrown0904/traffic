"""전국도시개발사업정보 표준데이터 → zones_housing.csv.

가설3 의 '택지지구·도시개발이 들어오면 지가는 오른다' 를 재려면 **지정
(고시)일**이 있어야 합니다. 산업단지 현황 파일에는 그것이 없었습니다.
이 표준데이터에는 사업 단위의 날짜가 들어 있습니다.

    https://api.data.go.kr/openapi/tn_pubr_public_urban_dev_proj_api

호스트가 `apis.data.go.kr` 가 아니라 **`api.data.go.kr`** 입니다(s 없음).
표준데이터는 이쪽에 삽니다. 중계기 허용 목록 양쪽에 따로 넣어야 합니다.

## 응답 칸 이름을 모릅니다

이 데이터셋이 어떤 칸을 주는지 문서만으로는 알 수 없습니다. 그래서
**받은 칸을 그대로 저장하고, 무엇을 받았는지 로그에 찍습니다.** 컬럼을
우리 이름으로 접는 일은 h3_files.load_zones 가 후보 목록으로 합니다 —
한 군데서만 하도록 둡니다.

추측해서 매핑을 미리 적어두면, 틀렸을 때 '자료가 없다' 와 '못 읽었다' 를
구분할 수 없게 됩니다.
"""
from __future__ import annotations

import json

import pandas as pd

from .http import get

URL = "https://api.data.go.kr/openapi/tn_pubr_public_urban_dev_proj_api"
PAGE_ROWS = 500          # 표준데이터는 보통 1000 까지 받는다. 보수적으로 둔다.
MAX_PAGES = 60           # 사업 건수가 3만을 넘지는 않는다. 폭주 방지.


def _body(payload: dict) -> dict:
    """표준데이터 응답에서 body 를 꺼낸다. 껍데기 모양이 두 가지다."""
    if "response" in payload:
        return payload["response"].get("body", {}) or {}
    return payload.get("body", payload) or {}


def _items(body: dict) -> list:
    items = body.get("items", [])
    # 어떤 엔드포인트는 {"items": {"item": [...]}} 로 한 겹 더 싼다.
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):          # 결과가 하나면 리스트가 아니다
        items = [items]
    return items or []


def fetch_all(max_pages: int = MAX_PAGES) -> pd.DataFrame:
    rows: list[dict] = []
    total = None
    for page in range(1, max_pages + 1):
        resp = get(URL, {
            "serviceKey": "",            # 중계기가 채운다
            "pageNo": page,
            "numOfRows": PAGE_ROWS,
            "type": "json",
        })
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            head = resp.text[:200].replace("\n", " ")
            raise RuntimeError(f"JSON 이 아닙니다 (page {page}): {head}") from None

        body = _body(payload)
        items = _items(body)
        if page == 1:
            total = body.get("totalCount")
            print(f"  전체 {total} 건 · 한 번에 {PAGE_ROWS} 건씩")
            if items:
                # **받은 칸을 그대로 보여준다.** 이것이 이 탐침의 절반이다.
                print(f"  응답이 준 칸 {len(items[0])}개:")
                for k in items[0]:
                    print(f"    - {k}")
                print(f"  첫 건: {json.dumps(items[0], ensure_ascii=False)[:400]}")
        if not items:
            break
        rows.extend(items)
        print(f"    {page}페이지 {len(items)}건 (누적 {len(rows):,})")
        if len(items) < PAGE_ROWS:
            break
        if total and len(rows) >= int(total):
            break

    df = pd.DataFrame(rows)
    if len(df):
        # 표준데이터는 빈 값을 빈 문자열로 준다. 전부 빈 칸은 버린다 —
        # 남겨두면 '있는데 비었다' 와 '아예 없다' 가 섞인다.
        empty = [c for c in df.columns
                 if df[c].astype(str).str.strip().eq("").all()]
        if empty:
            print(f"  전부 비어 있는 칸 {len(empty)}개 제외: {empty}")
            df = df.drop(columns=empty)
    return df
