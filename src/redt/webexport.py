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
# 수천 개가 한계다. 그래서 **연도를 골라 그 해만 받는다.** 2026-09-07
# 요구사항의 '거래 연도 선택' 이 그대로 파일 나누는 기준이 된다.
MAX_TRADE_POINTS = 2500          # trades.json — 전 기간 개요
MAX_TRADE_POINTS_YEAR = 3000     # trades-YYYY.json — 그 해만
SAMPLE_SEED = 42          # 표본을 고정해 실행마다 diff 가 생기지 않게 한다

# 도로 접함 필터의 세 칸 이름. 화면과 meta 가 같은 글자를 써야 하므로
# 여기서 한 번만 정한다.
ROAD_OK = "차 진입 가능"
ROAD_NO = "진입 어려움"
ROAD_UNKNOWN = "조사 안 됨"

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

# 필지 특성. **trade 표에는 없다** — 실거래 API 가 도로접·형상을 주지
# 않아서 브이월드 토지특성(dt_d194)에서 따로 받아 parcel 에 담고,
# 점-다각형으로 맞춘 결과를 trade_parcel 로 이어 놓았다.
#
# 요구사항(2026-09-07): "실거래 내용에 도로접하거나 토지의 모양등을
# 알 수 있는 지도 확인해 주세요." · "도로를 접하는 가가 제일 중요합니다."
# 실측이 그 말을 확인했다 — 차가 들어가느냐가 단가를 +66~67% 가른다.
def _trade_where(alias: str) -> str:
    """TRADE_WHERE 를 별칭 붙여서.

    필지와 조인하면 이름이 겹치는 칸이 생긴다(지목·용도지역·면적).
    지금 조건에 그 셋은 없지만, 조건 쪽을 미리 못박아 두면 나중에
    칸을 하나 더 넣을 때 조용한 모호성으로 죽지 않는다.
    """
    return (f"{alias}.lat IS NOT NULL AND {alias}.price_per_m2 IS NOT NULL "
            f"AND NOT coalesce({alias}.is_cancelled, FALSE)")


PARCEL_COLS = """
    coalesce(pc.road_side, '') AS road_side,
    coalesce(pc.shape, '') AS parcel_shape,
    coalesce(pc.slope, '') AS parcel_slope,
    pc.official_price
"""


def _trade_query(where: str, limit: int) -> str:
    """표본을 뽑은 **뒤에** 필지 특성을 붙인다.

    순서가 중요하다. 먼저 조인하면 수백만 행짜리 결합을 만들어 놓고
    거기서 2천 건을 뽑는 셈이 된다. 뽑고 나서 붙이면 2천 번의 조회다.

    아직 전국을 다 안 훑었으므로 대부분의 거래에는 붙는 것이 없다.
    그래서 LEFT JOIN 이고, 빈 값은 _trade_records 가 알아서 뺀다.
    """
    return f"""
        SELECT s.*, {PARCEL_COLS}
        FROM (
            SELECT {TRADE_COLS}
            FROM (SELECT * FROM trade WHERE {where})
            USING SAMPLE reservoir({limit} ROWS) REPEATABLE ({SAMPLE_SEED})
        ) s
        LEFT JOIN trade_parcel tp ON tp.trade_id = s.trade_id
        LEFT JOIN parcel pc ON pc.pnu = tp.pnu
        ORDER BY s.trade_id
    """

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

# 화물 수요를 보려면 2·3·4·5종을 함께 본다. settings.yaml 의 vehicle_groups 와
# 같은 값을 쓰되, 화면에서 뜻을 설명할 수 있도록 여기에도 이름을 둔다.
VEHICLE_GROUPS = [
    {"key": "total", "label": "전체", "types": [1, 2, 3, 4, 5, 6],
     "desc": "모든 차종의 합."},
    # 2종을 넣었다 (요구사항 2026-09-10): "2종도 물류에 많이 쓰이는
    # 화물차량 임". 2종은 '중형' 묶음으로도 따로 볼 수 있게 남겨 둔다 —
    # 묶음은 나눠 담는 칸이 아니라 보는 방식이다.
    {"key": "freight", "label": "화물 (2·3·4·5종)", "types": [2, 3, 4, 5],
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
                "price_per_m2": 0, "official_price": 0}


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
    # 토지는 개발이 끝났는지를 붙인다. 지목이 실거래 자료에 있는
    # 유일한 단서다 — 도로접·형상은 이 API 가 주지 않는다.
    from .usage import land_stage
    out["stage"] = [land_stage(j) if k == "land" else ""
                    for k, j in zip(out["kind"].tolist(), jimok)]
    # 도로 접함 여부는 **여기서 한 번만** 판정한다. 도로접면은
    # '세로한면(가)' 와 '세로한면(불)' 처럼 한 글자로 갈리므로, 화면에서
    # 문자열을 다시 뜯게 두면 규칙이 두 군데로 갈라져 언젠가 어긋난다.
    # 요구사항(2026-09-07): "도로를 접하는 가가 제일 중요합니다."
    #
    # 'Y'/'N' 로 싣는 이유는 0 이 아니어야 하기 때문이다 — 0 을 실으면
    # 화면의 `if (t.car_ok)` 가 '맹지' 와 '모름' 을 못 가른다.
    if "road_side" in out:
        from .usage import road_car_ok
        out["car_ok"] = ["" if (c := road_car_ok(r)) is None
                         else ("Y" if c else "N")
                         for r in out["road_side"].tolist()]
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


def _stdland_files() -> None:
    """std_land → stdland-{시군구}.json (가장 최근 해) + valuation.json (격차율 표).

    좌표는 아직 없다(브이월드 속성 조회에 없음). 화면은 같은 법정동리
    (PNU 앞 10자리)를 먼저 보고 그다음 시군구 안에서 고른다.
    """
    from . import valuation as V
    with db.connect(read_only=True) as con:
        if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='std_land'"
                           ).fetchone()[0]:
            return
        n = con.execute("SELECT count(*) FROM std_land").fetchone()[0]
        if not n:
            return
        df = con.execute("""
            WITH latest AS (
                SELECT pnu, max(year) AS year FROM std_land
                WHERE price > 0 AND pnu IS NOT NULL GROUP BY pnu
            )
            SELECT s.pnu, s.ld_code, s.ld_name, s.jibun, s.year, s.price, s.jimok, s.area_m2,
                   s.land_use, s.land_use2, s.district, s.use_situation, s.road_side, s.shape,
                   s.slope, s.sigungu_cd, s.lon, s.lat
            FROM std_land s JOIN latest l ON l.pnu = s.pnu AND l.year = s.year
        """).fetchdf()
    keep = set()
    total = 0
    # 빈 문자열은 값이 아니다 — 브이월드가 '' 로 준 용도지역2 가 그대로
    # 실리면 화면이 그것을 이름으로 읽는다.
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].where(df[c].astype(str).str.strip() != "", None)
    for code, g in df.groupby("sigungu_cd"):
        rows = []
        for r in g.itertuples(index=False):
            rows.append({"pnu": r.pnu, "ld": r.ld_code, "nm": r.ld_name, "jb": r.jibun,
                         "y": int(r.year) if r.year == r.year else None,
                         "pr": r.price, "jm": r.jimok, "ar": r.area_m2, "lu": r.land_use,
                         "lu2": r.land_use2, "dz": r.district, "us": r.use_situation,
                         "rs": r.road_side, "sh": r.shape, "sl": r.slope,
                         "lon": r.lon, "lat": r.lat})
        fname = f"stdland-{code}.json"
        _write(fname, {"sigungu": str(code), "n": len(rows), "rows": rows})
        keep.add(fname)
        total += len(rows)
    for stale in WEB_DATA.glob("stdland-*.json"):
        if stale.name not in keep:
            stale.unlink()
    _write("valuation.json", V.tables_for_web())
    years = sorted(int(y) for y in df["year"].dropna().unique())
    print(f"  표준지 {total:,}필지 · 시군구 조각 {len(keep)}개 · 연도 {years[:1]}~{years[-1:]}"
          f" · 격차율 표 valuation.json")


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


def _region_offices() -> dict[str, dict[str, list[float]]]:
    """묶은 단위(시·도, 시·군)의 관청 좌표.

    구 단위는 regions.json 의 각 행이 들고 있으므로 여기 안 싣는다.
    """
    with db.connect(read_only=True) as con:
        has = con.execute("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_name = 'office'
        """).fetchone()[0]
        if not has:
            return {}
        rows = con.execute("""
            SELECT level, key, lat, lon FROM office
            WHERE level IN ('sido', 'si') AND lat IS NOT NULL
        """).fetchdf()
    out: dict[str, dict[str, list[float]]] = {}
    for r in rows.itertuples(index=False):
        out.setdefault(r.level, {})[str(r.key)] = [
            round(float(r.lat), 6), round(float(r.lon), 6)]
    return out


def _region_name_fill() -> dict[str, dict[str, str]]:
    """실거래에 이름이 안 오는 시군구의 **빈 자리를 채울** 이름.

    config/region_names.yaml 이 왜 있는지는 그 파일 머리에 적어 두었다.
    한 줄로 줄이면: 세종특별자치시는 시도 아래에 시군구가 없어서 실거래
    응답의 시군구명 칸이 비어 온다.

    **덮어쓰지 않는다.** 자료에 이름이 있으면 그것이 이긴다.
    """
    path = ROOT / "config" / "region_names.yaml"
    if not path.exists():
        return {}
    import yaml
    with open(path, encoding="utf-8") as fh:
        got = yaml.safe_load(fh) or {}
    return {str(k): dict(v or {}) for k, v in got.items()}


def _parent_si(name: str) -> str:
    """'수원시 장안구' → '수원시'. 아니면 빈 문자열.

    화면에서 축척에 따라 시·군 단위로 묶기 위한 값이다.

    **광역시의 구에는 붙이지 않는다.** '종로구' 는 한 마디로 오므로
    자연히 걸리지 않고, 그것이 맞다 — 서울의 구를 묶을 상위 시는
    서울특별시 자신이고 그것은 시도 단위에서 처리한다.
    """
    parts = name.split()
    if len(parts) == 2 and parts[0].endswith("시") and parts[1].endswith("구"):
        return parts[0]
    return ""


# 행정구역별 땅값. 요구사항(2026-09-08):
#   "행정 구역별 계획관리 땅값 실거래가 연 평균제공"
#   "최근 실거래가격(기간 또는 건수) 기준으로 (기본은 계획관리)
#    축척에따라 보여줍니다"
#
# 용도지역을 묶는 이름과 그 판정 조건. LIKE 로 보는 이유는 자료에
# '계획관리지역' 과 '계획관리' 가 섞여 오기 때문이다.
#
# key 는 파일 이름에 쓴다 — 한글을 URL 에 넣으면 인코딩이 서버마다
# 달라져서 어느 날 조용히 404 가 된다.
# **순서가 뜻을 정한다.** _landprice_case() 가 이것을 CASE WHEN 사슬로
# 펴는데, CASE 는 먼저 맞는 것이 이긴다. 그래서 좁은 것을 위에, 넓은
# 것을 아래에 둔다 —
#
#   제1종일반주거  LIKE '%제1종일반주거%'   ← 먼저
#   일반주거       LIKE '%일반주거%'        ← 나중 (안 그러면 위를 삼킨다)
#   관리           LIKE '%관리%'            ← 맨 나중 (계획·생산·보전을 삼킨다)
#
# 이 순서를 흩뜨리면 조용히 틀린다. 거래가 사라지는 것이 아니라 **엉뚱한
# 칸으로 들어가서**, 화면에는 그럴듯한 숫자가 뜬다.
#
# 요구사항(2026-09-08): "전체 용도지역이 아직 안나오네요. 전부 반영하고
# 체크하면 가격이 반영될 수 있도록 해주세요."
LANDPRICE_GROUPS = [
    # ── 도시지역 (법 §36①1) — 시행령 §30 의 세분 순서 그대로 ──
    #    주거 → 상업 → 공업 → 녹지
    ("제1종전용주거", "제1종전용주거", "jeonyong1"),
    ("제2종전용주거", "제2종전용주거", "jeonyong2"),
    ("제1종일반주거", "제1종일반주거", "ilban1"),
    ("제2종일반주거", "제2종일반주거", "ilban2"),
    ("제3종일반주거", "제3종일반주거", "ilban3"),
    ("준주거", "준주거", "junju"),
    # 세분 없이 신고된 것. 좁은 것들 **뒤에** 와야 삼키지 않는다.
    ("전용주거(세분 없음)", "전용주거", "jeonyong"),
    ("일반주거(세분 없음)", "일반주거", "ilbanju"),
    ("중심상업", "중심상업", "jungsang"),
    ("일반상업", "일반상업", "ilbansang"),
    ("근린상업", "근린상업", "geunrin"),
    ("유통상업", "유통상업", "yutong"),
    ("전용공업", "전용공업", "jeongong"),
    ("일반공업", "일반공업", "ilbangong"),
    ("준공업", "준공업", "jungong"),
    ("보전녹지", "보전녹지", "bonok"),
    ("생산녹지", "생산녹지", "saengnok"),
    ("자연녹지", "자연녹지", "jayeon"),
    # ── 관리지역 (법 §36①2) ──
    ("보전관리", "보전관리", "bojeon"),
    ("생산관리", "생산관리", "saengsan"),
    ("계획관리", "계획관리", "gyehoek"),
    # 2006~2010 의 미세분 신고. 좁은 셋 뒤에 와야 한다.
    ("관리(세분 없음)", "관리", "gwanri"),
    # ── 농림지역 (법 §36①3) · 자연환경보전지역 (§36①4) ──
    ("농림", "농림", "nongrim"),
    ("자연환경보전", "자연환경보전", "jayeonhwan"),
    # ── 용도구역 (법 §38) — **용도지역이 아니다** ──
    ("개발제한구역", "개발제한", "gaebal"),
    # ── 기타 — 법령 어느 칸에도 못 넣는 것. 사유를 함께 싣는다 ──
    ("용도 미지정", "용도미지정", "mijijeong"),
    ("용도 미상", "용도 미상", "misang"),
    ("기타", "기타", "gita"),
]

# 법령 구조 그대로의 갈래 (요구사항 2026-09-09: "분류는 법령기준으로
# 정확히 합니다").
#
#   국토의 계획 및 이용에 관한 법률 §36①  도시지역 / 관리지역 /
#                                          농림지역 / 자연환경보전지역
#   같은 법 시행령 §30①                    주거 · 상업 · 공업 · 녹지의 세분
#   같은 법 §38                             개발제한구역은 **용도구역**이다
#
# '비도시지역' 은 법에 없는 말이라 뺐다. 관리·농림·자연환경보전을 한
# 낱말로 묶어 부르면 편하지만, 편한 말이 법의 칸을 흐린다.
#
# 순서도 법을 따른다. 그래서 계획관리가 예전보다 아래로 내려간다 —
# 화면이 법과 다른 순서를 쓰면, 그 화면을 보고 법을 배운 사람이 나중에
# 등기소에서 헷갈린다.
LANDPRICE_ZONE_TREE = [
    ("도시지역", "주거지역", ["제1종전용주거", "제2종전용주거",
                              "제1종일반주거", "제2종일반주거",
                              "제3종일반주거", "준주거",
                              "전용주거(세분 없음)", "일반주거(세분 없음)"]),
    ("도시지역", "상업지역", ["중심상업", "일반상업", "근린상업", "유통상업"]),
    ("도시지역", "공업지역", ["전용공업", "일반공업", "준공업"]),
    ("도시지역", "녹지지역", ["보전녹지", "생산녹지", "자연녹지"]),
    ("관리지역", "", ["보전관리", "생산관리", "계획관리", "관리(세분 없음)"]),
    ("농림지역", "", ["농림"]),
    ("자연환경보전지역", "", ["자연환경보전"]),
    ("용도구역 (법 §38)", "", ["개발제한구역"]),
    ("기타", "", ["용도 미지정", "용도 미상", "기타"]),
]

# 왜 그 칸에 있는지. 화면이 물음표 뒤에 그대로 보여준다 — 요구사항
# ("정말 분류 못하는 것은 기타로하고 사유 표기").
LANDPRICE_ZONE_NOTE = {
    "전용주거(세분 없음)":
        "시행령 §30 의 제1·2종 세분 없이 '전용주거지역' 으로 신고된 건.",
    "일반주거(세분 없음)":
        "시행령 §30 의 제1·2·3종 세분 없이 '일반주거지역' 으로 신고된 건.",
    "관리(세분 없음)":
        "2006~2010년 신고분. 보전·생산·계획으로 세분되기 전이라"
        " '관리지역' 으로만 적혀 있다.",
    "개발제한구역":
        "용도지역이 아니라 **용도구역**(법 §38)이다. 용도지역 위에"
        " 겹쳐 지정되므로 같은 칸에 놓고 견주면 안 된다.",
    "용도 미지정":
        "신고서에 용도지역 칸이 비어 있다. 그 땅에 용도지역이 없다는"
        " 뜻이 아니라 **적히지 않았다**는 뜻이다.",
    "용도 미상":
        "신고서의 용도지역 값을 법령의 어느 칸으로도 읽을 수 없다.",
    "기타":
        "신고서에 '기타' 로 적혀 있다. 무엇인지는 자료가 말하지 않는다.",
}

# **'최근' 을 무엇으로 자르는가.** 두 가지를 다 낸다 — 어느 쪽도 혼자서는
# 안 된다.
#
#   기간 기준은 시점이 같다. 화면의 모든 지역이 같은 달까지를 본다.
#     대신 거래가 드문 군은 최근 1년이 두세 건이라 값이 튄다.
#   건수 기준은 표본이 같다. 어느 지역이든 최근 N건으로 잰다.
#     대신 시점이 지역마다 다르다 — 어떤 군의 '최근 20건' 은 2011년까지
#     거슬러 올라간다. **그래서 몇 년치인지를 같이 싣는다.**
#
# 기간은 **자료의 마지막 해**를 기준으로 자른다. 지역마다 자기 마지막
# 해를 쓰면, 10년째 거래가 없는 군이 2015년 값을 '최근 1년' 이라고
# 내놓는다. 거래가 없으면 값이 없는 것이 맞다.
LANDPRICE_WINDOWS = [
    ("y1", "최근 1년", "year", 1),
    ("y3", "최근 3년", "year", 3),
    ("y5", "최근 5년", "year", 5),
    ("c20", "최근 20건", "count", 20),
    ("c50", "최근 50건", "count", 50),
]
# **도시지역과 비도시지역을 갈라 적는다.**
#
# 보고된 문제(2026-09-08): "인구가 많고 개발되고, 면적이 적은 도시는
# 도시지역(자연 녹지)의 비율이 높고 비도시지역(계획관리, 생산관리)
# 면적이 매우 적거나 없을 확율이 있습니다."
#
# 우리 자료로 그대로 확인됐다 (최근 5년 토지거래, 30건 이상 시군구):
#
#   인구 5만 미만   39곳   자연녹지  6%   계획+생산 56%
#   인구 5~15만     64곳   자연녹지 15%   계획+생산 48%
#   인구 15~40만    89곳   자연녹지 65%   계획+생산 22%   ← 여기서 뒤집힌다
#   인구 40~80만    31곳   자연녹지 74%   계획+생산 17%
#
# 서울 노원구·인천 부평구·대구 달서구는 자연녹지 100% · 계획관리 0건.
# 최근 5년 계획관리 거래가 다섯 건도 안 되는 시군구가 64곳이다.
#
# 그래서 이 둘을 한 목록에 평평하게 늘어놓으면 안 된다. 부천의 자연녹지와
# 안성의 계획관리를 같은 종류인 것처럼 나란히 놓게 된다.
# name → 대분류. 트리에서 뽑는다 — 두 곳에 적어 두면 언젠가 어긋난다.
LANDPRICE_ZONE_KIND = {
    name: major
    for major, _middle, names in LANDPRICE_ZONE_TREE
    for name in names
}

DEFAULT_LANDPRICE_GROUP = "계획관리"
DEFAULT_LANDPRICE_WINDOW = "y3"

# **거래가 너무 적은 칸은 창째로 싣지 않는다.**
#
# run 49 배포본이 이것을 증명했다. 계획관리 최근 3년 순위 1위가
# **부천시 원미구, 거래 2건, 평당 2,199만원**이었다. 부산 동구 1건,
# 서울 강동구 1건도 상위에 섞였다. 지도에서 그 시군구가 가장 짙은
# 파랑으로 뜨는데, 그것은 자료가 아니라 우연이다.
#
# 다섯 건이면 중앙값이 한 건에 통째로 끌려가지는 않는다. 모자란 창은
# 비운다 — 사용자는 기간을 넓히거나(최근 5년) 건수 기준으로 바꿔서
# 같은 지역을 다시 볼 수 있다.
LANDPRICE_MIN_N = 5

# 말풍선에 그릴 **최근 추이**. 몇 해치를 실을 것인가.
#
# 요구사항(2026-09-08): "마우스 오버랩시 정보와 실거래가격 트랜드 표시".
# 값 하나만 보면 그것이 오르는 중인지 내리는 중인지 알 수 없다. 같은
# 평당 80만원이라도 3년째 오르는 80만과 꺾여 내려온 80만은 다른 물건이다.
#
# 한 해 거래가 두세 건인 리가 흔해서, **세 건 미만인 해는 점을 안 찍는다.**
# 한 건짜리 해를 이어 그리면 그것은 추세가 아니라 잡음이다.
LANDPRICE_TREND_YEARS = 10
TREND_MIN_N = 3


def _landprice_trend(latest_year: int, keys: str, group_by: str) -> dict:
    """(칸, 용도지역) → [[연도, 건수, 중앙값], ...].

    빈 해는 아예 안 싣는다. 촘촘한 배열로 만들면 거래가 드문 리에서
    자리의 대부분이 null 이 된다 — 파일만 무거워지고 그릴 것은 같다.
    """
    since = latest_year - LANDPRICE_TREND_YEARS + 1
    with db.connect(read_only=True) as con:
        df = con.execute(f"""
            SELECT {keys}, grp, deal_year AS y,
                   count(*) AS n, median(price_per_m2) AS p50
            FROM (
                SELECT {keys}, deal_year, price_per_m2,
                       CASE {_landprice_case()} ELSE NULL END AS grp
                FROM trade
                WHERE kind = 'land' AND {TRADE_WHERE}
                  AND sigungu_cd IS NOT NULL AND deal_year >= {since}
            )
            WHERE grp IS NOT NULL
            GROUP BY {group_by}
            HAVING count(*) >= {TREND_MIN_N}
            ORDER BY {group_by}
        """).fetchdf()
    out: dict = {}
    for r in df.itertuples(index=False):
        key = tuple(str(getattr(r, k.split(".")[-1])) for k in keys.split(", "))
        out.setdefault(key + (str(r.grp),), []).append(
            [int(r.y), int(r.n), int(round(float(r.p50)))])
    return out


# 읍면동은 그 위에 하나 더 — 용도지역 통틀어 다섯 건도 안 되는 칸은
# 애초에 파일에 넣지 않는다. 창별로 걸러도 어차피 다 빌 것이고,
# 넣어 봐야 파일만 무거워진다.
UMD_MIN_TRADES = 5


def _landprice_case() -> str:
    return " ".join(f"WHEN land_use LIKE '%{like}%' THEN '{name}'"
                    for name, like, _key in LANDPRICE_GROUPS)


def _landprice_windows_sql(latest_year: int) -> str:
    """창마다 건수·중앙값·평균·시작연도를 뽑는 SELECT 조각.

    FILTER 로 한 번에 뽑는다. 창마다 따로 훑으면 1,180만 행을 다섯 번
    읽는다.
    """
    parts = []
    for key, _label, kind, span in LANDPRICE_WINDOWS:
        if kind == "year":
            cond = f"deal_year >= {latest_year - span + 1}"
        else:
            cond = f"rn <= {span}"
        parts.append(f"""
            count(*) FILTER (WHERE {cond}) AS n_{key},
            median(price_per_m2) FILTER (WHERE {cond}) AS p50_{key},
            avg(price_per_m2) FILTER (WHERE {cond}) AS avg_{key},
            min(deal_year) FILTER (WHERE {cond}) AS from_{key}""")
    return ",".join(parts)


def _landprice_cell(row, with_few: bool = False) -> dict:
    """한 칸의 창별 값. **비어 있는 창은 싣지 않는다.**

    거래가 없는 창에 0 이나 null 을 실으면 파일만 무거워지고, 화면은
    어차피 그리지 못한다. 없으면 없는 것이다.

    with_few 를 켜면 **다섯 건이 안 돼 버린 창의 건수**를 따로 싣는다.
    화면이 '거래가 0건이라 값이 없다' 와 '거래는 있었는데 셋뿐이라
    값으로 안 썼다' 를 구별해야 하기 때문이다(요구사항 2026-09-09
    — 거래가 없는 지자체도 이름은 보이게 한다). 둘에 똑같이 '0' 을
    적으면 세 건 있던 곳을 없던 곳이라고 말하는 것이 된다.

    시군구 칸에서만 켠다. 읍·면·동 조각은 수만 칸이라 여기에 한 칸을
    더하면 내려받는 무게가 그만큼 는다.
    """
    out = {}
    few = {}
    for key, _label, _kind, _span in LANDPRICE_WINDOWS:
        n = int(getattr(row, f"n_{key}", 0) or 0)
        p50 = getattr(row, f"p50_{key}", None)
        if n < LANDPRICE_MIN_N or p50 is None or pd.isna(p50):
            if with_few and n:
                few[key] = n
            continue
        out[key] = [n, int(round(float(p50))),
                    int(round(float(getattr(row, f"avg_{key}")))),
                    int(getattr(row, f"from_{key}"))]
    if few:
        out["few"] = few
    return out


def _latest_trade_year() -> int | None:
    with db.connect(read_only=True) as con:
        got = con.execute(f"""
            SELECT max(deal_year) FROM trade
            WHERE kind = 'land' AND {TRADE_WHERE} AND deal_year IS NOT NULL
        """).fetchone()[0]
    return int(got) if got is not None else None


def _land_price_by_region(latest_year: int) -> dict:
    """시군구 × 용도지역의 최근 실거래 ㎡당 단가.

    **중앙값과 평균을 둘 다 낸다.** 요구는 평균이었는데,
    땅값은 한쪽으로 길게 늘어진 분포라 평균이 큰 거래 몇 건에 끌려간다.
    한 시군구에 수십억짜리 한 건이 섞이면 평균이 통째로 들린다.
    그래서 화면은 중앙값을 먼저 보이고 평균을 함께 적는다 — 둘이 크게
    다르면 그 자체가 '큰 거래가 섞였다' 는 신호다.

    거래 건수도 같이 낸다. 세 건으로 만든 값과 삼백 건으로 만든 값을
    같은 색으로 칠하면 안 된다. 그리고 다섯 건이 안 되는 창은 아예
    비운다 (LANDPRICE_MIN_N 참조 — run 49 가 그 이유를 보여줬다).
    """
    with db.connect(read_only=True) as con:
        df = con.execute(f"""
            WITH t AS (
                SELECT sigungu_cd, deal_year, coalesce(deal_month, 0) AS m,
                       price_per_m2,
                       CASE {_landprice_case()} ELSE NULL END AS grp
                FROM trade
                WHERE kind = 'land' AND {TRADE_WHERE}
                  AND sigungu_cd IS NOT NULL AND deal_year IS NOT NULL
            ),
            r AS (
                SELECT *, row_number() OVER (
                    PARTITION BY sigungu_cd, grp
                    ORDER BY deal_year DESC, m DESC, price_per_m2) AS rn
                FROM t WHERE grp IS NOT NULL
            )
            SELECT sigungu_cd, grp, {_landprice_windows_sql(latest_year)}
            FROM r GROUP BY 1, 2 ORDER BY 1, 2
        """).fetchdf()
    if df.empty:
        return {}
    trend = _landprice_trend(latest_year, "sigungu_cd", "1, 2, 3")
    out: dict[str, dict] = {}
    dropped = 0
    for r in df.itertuples(index=False):
        cell = _landprice_cell(r, with_few=True)
        if cell:
            # 말풍선에 그릴 최근 추이. 없으면 안 싣는다.
            ser = trend.get((str(r.sigungu_cd), str(r.grp)))
            if ser:
                cell["s"] = ser
            out.setdefault(str(r.grp), {})[str(r.sigungu_cd)] = cell
        # 창이 하나도 안 남은 칸. 창별로 몇 개가 빠졌는지까지 세면
        # 숫자가 길어지므로 칸 단위로만 센다.
        for key, _l, _k, _s in LANDPRICE_WINDOWS:
            if getattr(r, f"n_{key}", 0) and key not in cell:
                dropped += 1
    n_cells = sum(len(v) for v in out.values())
    print(f"  행정구역 땅값 {len(out)}개 용도지역 × {n_cells:,}개 시군구칸"
          f" (거래 {LANDPRICE_MIN_N}건 미만이라 비운 창 {dropped:,}개)")
    return {
        "latest_year": latest_year,
        "windows": [{"key": k, "label": la, "kind": ki, "span": sp}
                    for k, la, ki, sp in LANDPRICE_WINDOWS],
        "default_group": DEFAULT_LANDPRICE_GROUP,
        "default_window": DEFAULT_LANDPRICE_WINDOW,
        # 대분류만 (옛 화면과의 호환).
        "zone_kinds": {name: LANDPRICE_ZONE_KIND[name]
                       for name, _like, _key in LANDPRICE_GROUPS
                       if name in out},
        # **법령 구조 그대로의 나무.** 화면은 이 순서대로 그리기만 한다 —
        # 분류를 화면에도 적어 두면 언젠가 둘이 어긋나고, 그때 어느 쪽이
        # 맞는지 아무도 모른다.
        #
        #   국토계획법 §36①   도시지역 / 관리지역 / 농림지역 / 자연환경보전지역
        #   시행령 §30①       주거·상업·공업·녹지의 세분
        #   같은 법 §38       개발제한구역은 용도구역
        "zone_tree": [
            {"major": major, "middle": middle,
             "names": [n for n in names if n in out]}
            for major, middle, names in LANDPRICE_ZONE_TREE
            if any(n in out for n in names)
        ],
        # 왜 그 칸에 있는지. '기타' 는 사유를 밝혀야 한다 (요구사항).
        "zone_notes": {n: t for n, t in LANDPRICE_ZONE_NOTE.items()
                       if n in out},
        "groups": out,
    }


def _land_price_by_umd(latest_year: int) -> dict[str, dict]:
    """읍면동 × 용도지역. **용도지역마다, 그리고 시·도마다 파일을 나눈다.**

    한 파일에 담으면 안 된다. 실측(run 48)으로 나온 숫자가 그것을 말한다.

      계획관리 13,472칸 · 3.0MB (gzip 753KB)
      농림     13,542칸 · 2.9MB (gzip 715KB)

    이 화면은 휴대폰에서 열린다. 읍면동으로 당길 때마다 750KB 를 받으면
    그 몇 초가 그대로 '느린 앱' 이 된다. 그런데 정작 화면에 글자를 90개
    까지만 놓으므로, 받은 것의 99% 는 그리지도 않는다.

    그래서 두 번 나눈다.

      1. 용도지역 — 고른 것 하나만 받는다 (5분의 1)
      2. 시·도 — 화면에 걸치는 것만 받는다 (다시 17분의 1)

    landprice.json 의 umd_index 가 조각마다 경계상자를 들고 있어서,
    화면이 무엇을 받아야 할지 스스로 안다.

    좌표는 그 읍면동 거래들의 평균이다. 법정동 경계의 중심이 아니라
    **거래가 실제로 일어난 자리의 한가운데**다 — 우리가 가진 것이
    그것이고, 이 화면에서는 오히려 그쪽이 맞다.
    """
    with db.connect(read_only=True) as con:
        df = con.execute(f"""
            WITH t AS (
                SELECT sigungu_cd, sigungu, umd,
                       deal_year, coalesce(deal_month, 0) AS m,
                       price_per_m2, lat, lon,
                       CASE {_landprice_case()} ELSE NULL END AS grp
                FROM trade
                WHERE kind = 'land' AND {TRADE_WHERE}
                  AND sigungu_cd IS NOT NULL AND deal_year IS NOT NULL
                  AND umd IS NOT NULL AND umd <> ''
            ),
            r AS (
                SELECT *, row_number() OVER (
                    PARTITION BY sigungu_cd, umd, grp
                    ORDER BY deal_year DESC, m DESC, price_per_m2) AS rn
                FROM t WHERE grp IS NOT NULL
            )
            SELECT sigungu_cd, umd, grp,
                   any_value(sigungu) AS sigungu,
                   avg(lat) AS lat, avg(lon) AS lon,
                   count(*) AS n_all,
                   {_landprice_windows_sql(latest_year)}
            FROM r GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
        """).fetchdf()
    out: dict[str, dict] = {name: {} for name, _like, _key in LANDPRICE_GROUPS}
    if df.empty:
        return out
    trend = _landprice_trend(latest_year, "sigungu_cd, umd", "1, 2, 3, 4")
    # 읍·면·동 인구 (요구사항 2026-09-09). **행정동 이름으로 잇는다** —
    # KOSIS 는 행정동이고 우리는 법정동이라 안 맞는 것이 있고, 안 맞으면
    # 비운다. 억지로 시군구 인구를 넣으면 리 하나가 20만이 된다.
    umd_pop = _umd_pop_latest()
    fill = _region_name_fill()
    thin = 0
    for r in df.itertuples(index=False):
        if int(r.n_all) < UMD_MIN_TRADES:
            thin += 1
            continue
        cell = _landprice_cell(r)
        if not cell:
            continue
        ser = trend.get((str(r.sigungu_cd), _text(r.umd), str(r.grp)))
        if ser:
            cell["s"] = ser
        code = str(r.sigungu_cd)
        chunk = out[str(r.grp)].setdefault(code[:2], {
            "group": str(r.grp), "sido_prefix": code[:2], "cells": [],
        })
        item = {
            "nm": _text(r.umd),
            "sg": code,
            "sgnm": _text(r.sigungu)
                    or str(fill.get(str(r.sigungu_cd), {}).get("name") or ""),
            "lat": round(float(r.lat), 5),
            "lon": round(float(r.lon), 5),
            "w": cell,
        }
        # **칸 자기 이름으로 맞은 것만** 칸에 붙인다. '미양면 계륵리' 는
        # 리라서 인구가 없다 — 그 자리에 미양면 인구를 넣으면 리 하나가
        # 면 전체 인구가 된다.
        pop = umd_pop.get((code, _text(r.umd)))
        if pop:
            item["pop"] = int(pop)
        chunk["cells"].append(item)
        # 면 단계에서 쓸 값은 따로 싣는다. 리를 합치는 것이 아니라
        # **면 하나의 값**이다 (리 인구를 우리는 갖고 있지 않다).
        head = _umd_head(_text(r.umd))
        hp = umd_pop.get((code, head))
        if hp:
            chunk.setdefault("head_pop", {})[f"{code}|{head}"] = int(hp)
    got = sum(len(c["cells"]) for g in out.values() for c in g.values())
    print(f"  읍면동 땅값 {got:,}칸"
          f" (거래 {UMD_MIN_TRADES}건 미만이라 뺀 칸 {thin:,}개)")
    if umd_pop:
        cells = [c for g in out.values() for ch in g.values()
                 for c in ch["cells"]]
        self_hit = sum(1 for c in cells if "pop" in c)
        heads = {f'{c["sg"]}|{_umd_head(c["nm"])}' for c in cells}
        head_hit = sum(1 for h in heads
                       if tuple(h.split("|")) in umd_pop)
        print(f"    인구: 칸 이름 그대로 맞은 것 {self_hit:,}/{len(cells):,}"
              f" ({self_hit / max(len(cells), 1):.1%})"
              f" · 면·동 이름으로 맞은 것 {head_hit:,}/{len(heads):,}"
              f" ({head_hit / max(len(heads), 1):.1%})")
    for name, _like, _key in LANDPRICE_GROUPS:
        n = sum(len(c["cells"]) for c in out[name].values())
        print(f"    {name} {n:,}칸 · 시도 {len(out[name])}조각")
    return out


# ── 행정구역이 통합돼 코드가 바뀐 시군구 ──────────────────────────
#
# run 72 실측: 읍·면 매칭률이 82.4% 였는데, **못 맞춘 것이 한 시도에
# 통째로 몰려 있었다.**
#
#     12130 여수시 · 12150 순천시 … 전남광주통합특별시  27곳 전부 0
#
# 전남과 광주가 합쳐지면서 시군구 코드가 새로 매겨졌다. 우리 실거래는
# 새 코드(12xxx)로 오는데 KOSIS 주민등록인구는 아직 옛 코드(46xxx ·
# 29xxx)다. 이름은 그대로인데 코드만 달라서 조인이 통째로 빗나간다.
#
# **대조표를 외워 적지 않는다.** 마지막 세 자리가 그대로 넘어온 것도
# 아니고(광양시 46230 → 12190), 옛 코드를 기억으로 스물일곱 줄 적으면
# 그중 몇 줄은 틀린다. 대신 **읍·면·동 이름이 몇 개나 겹치는지**로
# 찾는다. 담양군의 면 이름 열둘이 그대로 겹치는 옛 코드는 하나뿐이다.
# 다음에 또 어디가 통합돼도 고칠 것이 없다.
ALIAS_MIN_SHARED = 3        # 이름이 셋은 겹쳐야 같은 곳으로 본다
ALIAS_MIN_RATIO = 0.6       # 작은 쪽 기준 60% 이상


def _umd_pop_alias(theirs: dict[str, set[str]]) -> dict[str, str]:
    """{KOSIS 쪽 시군구코드: 우리 시군구코드}. 못 찾으면 안 넣는다.

    억지로 잇지 않는다 — 엉뚱한 시군구에 이으면 화면에 남의 동네
    인구가 '이 동네 인구' 로 뜬다. 없는 것보다 나쁘다.
    """
    try:
        with db.connect(read_only=True) as con:
            df = con.execute("""
                SELECT DISTINCT sigungu_cd, umd FROM trade
                WHERE sigungu_cd IS NOT NULL AND umd IS NOT NULL AND umd <> ''
            """).fetchdf()
    except Exception as exc:                                # noqa: BLE001
        print(f"  ⚠ 통합 시군구를 못 살폈습니다: {type(exc).__name__}: {exc}")
        return {}
    ours: dict[str, set[str]] = {}
    for r in df.itertuples(index=False):
        ours.setdefault(str(r.sigungu_cd), set()).add(_umd_head(str(r.umd)))
    # 코드가 이미 맞는 곳은 건드리지 않는다. 그리고 그 옛 코드는
    # 다른 시군구가 가져가지 못하게 잠근다.
    taken = {cd for cd in ours if cd in theirs}
    alias: dict[str, str] = {}
    for cd in sorted(ours):
        if cd in theirs:
            continue
        names = ours[cd]
        best, score = "", 0.0
        for other in sorted(theirs):
            if other in taken:
                continue
            shared = len(names & theirs[other])
            if shared < ALIAS_MIN_SHARED:
                continue
            ratio = shared / min(len(names), len(theirs[other]))
            if ratio > score:
                best, score = other, ratio
        if best and score >= ALIAS_MIN_RATIO:
            taken.add(best)
            alias[best] = cd
    if alias:
        print(f"    통합돼 코드가 바뀐 시군구 {len(alias)}곳을 이름으로 "
              f"다시 이었습니다 (예: {sorted(alias)[0]} → {alias[sorted(alias)[0]]})")
    return alias


def _umd_pop_latest() -> dict[tuple[str, str], int]:
    """(시군구코드, 읍면동이름) → 가장 최근 해 인구.

    표가 아직 없으면 빈 사전을 준다 — 인구가 없다고 땅값 화면을
    통째로 세우지 않는다.
    """
    try:
        with db.connect(read_only=True) as con:
            df = con.execute("""
                SELECT sigungu_cd, umd, sum(pop) AS pop
                FROM umd_pop
                WHERE year = (SELECT max(year) FROM umd_pop)
                GROUP BY 1, 2
            """).fetchdf()
    except Exception as exc:                                # noqa: BLE001
        print(f"  ⚠ 읍면동 인구를 못 읽었습니다: {type(exc).__name__}: {exc}")
        return {}
    pop = {(str(r.sigungu_cd), str(r.umd)): int(r.pop)
           for r in df.itertuples(index=False)}
    # 통합으로 코드가 바뀐 시군구는 **옮겨 담는다** — 옛 코드로 남겨
    # 두면 아무도 못 찾는다. 옛 칸은 지우지 않는다(다른 표가 옛 코드로
    # 물어볼 수 있다).
    theirs: dict[str, set[str]] = {}
    for cd, nm in pop:
        theirs.setdefault(cd, set()).add(nm)
    for old_cd, our_cd in _umd_pop_alias(theirs).items():
        for nm in theirs[old_cd]:
            pop.setdefault((our_cd, nm), pop[(old_cd, nm)])
    return pop


def _umd_head(name: str) -> str:
    """'미양면 계륵리' → '미양면'. 한 마디짜리는 그대로.

    **처음에 이것을 안 해서 매칭률이 2.6% 였다** (run 71 실측:
    461/17,430). 원인을 '행정동이라 법정동과 안 맞는다' 로 짚었는데
    그것은 둘째 원인이었다. 첫째는 우리 umd 칸에 **'면 + 리' 두 마디**가
    들어 있다는 것이다 —

        우리       미양면 계륵리 · 원곡면 칠곡리 · 발화동
        KOSIS      미양면 · 원곡면 · 발화동

    리 이름으로 물으니 당연히 안 맞았다. 자료를 안 보고 원인을 정하면
    이렇게 된다.
    """
    return str(name).split(" ")[0]


def _umd_bbox(cells: list[dict]) -> list[float]:
    """조각의 경계상자 [남, 서, 북, 동].

    화면이 이것을 보고 무엇을 받을지 정한다. 없으면 다 받아야 하고,
    그러면 나눈 뜻이 없다.
    """
    lats = [c["lat"] for c in cells]
    lons = [c["lon"] for c in cells]
    return [round(min(lats), 4), round(min(lons), 4),
            round(max(lats), 4), round(max(lons), 4)]


def _umd_roster() -> dict[str, dict]:
    """전국 법정동 명부를 **시·도 조각**으로. 거래가 없는 곳도 이름은 남긴다.

    요구사항(2026-09-09): "거래가 없는 동 이름이 다 안나오네요.
    모두 나오도록 해주세요."

    지금까지 읍·면·동 이름은 두 군데서만 나왔다.

      1. 땅값 조각 — 거래가 UMD_MIN_TRADES 건 넘는 칸만 실린다
      2. 검색 색인(places.json) — 거래가 세 건 넘게 있었던 곳만 있다

    둘 다 **거래에서 나온 목록**이라, 거래가 한 번도 없던 법정동은
    이름조차 없었다. 시골의 리가 통째로 여기에 해당한다.

    이 함수가 읽는 region_umd 는 행정표준코드 명부(1741000/StanReginCd)
    에서 받아 지오코더로 좌표를 붙인 표다. 거래와 무관한 **원부**다.

    ## 왜 시·도로 쪼개나

    18,700줄을 한 파일로 내면 1MB 가 넘는다. 이 화면은 휴대폰에서 열린다.
    읍면동으로 당길 때마다 그것을 받으면 그 몇 초가 그대로 '느린 앱'이
    된다. 땅값 조각과 같은 방식으로 시·도마다 나누고, 경계상자를 색인에
    실어 화면이 **보이는 조각만** 받게 한다.

    ## 시군구 코드

    명부는 표준코드다. 우리 실거래는 통합으로 코드가 바뀐 곳을 새 코드로
    준다(전남광주통합 12xxx). 코드를 외워 적지 않고 _umd_pop_alias 로
    **읍·면 이름이 겹치는지 보고** 잇는다 — 인구 표에서 쓰던 그 길이다.
    못 이으면 명부 코드 그대로 둔다. 그 경우 태그가 땅값 칸과 안 겹쳐
    이름이 두 번 뜰 수는 있어도, 남의 동네에 붙는 일은 없다.
    """
    try:
        with db.connect(read_only=True) as con:
            df = con.execute("""
                SELECT region_cd, sigungu_cd, sigungu, umd, level, lat, lon
                FROM region_umd
                WHERE lat IS NOT NULL AND lon IS NOT NULL
                ORDER BY sigungu_cd, umd
            """).fetchdf()
    except Exception as exc:                                # noqa: BLE001
        print(f"  ⚠ 법정동 명부를 못 읽었습니다: {type(exc).__name__}: {exc}")
        return {}
    if df.empty:
        print("  ⚠ 법정동 명부에 좌표가 붙은 줄이 없습니다 "
              "(umd-list 워크플로를 geocode 로 돌리세요)")
        return {}

    theirs: dict[str, set[str]] = {}
    for r in df.itertuples(index=False):
        theirs.setdefault(str(r.sigungu_cd), set()).add(_umd_head(str(r.umd)))
    alias = _umd_pop_alias(theirs)

    umd_pop = _umd_pop_latest()
    fill = _region_name_fill()
    out: dict[str, dict] = {}
    sgnm: dict[str, dict[str, str]] = {}
    for r in df.itertuples(index=False):
        code = alias.get(str(r.sigungu_cd), str(r.sigungu_cd))
        prefix = code[:2]
        chunk = out.setdefault(prefix, {"sido_prefix": prefix,
                                        "sgnm": {}, "rows": []})
        name = _text(r.umd)
        if not name:
            continue
        nm_head = _umd_head(name)
        # 인구는 **칸 이름 그대로 맞은 것만** 붙인다. '미양면 계륵리' 에
        # 미양면 인구를 넣으면 리 하나가 면 전체 인구가 된다.
        pop = umd_pop.get((code, name)) or 0
        chunk["rows"].append([
            name, code, round(float(r.lat), 5), round(float(r.lon), 5),
            int(pop), "r" if str(r.level) == "ri" else "u",
        ])
        who = sgnm.setdefault(prefix, {})
        if code not in who:
            who[code] = (_text(r.sigungu)
                         or str(fill.get(code, {}).get("name") or ""))
        # 면 단계에서 쓸 인구. 리를 합친 값이 아니라 면 하나의 값이다.
        hp = umd_pop.get((code, nm_head))
        if hp:
            chunk.setdefault("head_pop", {})[f"{code}|{nm_head}"] = int(hp)
    for prefix, chunk in out.items():
        chunk["sgnm"] = sgnm.get(prefix, {})
        lats = [row[2] for row in chunk["rows"]]
        lons = [row[3] for row in chunk["rows"]]
        chunk["bbox"] = [round(min(lats), 4), round(min(lons), 4),
                         round(max(lats), 4), round(max(lons), 4)]
    total = sum(len(c["rows"]) for c in out.values())
    with_pop = sum(1 for c in out.values() for row in c["rows"] if row[4])
    print(f"  법정동 명부 {total:,}곳 · 시도 {len(out)}조각"
          f" (인구가 붙은 곳 {with_pop:,})")
    if alias:
        print(f"    통합 시군구 {len(alias)}곳은 이름으로 우리 코드에 이었습니다")
    return out


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
            SELECT p.sigungu_cd, p.name, p.lat, p.lon, p.n_umd,
                   coalesce(o.sido, '') AS sido,
                   o.lat AS office_lat, o.lon AS office_lon
            FROM (
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
            ) p
            -- 시도 이름과 관청 좌표는 둘 다 office 에서 온다.
            -- **trade.sido 는 쓸 수 없다** — 실거래 API 응답에 시도가
            -- 없어서 늘 빈 값이다(collect/rtms.py 가 그렇게 적어 두었다).
            -- 관청 도로명주소의 첫 마디가 우리가 가진 유일한 출처다.
            LEFT JOIN office o ON o.level = 'gu' AND o.key = p.sigungu_cd
            ORDER BY p.sigungu_cd
        """).fetchdf()

    centers = {str(r.sigungu_cd): r for r in pts.itertuples(index=False)}

    # 관청을 못 찾은 시군구는 시도 이름도 비어 있다. 그대로 두면 멀리서
    # 볼 때 그 시군구가 자기 이름으로 홀로 원을 그린다 — 강화군·옹진군이
    # 인천에서 떨어져 나오는 식이다.
    #
    # 시군구 코드 앞 두 자리가 같으면 같은 시도다. 이웃이 아는 이름을
    # 빌려 온다. **추측이 아니라 우리 자료 안의 다수결**이다.
    vote: dict[str, dict[str, int]] = {}
    for code, c in centers.items():
        name = _text(getattr(c, "sido", ""))
        if name:
            vote.setdefault(code[:2], {})
            vote[code[:2]][name] = vote[code[:2]].get(name, 0) + 1
    prefix_sido = {p: max(v, key=v.get) for p, v in vote.items()}

    pop_by_code = {str(code): group for code, group in pop.groupby("sigungu_cd")}
    fill = _region_name_fill()
    used_fill: list[str] = []

    # **인구가 없다고 시군구를 통째로 빼면 안 된다.**
    #
    # 예전에는 이 고리를 인구 표에서 돌렸다. 그래서 인구가 없는 시군구는
    # regions.json 에 아예 없었고, 화면의 모든 겹(인구·땅값)이 그 시군구를
    # 조용히 잃었다. run 46 에서 실제로 드러났다 —
    #
    #   41591·41593·41595·41597 (화성시 4개 구, 2025 신설)
    #   28125·28155·28275·28290 (인천 신설 구)
    #
    # 이 여덟 코드는 실거래에는 있는데(계획관리만 120,214건) KOSIS 인구에는
    # 아직 그 코드가 없다. 그래서 땅값 지도에서 계획관리 거래의 4.5% 가
    # 소리 없이 사라져 있었다. 화성시가 통째로 없는 지도였다.
    #
    # 인구를 지어내서 메우지는 않는다. **좌표가 있으면 싣고, 인구는 비운다.**
    # 인구 겹은 그 해 값이 없는 시군구를 이미 건너뛰므로(app.js drawPopulation)
    # 빈 pop 은 안전하고, 땅값 겹은 그 시군구를 되찾는다.
    out = []
    for code in sorted(set(pop_by_code) | set(centers)):
        c = centers.get(code)
        if c is None:
            continue          # 좌표가 없으면 지도에 못 찍는다. 조용히 빼되 수는 센다.
        group = pop_by_code.get(code)
        # 이름이 안 온 코드의 빈 자리만 채운다 (config/region_names.yaml).
        got_name = _text(c.name)
        got_sido = _text(c.sido)
        spare = fill.get(str(code), {})
        if not got_name and spare.get("name"):
            got_name = str(spare["name"])
            used_fill.append(str(code))
        if not got_sido and spare.get("sido"):
            got_sido = str(spare["sido"])
        out.append({
            "sigungu_cd": str(code),
            "name": got_name or str(code),
            "lat": round(float(c.lat), 6),
            "lon": round(float(c.lon), 6),
            "n_umd": int(c.n_umd),
            # 시도 이름은 **실거래 자료에서 그대로** 가져온다. 코드
            # 앞 두 자리로 짐작하면 안 된다 — 우리 자료에는 광주광역시와
            # 전라남도가 '12' 라는 한 접두사에 함께 들어 있다
            # (12210 동구 … 12870 신안군). 코드로 갈랐으면 광주 다섯 구가
            # 전남 아래로 들어갔을 것이다.
            "sido": got_sido or prefix_sido.get(str(code)[:2], ""),
            # 관청 좌표. 있으면 원의 중심이 여기가 된다 (요구사항
            # 2026-09-07). 아직 못 받은 시군구는 빈 값이고, 그때는
            # 화면이 대표점으로 물러난다.
            **({"office_lat": round(float(c.office_lat), 6),
                "office_lon": round(float(c.office_lon), 6)}
               if pd.notna(c.office_lat) and pd.notna(c.office_lon) else {}),
            # 시 아래 구는 그 시로 묶을 수 있어야 한다 ('수원시 장안구'
            # → '수원시'). 이름이 두 마디로 오는 것이 유일한 단서다.
            "parent": _parent_si(got_name),
            "pop": ({str(int(r.year)): int(r.value)
                     for r in group.itertuples(index=False)}
                    if group is not None else {}),
        })
    if used_fill:
        print(f"    이름이 안 온 시군구 {len(used_fill)}곳을 "
              f"config/region_names.yaml 로 채웠습니다 — {', '.join(used_fill)}")
    stray = [r["sigungu_cd"] for r in out if r["name"] == r["sigungu_cd"]]
    if stray:
        # 지도에 코드가 그대로 찍힌다. 화면에 나가기 전에
        # 로그가 먼저 말해야 한다.
        print(f"    ⚠ 이름이 없어 코드가 그대로 나가는 시군구 {len(stray)}곳"
              f" — {', '.join(stray[:12])}")
        print("      (config/region_names.yaml 에 한 줄 더하면 채워집니다)")
    n_office = sum(1 for r in out if "office_lat" in r)
    n_sido = sum(1 for r in out if r["sido"])
    no_pop = [r for r in out if not r["pop"]]
    no_center = sorted(set(pop_by_code) - set(centers))
    print(f"  행정구역 {len(out)}개 시군구"
          f" (좌표가 없어 빠진 것 {len(no_center)}개)")
    print(f"    관청 좌표 {n_office}곳 · 시도 이름 {n_sido}곳")
    if no_pop:
        # 이름을 찍는다. 수만 세면 '몇 개 없구나' 로 지나가는데, 화성시가
        # 통째로 빠진 것은 이름이 보여야 알아챈다.
        names = ", ".join(f"{r['sigungu_cd']} {r['name']}" for r in no_pop[:12])
        print(f"    인구를 못 채운 시군구 {len(no_pop)}곳 — {names}"
              + (" …" if len(no_pop) > 12 else ""))
        print("      (지도에는 나오되 인구 원만 안 그려집니다. "
              "KOSIS 가 신설 코드를 아직 안 줍니다)")
    return out


# ── 검색 색인 ────────────────────────────────────────────────────────
#
# 요구사항(2026-09-09): "첫 화면이 전국인데, 정작 쓸 사람은 자기
# 지역부터 봅니다" 에 대해 "3번 진행합니다".
#
# 지도를 확대해 눈으로 찾게 하면 안 된다. 이름을 치면 그리로 가야 한다.
# 그런데 **필지 단위로는 못 간다** — 실거래 지번이 마스킹돼 있어(1**)
# 어느 필지인지 특정할 수가 없다(scripts/cadastral_probe.py 1절).
# 갈 수 있는 가장 아래가 읍·면·동이고, 거기까지를 색인으로 낸다.
#
# 좌표는 **그 이름으로 신고된 거래들의 중앙점**이다. 법정동 중심점이
# 섞여 있어 ±1~2km 어긋날 수 있지만, 화면을 그 동네로 옮기는 데는
# 충분하다. 필지를 짚는 데 쓰는 값이 아니다.
PLACE_MIN_TRADES = 3


def _places() -> list[dict]:
    """이름 → 좌표. 시·도 / 시·군·구 / 읍·면·동 세 단계.

    한 줄이 곧 검색 결과 한 칸이므로 **작게 유지한다.** 이름과 좌표와
    거래 수만 싣는다. 거래가 두 건뿐인 동네까지 넣으면 목록만 길어지고,
    눌러 봐야 지도에 아무것도 없다.
    """
    with db.connect(read_only=True) as con:
        # 인구는 **가장 최근 해**만 붙인다. 이름 옆에 (XX만) 하나를
        # 적는 데 15년치가 필요하지 않다.
        #
        # LEFT JOIN 인 이유: KOSIS 는 행정동이고 우리는 법정동이라
        # 안 맞는 이름이 있다. 안 맞으면 **비운다** — 억지로 채우면
        # 그 거짓이 화면에 '이 동네 인구' 로 뜬다.
        df = con.execute(f"""
            SELECT sigungu_cd, any_value(sigungu) AS sigungu, umd,
                   count(*) AS n,
                   median(lat) AS lat, median(lon) AS lon
            FROM trade
            WHERE lat IS NOT NULL AND lon IS NOT NULL
              AND sigungu_cd IS NOT NULL AND umd IS NOT NULL AND umd <> ''
              AND coalesce(is_cancelled, FALSE) = FALSE
            GROUP BY sigungu_cd, umd
            HAVING count(*) >= {PLACE_MIN_TRADES}
            ORDER BY sigungu_cd, umd
        """).fetchdf()
    # 인구는 **한 곳에서만** 읽는다. 전에는 이 함수가 따로 SQL 조인을
    # 했는데, 그러면 땅값 칸과 검색 목록이 서로 다른 규칙으로 인구를
    # 붙이게 된다 — 통합 시군구 보정을 한쪽만 받으면 같은 동네가 화면
    # 두 곳에서 다른 인구로 보인다.
    umd_pop = _umd_pop_latest()
    # 검색 목록의 '어느 시군구인가' 도 같은 규칙을 따른다. 지도에서는
    # 세종시라고 읽히는데 검색 결과에서는 그 칸이 비어 있으면, 같은
    # 동네가 화면 두 곳에서 다르게 보인다.
    fill = _region_name_fill()
    out = []
    hit = 0
    for r in df.itertuples(index=False):
        parent = str(r.sigungu or "") \
            or str(fill.get(str(r.sigungu_cd), {}).get("name") or "")
        row = {
            "k": "umd",
            "n": str(r.umd),
            # 어느 시군구의 '중앙동' 인지 안 적으면 같은 이름이 수십 개다.
            "p": parent,
            "sg": str(r.sigungu_cd),
            "c": int(r.n),
            "lat": round(float(r.lat), 5),
            "lon": round(float(r.lon), 5),
        }
        # **면 이름으로도 맞춰 본다.** 우리 umd 는 '미양면 계륵리'
        # 두 마디인데 KOSIS 는 '미양면' 이다 (run 71 에서 리 이름으로
        # 물어 2.6% 밖에 못 맞췄다). 검색 목록은 '이 이름을 누르면
        # 어디쯤' 을 보여 주는 자리라, 면 인구를 적어도 거짓이 아니다.
        cd, nm = str(r.sigungu_cd), str(r.umd)
        pop = umd_pop.get((cd, nm)) or umd_pop.get((cd, _umd_head(nm)))
        if pop:
            row["pop"] = int(pop)
            hit += 1
        out.append(row)
    if out:
        print(f"  읍·면·동 인구가 붙은 곳 {hit:,}/{len(out):,} "
              f"({hit / len(out):.1%}) — 나머지는 행정동↔법정동 이름이 "
              f"안 맞아 비웁니다")
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
                   (v.tollgate_id IS NULL) AS no_traffic,
                   -- 화물(2·3·4·5종) 가장 최근 해의 일평균. 화면이 필지
                   -- 진단의 교통 축을 **내보내기와 같은 식**으로 계산해야
                   -- 같은 값이 나온다 (parcelscore.build 참조).
                   coalesce(f.avg_daily, 0) AS freight
            FROM tollgate t
            LEFT JOIN (SELECT DISTINCT tollgate_id FROM traffic) v
                   ON v.tollgate_id = t.tollgate_id
            LEFT JOIN (
                SELECT tollgate_id, avg_daily FROM (
                    SELECT tollgate_id, avg_daily,
                           row_number() OVER (PARTITION BY tollgate_id
                                              ORDER BY year DESC) AS rn
                    FROM traffic
                    WHERE vehicle_type IN (2, 3, 4, 5) AND avg_daily IS NOT NULL
                ) WHERE rn = 1
            ) f ON f.tollgate_id = t.tollgate_id
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
        trades = con.execute(
            _trade_query(TRADE_WHERE, MAX_TRADE_POINTS)).fetchdf()
        # 연도별 표본. 그 해만 받으므로 한 해에 더 많이 담을 수 있다.
        # 실제 건수도 함께 센다 — 표본만 보여주면 '이 해에 거래가
        # 4천 건뿐' 으로 읽힌다.
        year_counts = con.execute(f"""
            SELECT deal_year, count(*) AS n FROM trade
            WHERE {TRADE_WHERE} GROUP BY 1 ORDER BY 1
        """).fetchdf()
        by_year = {}
        for year in year_counts["deal_year"].dropna().astype(int).tolist():
            by_year[year] = con.execute(_trade_query(
                f"{TRADE_WHERE} AND deal_year = {year}",
                MAX_TRADE_POINTS_YEAR)).fetchdf()

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

    # 토지는 용도지역과 개발단계로 가른다. 요구사항(2026-09-07):
    # "토지의 경우 용도지역을 선택하게" · "개발 완료된 물건에 더 비중".
    #
    # 표본이 아니라 **전수**를 센다. 화면이 '계획관리 576건' 이라고
    # 말하면 그것이 표본 수인지 실제 수인지 읽는 사람은 알 수 없다.
    from .usage import land_stage as _stage_of
    with db.connect(read_only=True) as con:
        _lrows = con.execute(f"""
            SELECT coalesce(land_use, '') AS land_use,
                   coalesce(jimok, '') AS jimok, count(*) AS n
            FROM trade WHERE kind = 'land' AND {TRADE_WHERE}
            GROUP BY 1, 2
        """).fetchdf()
    land_use_mix: dict[str, int] = {}
    stage_mix: dict[str, int] = {}
    for _r in _lrows.itertuples(index=False):
        _u = _r.land_use.strip() or "용도 미상"
        land_use_mix[_u] = land_use_mix.get(_u, 0) + int(_r.n)
        _s = _stage_of(_r.jimok) or "지목 미상"
        stage_mix[_s] = stage_mix.get(_s, 0) + int(_r.n)

    # 도로 접함. 요구사항(2026-09-07): "도로를 접하는 가가 제일
    # 중요합니다." 실측이 크기까지 알려줬다 — 차가 들어가느냐가 단가를
    # 남이천 +66%, 안성 +67% 가른다.
    #
    # **'조사 안 됨' 을 반드시 함께 센다.** 필지 특성은 전국을 칸으로
    # 나눠 조금씩 모으는 중이라 아직 대부분의 거래에 안 붙어 있다.
    # 그 숫자를 감추면 화면이 '맹지가 적다' 로 읽히는데, 사실은
    # '아직 모른다' 다.
    from .usage import road_car_ok as _car_of
    with db.connect(read_only=True) as con:
        _rrows = con.execute(f"""
            SELECT coalesce(pc.road_side, '') AS road_side, count(*) AS n
            FROM trade t
            LEFT JOIN trade_parcel tp ON tp.trade_id = t.trade_id
            LEFT JOIN parcel pc ON pc.pnu = tp.pnu
            WHERE t.kind = 'land' AND {_trade_where('t')}
            GROUP BY 1
        """).fetchdf()
    road_mix: dict[str, int] = {ROAD_OK: 0, ROAD_NO: 0, ROAD_UNKNOWN: 0}
    road_side_mix: dict[str, int] = {}
    for _r in _rrows.itertuples(index=False):
        _n = int(_r.n)
        _c = _car_of(_r.road_side)
        road_mix[ROAD_UNKNOWN if _c is None
                 else ROAD_OK if _c else ROAD_NO] += _n
        if _r.road_side:
            road_side_mix[_r.road_side] = \
                road_side_mix.get(_r.road_side, 0) + _n

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
        # 토지 쪽. land_use_mix 는 용도지역별, stage_mix 는 개발단계별
        # 전체 건수다.
        "land_use_mix": land_use_mix,
        # **분석이 쓰는 세 용도지역.** IC 반경 가격 추이는 이 셋만 모은
        # 값인데, 지도의 땅값 글자는 켜 놓은 용도지역을 따른다.
        # 같은 화면에 기준이 다른 두 값이 있으므로 화면이 그것을 밝혀야
        # 한다 (요구사항 2026-09-09). 설정에서 읽어 내보내므로
        # settings.yaml 을 고치면 화면 문구도 따라간다 — 손으로 적어 두면
        # 조용히 어긋난다.
        "land_use_filter": list(settings().get("land_use_filter") or []),
        "stage_mix": stage_mix,
        # 도로 접함. road_mix 는 필터가 쓰는 세 칸,
        # road_side_mix 는 원래 등급별 건수(말풍선·설명용)다.
        "road_mix": road_mix,
        "road_side_mix": road_side_mix,
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
    # 묶은 단위의 관청. 화면이 축척에 따라 시도·시군으로 묶을 때
    # 원의 중심으로 쓴다. 경기도를 볼 때 원이 경기도청에 있어야지
    # 43개 시군구 관청의 평균에 있으면 그것은 다시 대표점이다.
    meta["region_offices"] = _region_offices()
    meta["counts"]["offices"] = sum(
        len(v) for v in meta["region_offices"].values())
    if regions:
        years = sorted({int(y) for r in regions for y in r["pop"]})
        meta["population_years"] = years

    _write("meta.json", meta)
    _write("regions.json", regions)

    # 땅값 겹은 regions.json 의 좌표를 타고 그려진다. 거기 없는 시군구는
    # **화면에서 조용히 사라진다** — 오류도 빈 칸도 안 남기고 그냥 없다.
    # 그래서 여기서 센다. run 46 에서 여덟 코드(화성시 4개 구, 인천 신설
    # 구 4곳)가 그렇게 빠져 계획관리 거래의 4.5% 를 잃고 있었다.
    latest_year = _latest_trade_year()
    landprice = _land_price_by_region(latest_year) if latest_year else {}
    known = {r["sigungu_cd"] for r in regions}
    orphan: dict[str, int] = {}
    for cells in landprice.get("groups", {}).values():
        for cd, cell in cells.items():
            if cd not in known:
                # 창마다 건수가 다르므로 가장 넓은 창의 건수로 센다.
                orphan[cd] = max(orphan.get(cd, 0),
                                 max((w[0] for w in cell.values()), default=0))
    if orphan:
        top = ", ".join(f"{cd} {n:,}건" for cd, n
                        in sorted(orphan.items(), key=lambda kv: -kv[1])[:8])
        print(f"  ⚠ 좌표가 없어 땅값 지도에서 빠지는 시군구 {len(orphan)}곳"
              f" · 거래 {sum(orphan.values()):,}건 — {top}")

    # 읍면동은 용도지역 × 시도로 쪼개서 낸다. 화면은 고른 용도지역 중
    # **보이는 시도 조각만** 받는다. 경계상자를 색인에 실어 그것을
    # 화면이 스스로 판단하게 한다.
    if landprice:
        key_of = {name: key for name, _like, key in LANDPRICE_GROUPS}
        keep = set()
        index: dict[str, list] = {}
        for name, chunks in _land_price_by_umd(latest_year).items():
            rows = []
            total = 0
            for prefix, chunk in sorted(chunks.items()):
                fname = f"landprice-umd-{key_of[name]}-{prefix}.json"
                chunk["bbox"] = _umd_bbox(chunk["cells"])
                _write(fname, chunk)
                keep.add(fname)
                total += (WEB_DATA / fname).stat().st_size
                rows.append({"p": prefix, "f": fname,
                             "bbox": chunk["bbox"], "n": len(chunk["cells"])})
            if rows:
                index[name] = rows
                big = max(rows, key=lambda r: r["n"])
                size = (WEB_DATA / big["f"]).stat().st_size
                print(f"    {name}: {len(rows)}조각 · 합 {total / 1024:,.0f}KB"
                      f" · 가장 큰 조각 {big['p']} {big['n']:,}칸"
                      f" {size / 1024:,.0f}KB")
        landprice["umd_index"] = index
        # 이번에 안 낸 읍면동 파일은 지운다 (예전 통짜 파일 포함).
        # 저장소에 낡은 자료가 새것인 얼굴로 남는 것이 이 프로젝트에서
        # 이미 한 번 사고를 냈다.
        for stale in WEB_DATA.glob("landprice-umd-*.json"):
            if stale.name not in keep:
                stale.unlink()
                print(f"  낡은 읍면동 파일 삭제: {stale.name}")
    # 거래가 없는 법정동도 이름은 남긴다. 땅값 조각과 똑같이 시·도로
    # 쪼개고 경계상자를 색인에 실어, 화면이 보이는 조각만 받게 한다.
    roster = _umd_roster()
    if roster:
        keep = set()
        rows = []
        total = 0
        for prefix, chunk in sorted(roster.items()):
            fname = f"umd-roster-{prefix}.json"
            _write(fname, chunk)
            keep.add(fname)
            total += (WEB_DATA / fname).stat().st_size
            rows.append({"p": prefix, "f": fname,
                         "bbox": chunk["bbox"], "n": len(chunk["rows"])})
        landprice["umd_roster"] = rows
        big = max(rows, key=lambda r: r["n"])
        print(f"    명부 {len(rows)}조각 · 합 {total / 1024:,.0f}KB"
              f" · 가장 큰 조각 {big['p']} {big['n']:,}곳")
        for stale in WEB_DATA.glob("umd-roster-*.json"):
            if stale.name not in keep:
                stale.unlink()
                print(f"  낡은 명부 조각 삭제: {stale.name}")
    _write("landprice.json", landprice)

    # 표준지공시지가 — '현재 가치' 2판의 첫 마디. std_land 가 있을 때만
    # 시군구별로 낸다. 화면은 필지의 시군구 조각 하나만 받는다.
    try:
        _stdland_files()
    except Exception as exc:                       # noqa: BLE001
        print(f"  ⚠ 표준지 조각을 못 만들었습니다: {exc}")

    # 필지 진단(레이더)의 또래 분포. 요구사항(2026-09-08):
    # "해당 필지를 클릭하면 스파이더 차트를 통해 여러가지 인자들을 분석".
    #
    # **점수를 만들지 않는다** — 비교 대상의 분포만 만든다. 땅에 0~100 점
    # 하나를 매기면 가짜 정밀도가 된다. 같은 필지가 물류창고에는 A급이고
    # 전원주택에는 C급인데, 하나의 숫자로 뭉개면 그 사실이 사라진다.
    try:
        from .parcelscore import build as _peer_build
        from .analyze import urban as _urban
        # 여섯째 축은 검증(urban-check)이 채택했을 때만 실린다.
        with db.connect(read_only=True) as _con:
            _u = _urban.for_web(_con) if _urban.adopted() else None
        if _u is None:
            print("  주변 이용 축: urban_check.json 이 '채택' 이 아니라 싣지 않습니다")
        _write("parcelstats.json",
               _peer_build([(name, like) for name, like, _k in LANDPRICE_GROUPS],
                           urban=_u))
    except Exception as exc:                       # noqa: BLE001
        # 조인 표가 없는 실행(캐시가 비었을 때)에서도 나머지는 나가야 한다.
        print(f"  ⚠ 필지 진단 또래 분포를 못 만들었습니다: {exc}")
    # 검색 색인. 실패해도 나머지 화면은 살린다 — 검색이 없는 것과
    # 화면이 죽는 것은 사용자에게 전혀 다른 일이다.
    try:
        places = _places()
        _write("places.json", {"places": places})
        print(f"  검색 색인 {len(places):,}곳 (읍·면·동)")
    except Exception as exc:                                # noqa: BLE001
        print(f"  ⚠ 검색 색인을 못 만들었습니다: {type(exc).__name__}: {exc}")

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
