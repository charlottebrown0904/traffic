"""부동산통계정보시스템(R-ONE) Open API — 지가변동률·토지거래현황.

한국부동산원이 운영하는 국가승인통계 포털이다. 우리가 이것을 쓰는 이유는
하나다 — **시점수정**.

    감정평가에 관한 규칙 §14, 감정평가 실무기준 [610-1.5.2.3.1]①
    "시점수정은 「부동산 거래신고 등에 관한 법률」에 따라 국토교통부장관이
     조사·발표하는 지가변동률로서 비교표준지가 소재하는 시·군·구의
     같은 용도지역 지가변동률을 적용한다."

그 지가변동률의 원천이 여기다. 공공데이터포털(15134761)에서는 화면이 열리지
않았고, R-ONE 화면에서 표를 하나씩 내려받으면 시군구 × 용도지역 × 달만큼
클릭해야 한다. Open API 는 **요청제한횟수가 없다**(명세서 기재).

세 개의 엔드포인트가 한 줄로 이어진다.

    SttsApiTbl      통계표 목록      어떤 표가 있는가 (STATBL_ID, 주기코드)
    SttsApiTblItm   세부항목 목록    그 표의 항목 ID (ITM_ID)
    SttsApiTblData  자료 조회        실제 숫자 (DTA_VAL)

인증키는 중계기(Vercel 환경변수 `REB_KEY`)에만 둔다. 이쪽은 키를 모른다 —
`Key=__via_relay__` 자리표만 실어 보내면 중계기가 바꿔 끼운다.
"""
from __future__ import annotations

import re

from .http import ApiError, get_json

BASE = "https://www.reb.or.kr/r-one/openapi"
TBL = f"{BASE}/SttsApiTbl"
ITM = f"{BASE}/SttsApiTblItm"
DATA = f"{BASE}/SttsApiTblData"

# 우리에게 필요한 통계표. 값은 R-ONE 이 준 '통계표 목록'(635개) 에서
# 골랐고, 이름은 목록에 적힌 그대로다 — 추측한 ID 가 하나도 없다.
#
# ★ 표시는 산출식이 직접 요구하는 표다.
TABLES = {
    # 시점수정 — 실무기준이 요구하는 순서 그대로다.
    #   ① 같은 시군구 · 같은 용도지역   → 용도지역별 지가변동률 ★
    #   ② 없으면 인접 시군구 · 지역 전체 → 지역별 지가변동률
    "지가변동률_용도지역_월": "A_2024_00007",
    "지가변동률_지역_월": "A_2024_00903",
    "지가변동률_이용상황_월": "A_2024_00008",
    "지가변동률_용도지역_연": "T257803138871680",
    "지가변동률_지역_연": "A_2024_00902",
    "지가변동률_이용상황_연": "T254153138841315",
    # 지가지수 — 변동률을 누적한 수준값. 추이 그래프의 '지가' 축을
    # 우리가 만든 거래 중위값이 아니라 국가승인통계로 바꿀 수 있다.
    "지가지수_용도지역_월": "A_2024_00003",
    "지가지수_지역_월": "A_2024_00901",
    "지가지수_이용상황_월": "A_2024_00004",
    # 교통 접근성과 지가를 국가통계가 직접 이어 놓은 표. 우리 첫 화면의
    # 주장('교통량과 땅값이 같이 움직인다')과 같은 축이다.
    "지가지수_고속철도역세권": "A_2024_00009",
    "지가지수_지하철역세권": "A_2024_00010",
    "지가지수_국가산업단지": "A_2024_00012",
    "지가지수_3기신도시": "A_2024_00015",
    "지가지수_농지": "A_2024_00013",
    "지가지수_인구감소지역": "T245113133421365",
    # 그 밖의 요인 — 거래가 얼마나 도는가. '순수토지'는 건물이 없는
    # 토지만 센 것으로, 우리가 다루는 대상과 정확히 같다.
    "순수토지거래_용도지역_월": "A_2024_00675",
    "순수토지거래_지목_월": "A_2024_00555",
    "순수토지거래_행정구역_월": "A_2024_00538",
    "토지거래_용도지역_월": "A_2024_00648",
    "토지거래_지목_월": "A_2024_00649",
}

# 명세서의 메시지 표. 200 은 오류가 아니라 '그 칸에 자료가 없음'이다 —
# 이것을 예외로 던지면 빈 칸이 많은 시군구에서 수집이 통째로 멈춘다.
EMPTY = "200"
BAD_KEY = "290"


def _walk(node, key):
    """응답 어디에 있든 그 키의 값을 찾아낸다.

    R-ONE 명세서는 출력 **항목**만 적고 감싸는 모양은 적지 않았다.
    서울 열린데이터광장과 같은 계열(Key/Type/pIndex/pSize)이라
    `{"SttsApiTblData":[{...},{"RESULT":…},{"row":[…]}]}` 로 올 것이
    거의 확실하지만, 확실하지 않은 모양에 파서를 못박으면 첫 호출에서
    빈 목록을 받아놓고 '자료가 없다' 로 읽게 된다. 그래서 훑는다.
    """
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(v)
            else:
                found.extend(_walk(v, key))
    elif isinstance(node, list):
        for v in node:
            found.extend(_walk(v, key))
    return found


def _result(payload) -> tuple[str, str]:
    """(코드, 메시지). 못 찾으면 빈 문자열."""
    for res in _walk(payload, "RESULT") + _walk(payload, "result"):
        if isinstance(res, dict):
            code = str(res.get("CODE") or res.get("code") or "")
            msg = str(res.get("MESSAGE") or res.get("message") or "")
            # 'INFO-000' · 'ERROR-290' 처럼 접두가 붙어 오기도 한다.
            m = re.search(r"(\d{3})", code)
            return (m.group(1) if m else code), msg
    return "", ""


def _rows(payload) -> list[dict]:
    for rows in _walk(payload, "row") + _walk(payload, "ROW"):
        if isinstance(rows, list) and all(isinstance(r, dict) for r in rows):
            return rows
        if isinstance(rows, dict):
            return [rows]
    return []


def call(url: str, params: dict, page: int = 1, size: int = 1000) -> tuple[list[dict], str, str]:
    """한 페이지를 부른다. (행, 코드, 메시지)."""
    if size > 1000:
        # 명세서 오류 336. 1,000 을 넘겨 부르면 아무것도 오지 않는다.
        raise ValueError("pSize 는 1,000 을 넘을 수 없습니다 (명세서 오류 336)")
    q = {"Key": "__via_relay__", "Type": "json", "pIndex": page, "pSize": size}
    q.update({k: v for k, v in params.items() if v not in (None, "")})
    payload = get_json(url, q)
    code, msg = _result(payload)
    if code == BAD_KEY:
        raise ApiError(f"인증키가 유효하지 않습니다 (290). 중계기의 REB_KEY 를 확인하세요: {msg}")
    return _rows(payload), code, msg


def pages(url: str, params: dict, size: int = 1000, limit: int = 200):
    """끝까지 넘긴다. 한 페이지가 size 보다 적게 오면 마지막 장이다."""
    for page in range(1, limit + 1):
        rows, code, msg = call(url, params, page=page, size=size)
        if code == EMPTY or not rows:
            return
        yield from rows
        if len(rows) < size:
            return
    raise ApiError(f"{limit} 페이지를 넘겼습니다 — 조건을 좁히세요")


def tables(statbl_id: str | None = None) -> list[dict]:
    """통계표 목록. STATBL_ID 를 주면 그 표 하나만 온다."""
    return list(pages(TBL, {"STATBL_ID": statbl_id}))


def items(statbl_id: str, itm_tag: str | None = None) -> list[dict]:
    """그 표의 세부항목(ITM_ID) 목록."""
    return list(pages(ITM, {"STATBL_ID": statbl_id, "ITM_TAG": itm_tag}))


def cycle_of(statbl_id: str) -> str:
    """주기코드. **추측하지 않고 목록에서 읽는다.**

    SttsApiTblData 는 DTACYCLE_CD 가 필수인데 명세서에 코드값 표가 없다.
    틀린 값을 넣으면 오류가 아니라 '자료 없음(200)' 이 와서, 자료가 없는
    것으로 오해하게 된다 — RTMS 시군구 코드에서 이미 겪은 함정이다.
    """
    rows = tables(statbl_id)
    for r in rows:
        cd = r.get("DTACYCLE_CD") or r.get("dtacycle_cd")
        if cd:
            return str(cd)
    raise ApiError(f"통계표를 찾을 수 없습니다: {statbl_id}")


def data(statbl_id: str, cycle: str | None = None, *, start: str | None = None,
         end: str | None = None, itm_id: str | None = None,
         cls_id: str | None = None, grp_id: str | None = None) -> list[dict]:
    """자료 조회. 시점은 YYYYMM(월) · YYYY(연) 형태다."""
    cycle = cycle or cycle_of(statbl_id)
    return list(pages(DATA, {
        "STATBL_ID": statbl_id, "DTACYCLE_CD": cycle,
        "START_WRTTIME": start, "END_WRTTIME": end,
        "ITM_ID": itm_id, "CLS_ID": cls_id, "GRP_ID": grp_id,
    }))


def price_change(start: str, end: str, *, by: str = "용도지역") -> list[dict]:
    """월 지가변동률. 시점수정에 쓰는 값이다.

    by='용도지역' 이 실무기준 ①, '지역' 이 ② 이다. 순서를 바꾸지 않는다.
    """
    key = f"지가변동률_{by}_월"
    if key not in TABLES:
        raise ValueError(f"by 는 용도지역·지역·이용상황 중 하나입니다: {by}")
    return data(TABLES[key], start=start, end=end)
