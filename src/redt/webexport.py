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
from .config import PROCESSED, ROOT, settings

WEB_DATA = ROOT / "web" / "data"
SYNTHETIC_MARK = PROCESSED / ".synthetic"
MAX_TRADE_POINTS = 8000

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


def export(band: str = "0-3", volume_col: str = "volume_freight") -> dict:
    panel_path = PROCESSED / "panel.parquet"
    if not panel_path.exists():
        raise FileNotFoundError("panel.parquet 이 없습니다. `panel` 을 먼저 실행하세요.")
    panel = pd.read_parquet(panel_path)

    with db.connect(read_only=True) as con:
        tollgates = con.execute(
            "SELECT tollgate_id, name, route_no, lat, lon, sido, sigungu "
            "FROM tollgate WHERE lat IS NOT NULL").fetchdf()
        trade_total = con.execute("SELECT count(*) FROM trade").fetchone()[0]
        trades = con.execute(f"""
            SELECT trade_id, kind, lat, lon, deal_year, price_per_m2, area_m2,
                   coalesce(jimok, '') AS jimok, coalesce(geocode_level, '') AS geocode_level
            FROM trade
            WHERE lat IS NOT NULL AND price_per_m2 IS NOT NULL
              AND NOT coalesce(is_cancelled, FALSE)
            USING SAMPLE {MAX_TRADE_POINTS} ROWS
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
    _write("tollgates.json", _records(merged))
    _write("trades.json", _records(trades))
    _write("series.json", grouped)
    return meta
