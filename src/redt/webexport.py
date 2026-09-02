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
# 배포 저장소에 커밋되는 파일이라 지도 표시용 표본은 작게 유지한다
MAX_TRADE_POINTS = 2500
SAMPLE_SEED = 42          # 표본을 고정해 실행마다 diff 가 생기지 않게 한다

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


def _write(name: str, payload) -> Path:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    path = WEB_DATA / name
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
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
            "sido": meta_row.get("sido") or "",
            "sigungu": meta_row.get("sigungu") or "",
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


def export(band: str | None = None, volume_col: str = "volume_freight") -> dict:
    band = band or primary_band()
    panel_path = PROCESSED / "panel.parquet"
    if not panel_path.exists():
        raise FileNotFoundError("panel.parquet 이 없습니다. `panel` 을 먼저 실행하세요.")
    panel = pd.read_parquet(panel_path)

    with db.connect(read_only=True) as con:
        # ORDER BY 가 없으면 DuckDB 가 매번 다른 순서로 돌려주어, 내용이 같아도
        # 커밋 diff 가 생긴다. 이 파일들은 배포에 함께 커밋되므로 순서를 고정한다.
        tollgates = con.execute(
            "SELECT tollgate_id, name, route_no, lat, lon, sido, sigungu "
            "FROM tollgate WHERE lat IS NOT NULL ORDER BY tollgate_id").fetchdf()
        trade_total = con.execute("SELECT count(*) FROM trade").fetchone()[0]
        # REPEATABLE 로 표본을 고정한다. 없으면 실행할 때마다 다른 거래가 뽑혀
        # 500KB 파일 전체가 바뀐 것처럼 보인다.
        trades = con.execute(f"""
            SELECT * FROM (
                SELECT trade_id, kind, lat, lon, deal_year, price_per_m2, area_m2,
                       coalesce(jimok, '') AS jimok,
                       coalesce(geocode_level, '') AS geocode_level
                FROM trade
                WHERE lat IS NOT NULL AND price_per_m2 IS NOT NULL
                  AND NOT coalesce(is_cancelled, FALSE)
                USING SAMPLE reservoir({MAX_TRADE_POINTS} ROWS) REPEATABLE ({SAMPLE_SEED})
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
        },
        "bands_km": settings()["spatial"]["bands"],
        "disclaimer": DISCLAIMER,
    }

    _write("meta.json", meta)
    _write("traffic.json", _traffic_ranking())
    _write("chart.json", _chart_series())
    _write("tollgates.json", _records(merged))
    _write("trades.json", _records(trades))
    _write("series.json", grouped)
    return meta
