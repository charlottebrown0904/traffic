"""포털에서 받아 정리해둔 연간 교통량 CSV 를 DB 에 싣는다.

실시간 API 는 과거 연도를 주지 않는다(docs/traffic-api-findings.md). 그래서
포털의 일별 원본을 받아 scripts/convert_tcs_daily.py 로 접어두었는데, 그것을
traffic 테이블에 넣는 단계가 없어서 패널이 비어 있었다. 수집은 다 됐는데
'패널을 만들 재료가 부족합니다' 만 나왔다.

영업소 코드는 양쪽 표기가 달라 redt.ids 로 접어서 맞춘다. 맞춘 뒤에도
영업소 마스터와 짝이 안 맞는 비율이 높으면 크게 알린다 — 조인이 어긋난 채
분석까지 흘러가면 '표본이 없는 것' 과 구분할 수 없다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..config import RAW
from ..ids import canon_series

SOURCE = "tcs"


def load_files(pattern: str = "tcs_annual_*.csv") -> pd.DataFrame:
    """data/raw 의 연간 CSV 를 모아 traffic 테이블 모양으로 만든다."""
    frames = []
    for path in sorted(Path(RAW).glob(pattern)):
        if path.name.startswith("legacy_"):
            continue                       # 출처가 다른 파일 (PROVENANCE.md)
        df = pd.read_csv(path, encoding="utf-8-sig")
        need = {"영업소코드", "연도", "차종", "교통량"}
        missing = need - set(df.columns)
        if missing:
            print(f"  ⚠ {path.name}: 컬럼 없음 {sorted(missing)} — 건너뜁니다")
            continue
        frames.append(df)
        print(f"  {path.name}  {len(df):,}행")

    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "tollgate_id": canon_series(raw["영업소코드"]),
        "year": pd.to_numeric(raw["연도"], errors="coerce"),
        # '1종' → 1. 숫자를 못 읽으면 버린다 — 0(전체)으로 두면 차종별 합계와
        # 겹쳐 교통량이 두 배가 된다.
        "vehicle_type": pd.to_numeric(
            raw["차종"].astype(str).str.extract(r"(\d+)")[0], errors="coerce"),
        "direction": "all",
        "volume": pd.to_numeric(raw["교통량"], errors="coerce"),
        "avg_daily": None,
        "source": SOURCE,
        "unit_type": "tollgate",
        "match_km": 0.0,
    })

    before = len(out)
    out = out.dropna(subset=["tollgate_id", "year", "vehicle_type", "volume"])
    if len(out) < before:
        print(f"  ⚠ 값을 읽지 못한 {before - len(out):,}행 제외")
    out["year"] = out["year"].astype(int)
    out["vehicle_type"] = out["vehicle_type"].astype(int)
    out["volume"] = out["volume"].astype("int64")
    return out


def report_match(traffic: pd.DataFrame, tollgate_ids: set[str]) -> float:
    """영업소 마스터와 얼마나 짝이 맞는지. 낮으면 조인이 어긋난 것이다."""
    codes = set(traffic["tollgate_id"].unique())
    if not codes:
        return 0.0
    matched = codes & tollgate_ids
    rate = len(matched) / len(codes)
    print(f"  영업소 짝맞춤 {len(matched)}/{len(codes)} ({rate:.0%})")
    if rate < 0.5:
        missing = sorted(codes - tollgate_ids)[:10]
        print(f"  ⚠ 절반도 못 맞췄습니다. 마스터에 없는 코드 예: {missing}")
        print("    영업소 마스터가 일부만 받아졌거나(P2-6a) 코드 표기가 다릅니다."
              " 이대로 두면 패널이 조용히 비거나 표본이 크게 줄어듭니다.")
    return rate
