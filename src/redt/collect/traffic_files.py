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

import calendar
from pathlib import Path

import pandas as pd

from ..config import RAW
from ..ids import canon_series

SOURCE = "tcs"


def observed_days() -> pd.DataFrame:
    """영업소×연도별로 실제 관측된 날 수.

    패널은 연 합계가 아니라 **일평균**을 쓴다. 관측일수가 해마다 다르면
    교통량이 아니라 집계 범위가 변한 것을 β 로 잡아내기 때문이다. 그래서
    월별 파일에서 그 해에 실제로 자료가 있는 달을 세어 날 수로 환산한다.

    연중 개통한 영업소는 그 해 관측 달이 적으므로 여기서 자동으로 걸러진다
    — 12월 한 달만 있는 영업소를 365일로 나누면 교통량이 1/12 로 보인다.
    """
    rows = []
    for path in sorted(Path(RAW).glob("tcs_monthly_*.csv")):
        df = pd.read_csv(path, encoding="utf-8-sig", usecols=["영업소코드", "연월"])
        df = df.drop_duplicates()
        df["year"] = df["연월"].astype(str).str[:4].astype(int)
        df["month"] = df["연월"].astype(str).str[-2:].astype(int)
        df["days"] = [calendar.monthrange(y, m)[1]
                      for y, m in zip(df["year"], df["month"])]
        rows.append(df)
    if not rows:
        return pd.DataFrame(columns=["tollgate_id", "year", "days"])
    all_rows = pd.concat(rows, ignore_index=True)
    all_rows["tollgate_id"] = canon_series(all_rows["영업소코드"])
    return (all_rows.groupby(["tollgate_id", "year"], as_index=False)["days"].sum())


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

    # 일평균을 채운다. 이 칸이 비어 있으면 패널이 교통량을 0 으로 읽는다 —
    # 실제로 그렇게 되어 β 가 통째로 안 나온 적이 있다.
    days = observed_days()
    if days.empty:
        print("  ⚠ 월별 파일이 없어 일평균을 낼 수 없습니다. 365일로 나눕니다 "
              "— 연중 개통한 영업소가 과소평가됩니다.")
        out["avg_daily"] = out["volume"] / 365.0
    else:
        out = out.merge(days, on=["tollgate_id", "year"], how="left")
        missing = out["days"].isna().sum()
        if missing:
            print(f"  ⚠ 관측일수를 못 찾은 {missing:,}행 → 365일로 나눕니다")
        out["avg_daily"] = out["volume"] / out["days"].fillna(365.0)
        short = days[days["days"] < 350]
        if len(short):
            print(f"  관측일수가 350일 미만인 영업소×연도 {len(short)}건 "
                  "(연중 개통·폐쇄로 보이며, 일평균으로 보정됩니다)")
        out = out.drop(columns=["days"])
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
