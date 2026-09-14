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
    # 2026-09-14. 처음에 200Y002/1400 을 **추측으로** 적었고 없는 표였다.
    # 목록을 훑어(--browse) 찾은 것이 이것이다:
    #   200Y110  2.1.2.2.4. 국내총생산에 대한 지출(원계열, 실질, 분기 및 연간)
    #   10601    국내총생산에 대한 지출  1960Q1~2026Q2
    #
    # 이것은 **수준**(실질 금액)이지 성장률이 아니다. ECOS 가 성장률을 따로
    # 주기도 하지만, 수준을 받아 우리가 재는 쪽을 고른다 — 전년동기대비냐
    # 전기대비냐를 우리가 정할 수 있고, 나중에 기준이 바뀌어도 같은 자리에서
    # 고치면 된다. 받은 값과 우리가 만든 값을 섞지 않으려고 둘 다 담는다.
    "gdp_real":    ("200Y110", "Q", "10601",   "실질 GDP (원계열, 분기)"),
}

# 받은 계열에서 **우리가 만들어 내는** 계열. {새 이름: (원본, 시차, 이름)}
#
# 분기 자료의 전년동기대비는 네 분기 전과 견준다. 전기대비(시차 1)로 하면
# 계절이 그대로 남아 봄·가을마다 오르내린다 — 원계열이라 더 그렇다.
DERIVED = {
    "gdp_growth": ("gdp_real", 4, "실질 GDP 성장률 (전년동기대비 %)"),
}


def growth(rows: list[dict], lag: int) -> list[dict]:
    """수준 계열 → 시차 대비 증감률(%). 기간이 비면 그 자리는 건너뛴다.

    **차례대로 있다고 믿지 않는다.** 받은 순서가 뒤죽박죽이면 네 칸 앞이
    네 분기 전이 아니게 된다. 기간으로 세워 놓고, 짝이 실제로 있는지
    확인한 것만 낸다 — 없는 분기를 이웃으로 때우면 조용히 틀린다.
    """
    by = {r["time"]: r["value"] for r in rows}
    times = sorted(by)
    out = []
    for i, t in enumerate(times):
        if i < lag:
            continue
        base_t = times[i - lag]
        base = by[base_t]
        # 네 칸 앞이 정말 네 분기 전인가 — 빠진 분기가 있으면 아니다.
        if _quarters_between(base_t, t) != lag:
            continue
        if not base:
            continue
        out.append({"time": t, "value": (by[t] - base) / base * 100.0})
    return out


def _quarters_between(a: str, b: str) -> int | None:
    """'2015Q1' 과 '2016Q1' 사이의 분기 수. 모양이 다르면 None."""
    try:
        ya, qa = int(a[:4]), int(a[5])
        yb, qb = int(b[:4]), int(b[5])
    except (ValueError, IndexError):
        return None
    if a[4] not in "Qq" or b[4] not in "Qq":
        return None
    return (yb - ya) * 4 + (qb - qa)


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

# 통계표 목록은 나무를 **평평하게 펴서** 한 번에 준다. 200건에서 자르면
# 앞쪽(통화·금리)만 보이고 국민계정까지 못 내려간다. 넉넉히 받아 둔다.
def list_url(kind: str, code: str, rows: int = 2000) -> str:
    return f"{BASE}/{kind}/{KEY_SLOT}/json/kr/1/{rows}" + (f"/{code}" if code else "")


def _list(kind: str, code: str, key: str, timeout: int = 60,
          rows: int = 2000) -> list[dict]:
    res = http.get_json(list_url(kind, code, rows), {}, timeout=timeout)
    if isinstance(res, dict) and "RESULT" in res:
        raise RuntimeError(f"ECOS: {res['RESULT'].get('MESSAGE', res['RESULT'])}")
    return ((res or {}).get(key) or {}).get("row") or []


def tables(parent: str = "", timeout: int = 60) -> list[dict]:
    """통계표 목록. parent 를 비우면 최상위."""
    return _list("StatisticTableList", parent, "StatisticTableList", timeout)


def items(table: str, timeout: int = 60) -> list[dict]:
    """그 표의 항목 목록. ITEM_CODE 가 SERIES 에 적을 값이다."""
    return _list("StatisticItemList", table, "StatisticItemList", timeout)
