"""한국은행 ECOS — 미래 가치의 **시장 층**.

금리·물가·성장률은 전국 모든 땅에 같은 방향으로 작용한다. 필지를 이웃과
다르게 만들지 않고 시장 전체를 위아래로 옮긴다 (docs/future-value.md §2).
그래서 인자로 곱하지 않고 **시나리오 셋**(하락·유지·상승)으로 낸다.

**인증키는 경로 한 칸에 들어간다.** 다른 공공 API 와 다르다.

    /api/StatisticSearch/{인증키}/json/kr/1/100/{표}/{주기}/{시작}/{끝}/{항목}

그래서 우리는 자리표 `__KEY__` 를 넣어 부르고, 키는 서울 중계기가 채운다
(api/relay.js 의 pathKey). 키는 Vercel 환경변수 ECOS_KEY 에만 있고 러너에도
저장소에도 없다.
"""
from __future__ import annotations

from . import http

BASE = "https://ecos.bok.or.kr/api"
KEY_SLOT = "__KEY__"

# 쓸 표. 코드는 ECOS 통계표 코드다.
#   주기 M=월 · Q=분기 · A=년
SERIES = {
    "policy_rate": ("722Y001", "M", "0101000", "한국은행 기준금리"),
    "cd91":        ("721Y001", "M", "2010000", "CD 91일 금리"),
    "bond3":       ("721Y001", "M", "5020000", "국고채 3년"),
    "cpi":         ("901Y009", "M", "0",       "소비자물가지수"),
    "gdp_growth":  ("200Y002", "Q", "1400",    "실질 GDP 성장률"),
}


def url(table: str, cycle: str, start: str, end: str, item: str,
        rows: int = 1000) -> str:
    """ECOS 조회 주소. 키 자리에는 자리표를 둔다 — 키는 중계기만 안다."""
    return (f"{BASE}/StatisticSearch/{KEY_SLOT}/json/kr/1/{rows}"
            f"/{table}/{cycle}/{start}/{end}/{item}")


def rows(name: str, start: str, end: str, timeout: int = 60) -> list[dict]:
    """한 계열을 받아 [{time, value}] 로. 없는 이름이면 KeyError."""
    table, cycle, item, _label = SERIES[name]
    res = http.get_json(url(table, cycle, start, end, item), {}, timeout=timeout)
    if not isinstance(res, dict):
        return []
    # 실패하면 {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
    if "RESULT" in res:
        raise RuntimeError(f"ECOS: {res['RESULT'].get('MESSAGE', res['RESULT'])}")
    body = res.get("StatisticSearch") or {}
    out = []
    for r in body.get("row") or []:
        v = r.get("DATA_VALUE")
        if v in (None, "", "-"):
            continue
        try:
            out.append({"time": str(r.get("TIME")), "value": float(v)})
        except ValueError:
            continue
    return out


# ── 코드는 추측하지 않고 물어본다 ────────────────────────────────
#
# 처음에 실질 GDP 성장률을 200Y002/1400 으로 적었다. 추측이었고 틀렸다 —
# '해당하는 데이터가 없습니다' 가 돌아왔다. ECOS 는 없는 표를 물어도 없는
# 항목을 물어도 같은 말을 한다. 그래서 목록을 받아 눈으로 고른다.
#
#   StatisticTableList  표 목록 (부모 코드를 주면 그 아래)
#   StatisticItemList   그 표의 항목 목록 — ITEM_CODE 가 우리가 쓸 값이다

def list_url(kind: str, code: str, rows: int = 200) -> str:
    return f"{BASE}/{kind}/{KEY_SLOT}/json/kr/1/{rows}" + (f"/{code}" if code else "")


def _list(kind: str, code: str, key: str, timeout: int = 60) -> list[dict]:
    res = http.get_json(list_url(kind, code), {}, timeout=timeout)
    if isinstance(res, dict) and "RESULT" in res:
        raise RuntimeError(f"ECOS: {res['RESULT'].get('MESSAGE', res['RESULT'])}")
    return ((res or {}).get(key) or {}).get("row") or []


def tables(parent: str = "", timeout: int = 60) -> list[dict]:
    """통계표 목록. parent 를 비우면 최상위."""
    return _list("StatisticTableList", parent, "StatisticTableList", timeout)


def items(table: str, timeout: int = 60) -> list[dict]:
    """그 표의 항목 목록. ITEM_CODE 가 SERIES 에 적을 값이다."""
    return _list("StatisticItemList", table, "StatisticItemList", timeout)
