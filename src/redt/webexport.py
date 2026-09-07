"""DuckDB → 프런트엔드용 정적 JSON.

웹 화면은 DB에 직접 붙지 않는다. 이 단계에서 만든 JSON만 읽으므로
합성 데이터든 실데이터든 화면 코드는 그대로다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import db
from .analyze import scoring
from .config import PROCESSED, ROOT, primary_band, settings

WEB_DATA = ROOT / "public" / "app" / "data"
SYNTHETIC_MARK = PROCESSED / ".synthetic"
# 배포 저장소에 커밋되는 파일이라 지도 표시용 표본은 작게 유지한다.
#
# 전체 개요용(연도 무관) 한 파일과, 연도별 파일을 따로 낸다.
#
# 왜 나누는가. 좌표 있는 거래가 953만 건인데 한 파일에 다 담으면
# 2GB 다. 담아도 못 그린다 — 표식 하나가 DOM 요소 하나라 휴대폰에서는
# 수천 개가 한계다. 그래서 **연도를 골라 그 해만 받는다.** 사장님
# 지시(2026-09-07)의 '거래 연도 선택' 이 그대로 파일 나누는 기준이 된다.
MAX_TRADE_POINTS = 2500          # trades.json — 전 기간 개요
MAX_TRADE_POINTS_YEAR = 3000     # trades-YYYY.json — 그 해만
SAMPLE_SEED = 42          # 표본을 고정해 실행마다 diff 가 생기지 않게 한다

# 말풍선에 보여줄 칸. 지도에 점만 찍혀 있으면 '얼마에 팔렸나' 를
# 알 수 없어서 스크리닝에 못 쓴다.
TRADE_COLS = """
    trade_id, kind, lat, lon, deal_year,
    coalesce(deal_month, 0) AS deal_month,
    price_per_m2, price_krw, area_m2,
    coalesce(sido, '') AS sido,
    coalesce(sigungu, '') AS sigungu,
    coalesce(umd, '') AS umd,
    coalesce(jibun, '') AS jibun,
    coalesce(jimok, '') AS jimok,
    -- 용도지역을 함께 내보냅니다. 지도에서 거래 점을 용도지역 색으로
    -- 칠하기 위해서입니다 — 한국 지적편집도를 읽어온 분들에게는 이
    -- 색이 곧 뜻입니다.
    coalesce(land_use, '') AS land_use,
    building_area_m2,
    build_year,
    coalesce(deal_type, '') AS deal_type,
    coalesce(building_use, '') AS building_use,
    coalesce(geocode_level, '') AS geocode_level
"""

# 어느 거래를 지도에 올릴 수 있는가. 좌표가 있고, 단가가 있고,
# 해제되지 않은 것. **IC 거리로는 거르지 않는다** — 반경 밖 거래도
# 그 자리에 실제로 있었던 거래다.
TRADE_WHERE = ("lat IS NOT NULL AND price_per_m2 IS NOT NULL "
               "AND NOT coalesce(is_cancelled, FALSE)")

# 한국도로공사 TCS 차종 구분. 화면에서 "3종이 뭐냐" 는 물음에 답할 곳이 없어
# 필터만 있고 뜻이 없었다. 요금 체계의 기준이라 그대로 옮긴다.
# 출처: 유료도로법 시행령 별표1 (통행료 차종 구분).
VEHICLE_TYPES = [
    {"code": 1, "label": "1종 승용",
     "desc": "2축 차량 · 윤폭 279.4mm 이하 · 경차 제외. 승용차, 16인승 이하 승합차, 2.5톤 미만 화물차."},
    {"code": 2, "label": "2종 중형",
     "desc": "2축 차량 · 윤폭 279.4mm 초과 · 윤거 1,800mm 이하. 17~32인승 승합차, 2.5~5.5톤 화물차."},
    {"code": 3, "label": "3종 대형",
     "desc": "2축 차량 · 윤폭 279.4mm 초과 · 윤거 1,800mm 초과. 33인승 이상 승합차, 5.5~10톤 화물차."},
    {"code": 4, "label": "4종 대형화물",
     "desc": "3축 대형화물차. 10~20톤."},
    {"code": 5, "label": "5종 특수화물",
     "desc": "4축 이상 특수화물차. 20톤 이상."},
    {"code": 6, "label": "6종 경차",
     "desc": "배기량 1,000cc 미만 · 길이 3.6m, 너비 1.6m, 높이 2.0m 이하."},
]

# 화물 수요를 보려면 3·4·5종을 함께 본다. settings.yaml 의 vehicle_groups 와
# 같은 값을 쓰되, 화면에서 뜻을 설명할 수 있도록 여기에도 이름을 둔다.
VEHICLE_GROUPS = [
    {"key": "total", "label": "전체", "types": [1, 2, 3, 4, 5, 6],
     "desc": "모든 차종의 합."},
    {"key": "freight", "label": "화물 (3·4·5종)", "types": [3, 4, 5],
     "desc": "공장·물류 수요를 가장 직접 반영합니다. 토지·공장 투자에서는 이쪽이 핵심입니다."},
    {"key": "passenger", "label": "승용 (1·6종)", "types": [1, 6],
     "desc": "생활 통행. 주거 수요와 관광 통행이 섞입니다."},
    {"key": "mid", "label": "중형 (2종)", "types": [2],
     "desc": "중형 승합·화물. 표본이 작아 변동이 큽니다."},
]

DISCLAIMER = (
    "과거 실거래 신고 자료와 교통량 통계를 요약한 스크리닝 지표입니다. "
    "미래 가격을 예측하거나 보장하지 않으며, 투자 판단의 책임은 이용자에게 있습니다."
)


def _clean(value):
    """JSON 이 못 다루는 NaN/NumPy 타입을 정리한다."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else round(float(value), 6)
    if isinstance(value, float):
        return None if pd.isna(value) else round(value, 6)
    if value is pd.NaT or value is None:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict("records")]


# 자리를 줄일 칸. 좌표는 소수 5자리면 약 1m 다 — 그보다 정밀해 봐야
# 법정동 중심점은 ±1~2km 오차이고 지번 좌표도 필지 대표점이다.
_TRADE_ROUND = {"lat": 5, "lon": 5, "area_m2": 1, "building_area_m2": 1,
                "price_per_m2": 0}


def _with_usage(df: pd.DataFrame) -> pd.DataFrame:
    """공장·창고를 갈라 `usage` 칸을 붙인다.

    15126470 은 '공장 및 창고 등' 자료라 창고가 처음부터 같이 들어와
    있었다. 한 칸에 담아 두면 화면에서 가릴 수가 없다.

    토지는 가를 것이 없으므로 빈 값이고, _trade_records 가 빈 값을
    싣지 않으므로 파일이 무거워지지도 않는다.
    """
    from .usage import label
    out = df.copy()
    if "kind" not in out or out.empty:
        return out
    blank = [""] * len(out)
    use = out["building_use"].tolist() if "building_use" in out else blank
    jimok = out["jimok"].tolist() if "jimok" in out else blank
    out["usage"] = [label(u, j) if k == "factory" else ""
                    for k, u, j in zip(out["kind"].tolist(), use, jimok)]
    # 원값은 내보내지 않는다. 판정에만 쓰고, 파일에는 결과만 싣는다.
    return out.drop(columns=["building_use"], errors="ignore")


def _trade_records(df: pd.DataFrame) -> list[dict]:
    """거래를 화면용으로 줄여서 내보낸다.

    연도 파일 하나가 휴대폰으로 매번 내려가므로 무게가 그대로 체감된다.
    처음 만들었을 때 4,000건에 1.6MB(건당 377바이트)였고, 그 절반이
    **쓰지도 않는 값**이었다.

      · trade_id 40자 해시 — 지도에서 한 번도 안 쓴다. 정렬에만 쓰고 뺀다
      · 빈 칸 — 토지는 건물면적·건축연도가 늘 비어 있는데 `null` 이라고
        또박또박 적고 있었다. 없는 칸은 아예 안 싣는다 (화면은 undefined
        와 null 을 같게 다룬다)
      · 소수점 — 좌표 6자리·면적 6자리는 뜻이 없다
    """
    out = []
    for row in df.to_dict("records"):
        rec = {}
        for k, v in row.items():
            if k == "trade_id":
                continue                      # 정렬용으로만 쓴다
            v = _clean(v)
            if v is None or v == "":
                continue                      # 없는 칸은 싣지 않는다
            if k in _TRADE_ROUND and isinstance(v, (int, float)):
                digits = _TRADE_ROUND[k]
                v = round(v, digits) if digits else int(round(v))
            rec[k] = v
        out.append(rec)
    return out


def _text(value) -> str:
    """문자열이 아니면 빈 문자열. NaN 을 걸러내는 것이 목적이다."""
    return value if isinstance(value, str) else ""


def _finite(obj):
    """NaN·Infinity 를 None 으로 바꾼다. 중첩된 것까지 훑는다.

    **NaN 은 JSON 이 아니다.** 파이썬 json 은 기본값으로 그것을 `NaN` 이라고
    적어 주고 다시 읽을 수도 있지만, 브라우저의 JSON.parse 는 거부한다.
    그래서 파일은 멀쩡해 보이고 파이썬 검사도 통과하는데 화면만 죽는다.

    실제로 그렇게 됐다. run 21 이 명부에서 영업소 119곳을 새로 등재했는데
    그중 41곳은 시도·시군구를 아직 모른다(좌표를 못 받아 지역을 못 되짚었다).
    그 NaN 이 traffic.json 에 그대로 실려 파일이 JSON 이 아니게 됐고,
    순위 탭이 통째로 꺼졌다.

    코드에는 `meta_row.get("sido") or ""` 라는 방어가 있었다. 그런데
    **NaN 은 파이썬에서 참**이라 `or` 를 그냥 통과한다. 빈 값을 막는
    관용구가 정작 NaN 앞에서만 안 듣는다.
    """
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def _write(name: str, payload) -> Path:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    path = WEB_DATA / name
    # allow_nan=False 가 마지막 벽이다. _finite 가 놓친 것이 있으면 조용히
    # 깨진 파일을 내보내지 않고 여기서 멈춘다 — 화면이 죽고 나서 아는 것보다
    # 러너가 빨개지는 편이 낫다.
    text = json.dumps(_finite(payload), ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return path


def _traffic_ranking() -> dict:
    """지시4 — 연도×차종별 영업소 교통량. 순위 탭이 이 파일 하나만 읽는다.

    값은 **일평균 통행량(대/일)** 이다. 연 합계를 쓰면 연중 개통한 영업소가
    실제보다 적게 다닌 것처럼 보인다 — 12월 한 달만 있는 영업소를 그대로
    합치면 다른 곳의 1/12 로 찍힌다. 순위표에서 그런 값은 그냥 틀린 값이다.

    자리를 아끼려고 [연도][차종] 이차원 배열로 접는다. 영업소 475개 ×
    8년 × 6차종을 객체로 풀면 파일이 몇 배가 되는데, 이 파일은 저장소에
    커밋되어 배포에 실린다.
    """
    with db.connect(read_only=True) as con:
        rows = con.execute("""
            SELECT t.tollgate_id, t.year, t.vehicle_type,
                   sum(t.avg_daily) AS avg_daily
            FROM traffic t
            WHERE t.avg_daily IS NOT NULL AND t.vehicle_type > 0
            GROUP BY 1, 2, 3
        """).fetchdf()
        names = con.execute(
            "SELECT tollgate_id, name, sido, sigungu, lat, lon, "
            "coalesce(src, '') AS src FROM tollgate").fetchdf()

    if rows.empty:
        return {"years": [], "vehicle_types": VEHICLE_TYPES,
                "vehicle_groups": VEHICLE_GROUPS, "rows": [],
                "note": "교통량이 적재되지 않았습니다."}

    years = sorted(int(y) for y in rows["year"].unique())
    types = [v["code"] for v in VEHICLE_TYPES]
    lookup = {(str(r.tollgate_id), int(r.year), int(r.vehicle_type)): float(r.avg_daily)
              for r in rows.itertuples()}
    info = names.set_index("tollgate_id").to_dict("index")

    # 마스터에 아직 없는 영업소(민자고속도로 등)는 이름이 비어 있다. 교통량
    # CSV 에는 이름이 들어 있으므로 그것으로 메운다 — 순위표에 '영업소 685'
    # 라고 찍히면 어디인지 알 수 없다.
    try:
        from .collect.tollgate_fill import names_from_traffic
        csv_names = names_from_traffic()
    except Exception:                              # noqa: BLE001 — 이름은 부가정보
        csv_names = {}

    out = []
    for tid in sorted(rows["tollgate_id"].unique(), key=lambda x: str(x)):
        meta_row = info.get(tid, {})
        grid = [[round(lookup.get((str(tid), y, vt), 0.0)) for vt in types]
                for y in years]
        if not any(any(r) for r in grid):
            continue
        out.append({
            "id": str(tid),
            "name": ((meta_row.get("name") or "").strip()
                     or csv_names.get(str(tid), "")
                     or f"영업소 {tid}"),
            # NaN 은 참이라 `or ""` 를 통과한다. 문자열인지 먼저 본다.
            "sido": _text(meta_row.get("sido")),
            "sigungu": _text(meta_row.get("sigungu")),
            "lat": _clean(meta_row.get("lat")),
            "lon": _clean(meta_row.get("lon")),
            "v": grid,
        })

    return {
        "years": years,
        "types": types,
        "vehicle_types": VEHICLE_TYPES,
        "vehicle_groups": VEHICLE_GROUPS,
        "unit": "일평균 통행량 (대/일)",
        "note": ("연 합계가 아니라 일평균입니다. 연중 개통·폐쇄한 영업소가 "
                 "적게 다닌 것처럼 보이지 않도록 관측일수로 나눴습니다."),
        "rows": out,
    }


# 추이 비교 차트에서 한 계열이 되려면 이만큼은 있어야 한다. 거래 두세 건의
# 중앙값을 선으로 이으면, 잡음이 추세처럼 보인다.
CHART_MIN_TRADES = 5
CHART_MIN_YEARS = 3


def _chart_series() -> dict:
    """지시(2026-09-02) — 교통량·지가·공시지가·반경을 한 그래프에 겹쳐 보기 위한 자료.

    단위가 제각각이라(대/일 vs 원/㎡) 그대로 겹치면 한 계열이 나머지를
    납작하게 눌러 버린다. 주식 비교차트가 하는 것과 같은 방법을 쓴다 —
    **각 계열의 첫 해를 100 으로 두고 지수로 그린다.** 화면에서 원값도
    볼 수 있도록 원값을 함께 보낸다.

    교통량은 traffic.json 에 이미 있으므로 여기서 다시 담지 않는다.
    화면이 두 파일을 합쳐 쓴다. 같은 숫자를 두 번 커밋할 이유가 없다.
    """
    path = PROCESSED / "trades_priced.parquet"
    if not path.exists():
        return {"rows": {}, "note": "trades_priced.parquet 이 없습니다. panel 을 먼저 실행하세요."}

    priced = pd.read_parquet(path)
    if priced.empty:
        return {"rows": {}, "note": "보정된 거래가 없습니다."}

    bands = sorted(priced["band"].dropna().unique().tolist())
    influence = [b for b in bands if float(b.split("-")[1]) <= 5]

    def _fold(df: pd.DataFrame, key: str) -> dict:
        """tollgate × year × <key> → 중앙값 ㎡단가. 얇은 칸은 버린다."""
        agg = (df.groupby(["tollgate_id", "year", key], as_index=False)
               .agg(n=("adj_ln_price", "size"), v=("adj_ln_price", "median")))
        agg = agg[agg["n"] >= CHART_MIN_TRADES]
        out: dict = {}
        for (tid, name), grp in agg.groupby(["tollgate_id", key]):
            if grp["year"].nunique() < CHART_MIN_YEARS:
                continue          # 점 두 개를 선으로 이으면 추세처럼 보인다
            out.setdefault(str(tid), {})[str(name)] = {
                int(r.year): round(float(np.exp(r.v))) for r in grp.itertuples()
            }
        return out

    by_band = _fold(priced, "band")
    # 용도지역은 영향범위(0~5km) 안에서만 본다. 대조 밴드까지 섞으면
    # '그 IC 주변 계획관리 땅값' 이 아니라 그냥 '그 동네 땅값' 이 된다.
    near = priced[priced["band"].isin(influence)]
    by_use = _fold(near, "land_use") if "land_use" in near.columns else {}
    by_kind = _fold(near, "kind")

    tids = set(by_band) | set(by_use) | set(by_kind)
    rows = {t: {"band": by_band.get(t, {}),
                "land_use": by_use.get(t, {}),
                "kind": by_kind.get(t, {})} for t in sorted(tids)}

    return {
        "rows": rows,
        "bands": bands,
        "influence_bands": influence,
        "unit": "원/㎡ (헤도닉 보정 중앙값)",
        "min_trades": CHART_MIN_TRADES,
        "min_years": CHART_MIN_YEARS,
        "landprice": _landprice_series(),
        "note": (f"셀당 거래 {CHART_MIN_TRADES}건 미만, 관측 {CHART_MIN_YEARS}년 미만인"
                 " 계열은 그리지 않습니다. 점 몇 개를 선으로 이으면 잡음이 추세처럼"
                 " 보이기 때문입니다."),
    }


def _landprice_series() -> dict:
    """공시지가 계열. 아직 원천이 없으면 **비었다는 사실을 명시해** 돌려준다.

    화면에서 선이 안 보이는 것과 '자료가 없다' 는 다른 말이다. 앞엣것은
    사용자가 자기 조작을 의심하게 만든다.
    """
    with db.connect(read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "land_price" not in tables:
            return {"rows": {}, "available": False,
                    "reason": ("공시지가 시계열 원천을 아직 확보하지 못했습니다. "
                               "브이월드 WFS 는 연도를 무시하고, 속성 API 는 두세 해만 "
                               "줍니다 (docs/land-price-fallback.md).")}
        df = con.execute("""
            SELECT tollgate_id, year, round(median(price_per_m2)) AS v, count(*) AS n
            FROM land_price WHERE tollgate_id IS NOT NULL
            GROUP BY 1, 2
        """).fetchdf()
    if df.empty:
        return {"rows": {}, "available": False, "reason": "적재된 공시지가가 없습니다."}
    rows: dict = {}
    for tid, grp in df.groupby("tollgate_id"):
        if len(grp) < CHART_MIN_YEARS:
            continue
        rows[str(tid)] = {int(r.year): int(r.v) for r in grp.itertuples()}
    return {"rows": rows, "available": bool(rows)}


def _regions() -> list[dict]:
    """시군구별 인구와 **대표점**.

    대표점은 어디서 오는가 — 우리에게 시군구 경계는 없다. 새로 받아오는
    대신, 이미 가진 **법정동 중심점 좌표의 중앙값**을 쓴다.

      · 법정동 중심점은 지오코딩에서 이미 붙여 둔 값이다 (geocode_level='umd').
      · 거래 좌표 전체의 평균을 쓰면 거래가 몰린 쪽으로 끌려간다. 그래서
        **법정동마다 한 점씩**만 세고, 평균이 아니라 중앙값을 쓴다 —
        섬이나 외딴 법정동 하나가 점을 끌고 가지 못한다.

    행정구역의 기하학적 중심은 아니다. 몇 km 어긋날 수 있고, 화면에도
    '대표점' 이라고 적는다. 인구를 원 크기로 보이는 용도에는 충분하고,
    이것 때문에 API 를 하루치 더 쓰는 것은 맞바꿈이 안 맞는다.
    """
    with db.connect(read_only=True) as con:
        has_region = con.execute("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_name = 'region_year'
        """).fetchone()[0]
        if not has_region:
            return []
        pop = con.execute("""
            SELECT sigungu_cd, year, value
            FROM region_year
            WHERE metric = 'population' AND value IS NOT NULL
            ORDER BY sigungu_cd, year
        """).fetchdf()
        if pop.empty:
            return []
        # 법정동마다 한 점. 같은 법정동에 거래가 천 건이어도 한 번만 센다.
        pts = con.execute("""
            SELECT sigungu_cd,
                   any_value(sigungu) AS name,
                   median(lat) AS lat, median(lon) AS lon,
                   count(*) AS n_umd
            FROM (
                SELECT sigungu_cd, any_value(sigungu) AS sigungu,
                       avg(lat) AS lat, avg(lon) AS lon
                FROM trade
                WHERE lat IS NOT NULL AND umd IS NOT NULL AND umd <> ''
                GROUP BY sigungu_cd, umd
            )
            GROUP BY sigungu_cd
            ORDER BY sigungu_cd
        """).fetchdf()

    centers = {str(r.sigungu_cd): r for r in pts.itertuples(index=False)}
    out = []
    for code, group in pop.groupby("sigungu_cd"):
        c = centers.get(str(code))
        if c is None:
            continue          # 좌표가 없으면 지도에 못 찍는다. 조용히 빼되 수는 센다.
        out.append({
            "sigungu_cd": str(code),
            "name": _text(c.name) or str(code),
            "lat": round(float(c.lat), 6),
            "lon": round(float(c.lon), 6),
            "n_umd": int(c.n_umd),
            "pop": {str(int(r.year)): int(r.value)
                    for r in group.itertuples(index=False)},
        })
    print(f"  행정구역 인구 {len(out)}개 시군구"
          f" (좌표 없어 빠진 것 {pop['sigungu_cd'].nunique() - len(out)}개)")
    return out


def export(band: str | None = None, volume_col: str = "volume_freight") -> dict:
    band = band or primary_band()
    panel_path = PROCESSED / "panel.parquet"
    if not panel_path.exists():
        raise FileNotFoundError("panel.parquet 이 없습니다. `panel` 을 먼저 실행하세요.")
    panel = pd.read_parquet(panel_path)

    with db.connect(read_only=True) as con:
        # ORDER BY 가 없으면 DuckDB 가 매번 다른 순서로 돌려주어, 내용이 같아도
        # 커밋 diff 가 생긴다. 이 파일들은 배포에 함께 커밋되므로 순서를 고정한다.
        # no_traffic: 도로공사 TCS 공공데이터에 통행량이 **한 해도** 없는
        # 영업소. 대부분 민자 운영사가 직접 요금을 걷는 노선이라(마도·
        # 남봉담 등 수도권제2순환 봉담~송산 구간) 도로공사가 그 자료를
        # 갖고 있지 않다. 화면에서 '한산한 IC' 로 보이면 정반대의 결론이
        # 나오므로, 교통량 0 이 아니라 '미공개' 로 구분해 내보낸다.
        tollgates = con.execute("""
            SELECT t.tollgate_id, t.name, t.route_no, t.lat, t.lon,
                   t.sido, t.sigungu,
                   coalesce(t.operator_cd, '') AS operator_cd,
                   (v.tollgate_id IS NULL) AS no_traffic
            FROM tollgate t
            LEFT JOIN (SELECT DISTINCT tollgate_id FROM traffic) v
                   ON v.tollgate_id = t.tollgate_id
            WHERE t.lat IS NOT NULL
            ORDER BY t.tollgate_id
        """).fetchdf()
        trade_total = con.execute("SELECT count(*) FROM trade").fetchone()[0]
        # REPEATABLE 로 표본을 고정한다. 없으면 실행할 때마다 다른 거래가 뽑혀
        # 500KB 파일 전체가 바뀐 것처럼 보인다.
        # **거른 뒤에 뽑는다.** DuckDB 의 USING SAMPLE 은 같은 절에 쓰면
        # WHERE 보다 **먼저** 돈다. 그래서 예전 질의는 원본 표에서 2,500건을
        # 뽑고 그중 조건을 통과한 것만 남겨, 늘 2천 건 남짓밖에 안 나왔다
        # (좌표 없는 거래가 19% 라 그만큼 깎였다). 하위 질의로 감싸야
        # 거른 뒤의 집합에서 뽑는다 — 합성 자료에서 446 → 4,000 으로 확인.
        trades = con.execute(f"""
            SELECT * FROM (
                SELECT {TRADE_COLS}
                FROM (SELECT * FROM trade WHERE {TRADE_WHERE})
                USING SAMPLE reservoir({MAX_TRADE_POINTS} ROWS) REPEATABLE ({SAMPLE_SEED})
            ) ORDER BY trade_id
        """).fetchdf()
        # 연도별 표본. 그 해만 받으므로 한 해에 더 많이 담을 수 있다.
        # 실제 건수도 함께 센다 — 표본만 보여주면 '이 해에 거래가
        # 4천 건뿐' 으로 읽힌다.
        year_counts = con.execute(f"""
            SELECT deal_year, count(*) AS n FROM trade
            WHERE {TRADE_WHERE} GROUP BY 1 ORDER BY 1
        """).fetchdf()
        by_year = {}
        for year in year_counts["deal_year"].dropna().astype(int).tolist():
            by_year[year] = con.execute(f"""
                SELECT * FROM (
                    SELECT {TRADE_COLS}
                    FROM (SELECT * FROM trade
                          WHERE {TRADE_WHERE} AND deal_year = {year})
                    USING SAMPLE reservoir({MAX_TRADE_POINTS_YEAR} ROWS)
                                REPEATABLE ({SAMPLE_SEED})
                ) ORDER BY trade_id
            """).fetchdf()

    try:
        scores = scoring.build_scores(panel, band=band, volume_col=volume_col)
    except (ValueError, KeyError) as exc:
        print(f"  스코어 계산 건너뜀: {exc}")
        scores = pd.DataFrame(columns=["tollgate_id"])

    merged = tollgates.merge(scores, on="tollgate_id", how="left")

    # 상세 패널용 연도별 시계열
    series_cols = ["tollgate_id", "year", "band", "kind", "price_index",
                   "n_trades", "volume_total", "volume_freight", "volume_passenger"]
    available = [c for c in series_cols if c in panel.columns]
    series = panel[available].copy()
    if "price_index" in series:
        series["price_per_m2"] = np.exp(series["price_index"])
        series = series.drop(columns=["price_index"])

    grouped: dict[str, list] = {}
    for tollgate_id, group in series.groupby("tollgate_id"):
        grouped[str(tollgate_id)] = _records(group.drop(columns=["tollgate_id"]))

    # 공장·창고 구분이 전체 자료에서 실제로 몇 건씩인가. 표본이 아니라
    # **전수**를 세야 화면이 '창고가 원래 적다' 와 '못 가른다' 를 가른다.
    from .usage import label as _usage_of
    with db.connect(read_only=True) as con:
        _rows = con.execute("""
            SELECT coalesce(building_use, '') AS use,
                   coalesce(jimok, '') AS jimok, count(*) AS n
            FROM trade WHERE kind = 'factory' GROUP BY 1, 2
        """).fetchdf()
    usage_mix: dict[str, int] = {}
    for _r in _rows.itertuples(index=False):
        _k = _usage_of(_r.use, _r.jimok) or "구분 없음"
        usage_mix[_k] = usage_mix.get(_k, 0) + int(_r.n)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "is_synthetic": SYNTHETIC_MARK.exists(),
        "band": band,
        "volume_col": volume_col,
        "bands": sorted(panel["band"].dropna().unique().tolist()),
        "kinds": sorted(panel["kind"].dropna().unique().tolist()),
        "year_min": int(panel["year"].min()),
        "year_max": int(panel["year"].max()),
        "counts": {
            "tollgates": int(len(merged)),
            "scored": int(scores["tollgate_id"].nunique()) if len(scores) else 0,
            "trades_total": int(trade_total),
            "trades_plotted": int(len(trades)),
            "trades_mapped": int(year_counts["n"].sum()) if len(year_counts) else 0,
        },
        # 연도별 파일이 있다는 것과, 그 해의 **실제 건수**를 함께 알린다.
        # 표본 수만 주면 화면이 '2019년 거래 4,000건' 이라고 말하게 된다.
        # 공장·창고가 실제로 갈렸는지. 화면이 '창고 0건' 을 만났을 때
        # '창고 거래가 없다' 로 말할지 '가를 칸이 비어 있다' 로 말할지가
        # 여기서 갈린다.
        "usage_mix": usage_mix,
        "trade_years": [
            {"year": int(r.deal_year), "total": int(r.n),
             "sample": int(len(by_year.get(int(r.deal_year), [])))}
            for r in year_counts.dropna(subset=["deal_year"]).itertuples()
        ],
        "bands_km": settings()["spatial"]["bands"],
        "disclaimer": DISCLAIMER,
    }

    regions = _regions()
    meta["counts"]["regions"] = len(regions)
    if regions:
        years = sorted({int(y) for r in regions for y in r["pop"]})
        meta["population_years"] = years

    _write("meta.json", meta)
    _write("regions.json", regions)
    _write("traffic.json", _traffic_ranking())
    _write("chart.json", _chart_series())
    _write("tollgates.json", _records(merged))
    _write("trades.json", _trade_records(_with_usage(trades)))
    for year, frame in by_year.items():
        _write(f"trades-{year}.json", _trade_records(_with_usage(frame)))
    # 기간이 줄면 지난 실행의 연도 파일이 남는다. 화면은 meta 의
    # trade_years 만 보므로 안 읽히지만, 저장소에 낡은 자료가 새것인
    # 얼굴로 남아 있는 것이 이 프로젝트에서 이미 한 번 사고를 냈다.
    for stale in WEB_DATA.glob("trades-*.json"):
        try:
            year = int(stale.stem.split("-", 1)[1])
        except ValueError:
            continue
        if year not in by_year:
            stale.unlink()
            print(f"  낡은 연도 파일 삭제: {stale.name}")
    _write("series.json", grouped)
    return meta
