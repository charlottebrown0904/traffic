"""합성 데이터로 파이프라인 전체를 검증한다.

'진짜 β'를 심어놓고 추정기가 그것을 되찾아오는지 본다.
되찾지 못하면 실제 데이터에서 나온 결과도 믿을 수 없다.
API 키 없이 Step 2~3 로직을 점검하는 용도.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redt import db  # noqa: E402
from redt.config import PROCESSED  # noqa: E402

RNG = np.random.default_rng(20260827)

TRUE_BETA = {"0-3": 0.50, "3-5": 0.30, "5-10": 0.10, "10-20": 0.00}
BAND_RANGE = {"0-3": (0.3, 3), "3-5": (3, 5), "5-10": (5, 10), "10-20": (10, 20)}
YEARS = list(range(2015, 2025))
KINDS = ["land", "factory"]
LAND_USES = ["전", "답", "대", "임야", "공장용지"]


def make_tollgates(n_rows=6, n_cols=10) -> pd.DataFrame:
    """0.6도(~60km) 격자에 배치 — 최근접 영업소가 항상 의도한 영업소가 되도록."""
    rows = []
    for i in range(n_rows):
        for j in range(n_cols):
            idx = i * n_cols + j
            rows.append({
                "tollgate_id": f"TG{idx:03d}",
                "name": f"합성{idx:03d}영업소",
                "route_no": f"{(idx % 9) + 1}0",
                "lat": 34.5 + i * 0.6,
                "lon": 126.5 + j * 0.45,
                "sido": f"시도{idx % 8}",
                "sigungu": f"시군구{idx % 20}",
                "sigungu_cd": f"{41000 + (idx % 20):05d}",
                "is_open_type": bool(idx % 3 == 0),
            })
    return pd.DataFrame(rows)


def make_traffic(tollgates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """차종별 교통량. ln(교통량)은 영업소별 랜덤워크로 움직인다."""
    records, truth = [], []
    for tg in tollgates.itertuples():
        base = RNG.uniform(np.log(2e6), np.log(4e7))
        drift = RNG.normal(0.03, 0.03)
        ln_t = base
        for year in YEARS:
            ln_t += drift + RNG.normal(0, 0.06)
            truth.append({"tollgate_id": tg.tollgate_id, "year": year, "ln_traffic": ln_t})
            total = np.exp(ln_t)
            # 1종 60%, 2종 12%, 3~5종 28% (화물)
            for vtype, share in [(1, 0.60), (2, 0.12), (3, 0.16), (4, 0.08), (5, 0.04)]:
                records.append({
                    "tollgate_id": tg.tollgate_id,
                    "year": year,
                    "vehicle_type": vtype,
                    "direction": "all",
                    "volume": int(total * share),
                    "avg_daily": total * share / 365,
                    "source": "tcs",
                    "unit_type": "tollgate",
                    "match_km": 0.0,
                })
    return pd.DataFrame(records), pd.DataFrame(truth)


def offset_coord(lat, lon, km, bearing_rad):
    dlat = (km / 111.32) * np.cos(bearing_rad)
    dlon = (km / (111.32 * np.cos(np.radians(lat)))) * np.sin(bearing_rad)
    return lat + dlat, lon + dlon


def make_trades(tollgates: pd.DataFrame, truth: pd.DataFrame,
                per_cell: int = 12) -> pd.DataFrame:
    ln_traffic = {(r.tollgate_id, r.year): r.ln_traffic for r in truth.itertuples()}
    rows = []
    for tg in tollgates.itertuples():
        tg_effect = RNG.normal(0, 0.5)          # 영업소 고정효과
        for kind in KINDS:
            for band, beta in TRUE_BETA.items():
                lo, hi = BAND_RANGE[band]
                for year in YEARS:
                    prev = ln_traffic.get((tg.tollgate_id, year - 1))
                    if prev is None:
                        continue
                    year_effect = 0.04 * (year - YEARS[0])   # 전국 사이클
                    cell_price = tg_effect + year_effect + beta * prev + RNG.normal(0, 0.02)
                    for k in range(per_cell):
                        km = RNG.uniform(lo, hi)
                        lat, lon = offset_coord(tg.lat, tg.lon, km, RNG.uniform(0, 2 * np.pi))
                        area = float(np.exp(RNG.uniform(np.log(200), np.log(20000))))
                        land_use = LAND_USES[RNG.integers(0, len(LAND_USES))]
                        # 헤도닉이 걷어내야 할 물건 특성 효과
                        char = -0.25 * np.log(area) + 0.3 * LAND_USES.index(land_use)
                        ln_pm2 = cell_price + char + RNG.normal(0, 0.25)
                        pm2 = float(np.exp(ln_pm2))
                        key = f"{tg.tollgate_id}|{kind}|{band}|{year}|{k}"
                        rows.append({
                            "trade_id": hashlib.sha1(key.encode()).hexdigest(),
                            "kind": kind,
                            "sigungu_cd": tg.sigungu_cd,
                            "sido": tg.sido,
                            "sigungu": tg.sigungu,
                            "umd": f"합성리{k % 7}",
                            "jibun": f"{RNG.integers(1, 900)}-{RNG.integers(1, 20)}",
                            "deal_year": year,
                            "deal_month": int(RNG.integers(1, 13)),
                            "area_m2": area,
                            "price_krw": int(pm2 * area),
                            "price_per_m2": pm2,
                            "jimok": land_use,
                            "land_use": ["계획관리", "생산녹지", "공업"][k % 3],
                            "building_area_m2": None,
                            "building_use": "",
                            "build_year": None,
                            "is_share_deal": False,
                            "is_cancelled": bool(k == 0 and year % 4 == 0),
                            "deal_type": "중개거래" if k % 5 else "직거래",
                            "lat": lat,
                            "lon": lon,
                            "geocode_level": "parcel" if k % 6 else "umd",
                        })
    return pd.DataFrame(rows)


def main():
    print("합성 데이터 생성 중...")
    tollgates = make_tollgates()
    traffic, truth = make_traffic(tollgates)
    trades = make_trades(tollgates, truth)
    print(f"  영업소 {len(tollgates)} / 교통량 {len(traffic):,}행 / 거래 {len(trades):,}건")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    target = PROCESSED / "redt.duckdb"
    if target.exists():
        target.unlink()

    with db.connect() as con:
        db.upsert(con, "tollgate", tollgates)
        db.upsert(con, "traffic", traffic)
        db.upsert(con, "trade", trades)
    print(f"  → {target}")
    print("\n심어놓은 진짜 β:", TRUE_BETA)


if __name__ == "__main__":
    main()
