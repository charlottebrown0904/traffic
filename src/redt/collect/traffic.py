"""교통량 파일 → traffic 테이블 정규화.

과거 시계열이 여러 포털에 흩어져 있고 형식이 제각각(일별/분기별/연별,
long/wide, 영업소기준/본선지점기준)이라 하나의 유연한 로더로 흡수한다.

사용 순서
  1) `inspect(path)` 로 컬럼을 본다
  2) 자동 추정이 틀리면 `mapping=` 으로 지정한다
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import RAW, settings

COLUMN_HINTS = {
    "tollgate_id": ["unitCode", "tcsUnitCode", "영업소코드", "tollgate_id", "icCode",
                    "지점번호", "지점코드", "pointCode"],
    "name": ["unitName", "영업소명", "tollgate_name", "name", "지점명", "조사지점명"],
    "year": ["year", "년도", "연도", "aggYear", "집계연도", "조사연도"],
    "date": ["sumDate", "집계일자", "date", "ymd", "aggDate", "stdDt", "기준일자"],
    "quarter": ["quarter", "분기", "qtr"],
    "vehicle_type": ["carType", "차종", "vehicle_type", "tcsCarKnd", "tcsCarTypeCd"],
    "direction": ["direction", "방향", "ioType", "입출구구분", "구분"],
    "volume": ["trafficAmout", "trafficAmount", "교통량", "volume", "tcsVol",
               "합계", "계", "통행량", "aadt", "AADT", "연평균일교통량", "일평균교통량"],
    "lat": ["lat", "latitude", "위도", "yValue", "y"],
    "lon": ["lon", "lng", "longitude", "경도", "xValue", "x"],
}

# 값이 '연간 누적'인지 '일평균'인지 컬럼명으로 판별
DAILY_HINTS = ("aadt", "연평균", "일평균", "일교통량", "avg", "평균")


def read_any(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt"):
        for encoding in ("utf-8", "cp949", "euc-kr"):
            try:
                return pd.read_csv(path, dtype=str, encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"인코딩을 판별하지 못했습니다: {path}")
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in (".json", ".jsonl"):
        text = path.read_text(encoding="utf-8")
        if suffix == ".jsonl":
            return pd.DataFrame([json.loads(l) for l in text.splitlines() if l.strip()])
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = next((v for v in payload.values() if isinstance(v, list)), [])
        return pd.DataFrame(payload)
    raise ValueError(f"지원하지 않는 파일 형식: {suffix}")


def inspect(path: str | Path) -> pd.DataFrame:
    df = read_any(path)
    print(f"행 {len(df):,} / 열 {len(df.columns)}")
    print("컬럼:", list(df.columns))
    years = _year_columns(df)
    if years:
        print(f"→ wide 형식으로 보입니다. 연도 컬럼 {len(years)}개: {years[:12]}"
              f"{' ...' if len(years) > 12 else ''}")
    print(df.head(5).to_string())
    return df


def _year_columns(df: pd.DataFrame) -> list[str]:
    """'2015', '2015년', 'y2015' 처럼 연도로 보이는 컬럼을 찾는다 (wide 형식 감지)."""
    found = []
    for col in df.columns:
        match = re.fullmatch(r"[a-zA-Z_]?(19|20)\d{2}(년|년도)?", str(col).strip())
        if match:
            found.append(str(col))
    return found


def _resolve(columns, hints: list[str]) -> str | None:
    lowered = {str(c).strip().lower(): c for c in columns}
    for hint in hints:
        if hint.lower() in lowered:
            return lowered[hint.lower()]
    # 부분 일치 (예: '교통량(대/일)')
    for hint in hints:
        for low, original in lowered.items():
            if hint.lower() in low:
                return original
    return None


def _melt_wide(df: pd.DataFrame, year_cols: list[str]) -> pd.DataFrame:
    """연도가 컬럼으로 펼쳐진 형식을 long 으로 접는다."""
    id_cols = [c for c in df.columns if c not in year_cols]
    long = df.melt(id_vars=id_cols, value_vars=year_cols,
                   var_name="_year_raw", value_name="_value")
    long["year"] = pd.to_numeric(
        long["_year_raw"].astype(str).str.extract(r"((?:19|20)\d{2})")[0], errors="coerce"
    )
    long["volume"] = pd.to_numeric(
        long["_value"].astype(str).str.replace(r"[,\s]", "", regex=True), errors="coerce"
    )
    return long.drop(columns=["_year_raw", "_value"])


def normalize(df: pd.DataFrame, mapping: dict | None = None, source: str = "unknown",
              unit_type: str = "tollgate", value_is_daily: bool | None = None
              ) -> pd.DataFrame:
    """원본 → traffic 스키마 (영업소 × 연도 × 차종)."""
    mapping = mapping or {}
    year_cols = _year_columns(df)
    wide = bool(year_cols) and not mapping.get("year")
    if wide:
        print(f"  wide 형식 감지 — 연도 컬럼 {len(year_cols)}개를 long 으로 변환")
        df = _melt_wide(df, year_cols)

    resolved = {
        field: mapping.get(field) or _resolve(df.columns, hints)
        for field, hints in COLUMN_HINTS.items()
    }
    if wide:
        resolved["year"], resolved["volume"] = "year", "volume"

    if not resolved["tollgate_id"] and not resolved["name"]:
        raise ValueError(
            f"영업소/지점 식별 컬럼을 찾지 못했습니다.\n실제 컬럼: {list(df.columns)}\n"
            f"mapping={{'tollgate_id': '<컬럼명>'}} 으로 지정하세요."
        )
    if not resolved["volume"]:
        raise ValueError(
            f"교통량 값 컬럼을 찾지 못했습니다.\n실제 컬럼: {list(df.columns)}\n"
            f"mapping={{'volume': '<컬럼명>'}} 으로 지정하세요."
        )

    key_col = resolved["tollgate_id"] or resolved["name"]
    out = pd.DataFrame({
        "tollgate_id": df[key_col].astype(str).str.strip(),
        "volume_raw": pd.to_numeric(
            df[resolved["volume"]].astype(str).str.replace(r"[,\s]", "", regex=True),
            errors="coerce"),
    })

    # ---- 연도 만들기 -------------------------------------------------
    if resolved["year"]:
        out["year"] = pd.to_numeric(
            df[resolved["year"]].astype(str).str.extract(r"((?:19|20)\d{2})")[0],
            errors="coerce")
        granularity = "year"
    elif resolved["date"]:
        out["year"] = pd.to_numeric(
            df[resolved["date"]].astype(str).str.extract(r"((?:19|20)\d{2})")[0],
            errors="coerce")
        out["_date"] = df[resolved["date"]].astype(str)
        granularity = "date"
    else:
        raise ValueError("연도를 만들 컬럼(year 또는 date)이 없습니다.")

    out["vehicle_type"] = (
        pd.to_numeric(df[resolved["vehicle_type"]], errors="coerce").fillna(0).astype(int)
        if resolved["vehicle_type"] else 0
    )
    out["direction"] = (
        df[resolved["direction"]].astype(str).str.strip().str.lower()
        .replace({"입구": "in", "출구": "out", "1": "in", "2": "out", "nan": "all"})
        if resolved["direction"] else "all"
    )
    for col in ("lat", "lon"):
        out[col] = (pd.to_numeric(df[resolved[col]], errors="coerce")
                    if resolved[col] else np.nan)

    out = out.dropna(subset=["year", "volume_raw"])
    out["year"] = out["year"].astype(int)
    period = settings()["period"]
    before = len(out)
    out = out[out["year"].between(period["start_year"], period["end_year"])]
    if len(out) < before:
        print(f"  기간({period['start_year']}~{period['end_year']}) 밖 {before - len(out):,}행 제외")

    # ---- 값의 성격: 연간 누적인가 일평균인가 --------------------------
    if value_is_daily is None:
        col_name = str(resolved["volume"]).lower()
        value_is_daily = any(h in col_name for h in DAILY_HINTS)
        if value_is_daily:
            print(f"  '{resolved['volume']}' → 일평균 값으로 해석합니다 "
                  f"(다르면 value_is_daily=False 로 지정)")

    keys = ["tollgate_id", "year", "vehicle_type", "direction"]
    if granularity == "date" and not value_is_daily:
        # 일별/월별 원본 → 연 합계 + 관측일수로 일평균
        agg = out.groupby(keys, as_index=False).agg(
            volume=("volume_raw", "sum"),
            n_obs=("_date", "nunique"),
            lat=("lat", "first"), lon=("lon", "first"))
        agg["avg_daily"] = agg["volume"] / agg["n_obs"].clip(lower=1)
        partial = agg[agg["n_obs"] < 300]
        if len(partial):
            print(f"  ⚠️ 관측일수 300일 미만인 셀 {len(partial):,}개 — "
                  f"연 합계가 과소집계일 수 있어 avg_daily 사용을 권합니다")
        agg = agg.drop(columns=["n_obs"])
    elif value_is_daily:
        agg = out.groupby(keys, as_index=False).agg(
            avg_daily=("volume_raw", "mean"), lat=("lat", "first"), lon=("lon", "first"))
        agg["volume"] = (agg["avg_daily"] * 365).round()
    else:
        agg = out.groupby(keys, as_index=False).agg(
            volume=("volume_raw", "sum"), lat=("lat", "first"), lon=("lon", "first"))
        agg["avg_daily"] = agg["volume"] / 365

    agg["volume"] = agg["volume"].round().astype("int64")
    agg["source"] = source
    agg["unit_type"] = unit_type
    agg["match_km"] = 0.0
    return agg


def map_points_to_tollgates(traffic: pd.DataFrame, tollgates: pd.DataFrame,
                            max_km: float = 5.0) -> pd.DataFrame:
    """본선 지점(좌표 보유) 자료를 가장 가까운 영업소에 귀속시킨다.

    본선 지점 교통량은 **통과 교통을 포함**하므로 영업소 진출입량과 성격이 다르다.
    그래도 장기 시계열이 이쪽에만 있어서, source='aadt' 로 구분해 함께 보관한다.
    """
    from ..transform.spatial import haversine_matrix

    has_coord = traffic["lat"].notna() & traffic["lon"].notna()
    if not has_coord.any():
        print("  좌표가 없어 지점→영업소 매핑을 건너뜁니다 "
              "(파일에 위도/경도 컬럼이 있어야 합니다)")
        return traffic

    tg = tollgates.dropna(subset=["lat", "lon"])
    if tg.empty:
        raise ValueError("영업소 좌표가 없습니다. 먼저 `tollgates` 를 적재하세요.")

    points = traffic[has_coord].drop_duplicates(subset=["tollgate_id"])[
        ["tollgate_id", "lat", "lon"]]
    dist = haversine_matrix(points["lat"], points["lon"], tg["lat"], tg["lon"])
    nearest = dist.argmin(axis=1)
    best_km = dist[np.arange(len(points)), nearest]

    lookup = pd.DataFrame({
        "_point_id": points["tollgate_id"].to_numpy(),
        "_mapped_id": tg["tollgate_id"].to_numpy()[nearest],
        "_match_km": best_km,
    })
    lookup = lookup[lookup["_match_km"] <= max_km]
    print(f"  지점 {len(points):,}개 중 {len(lookup):,}개를 {max_km}km 이내 영업소에 매핑")

    merged = traffic.merge(lookup, left_on="tollgate_id", right_on="_point_id", how="inner")
    merged["tollgate_id"] = merged["_mapped_id"]
    merged["match_km"] = merged["_match_km"]
    merged = merged.drop(columns=["_point_id", "_mapped_id", "_match_km"])

    # 한 영업소에 여러 지점이 붙으면 합산 (양방향 지점 등)
    keys = ["tollgate_id", "year", "vehicle_type", "direction", "source", "unit_type"]
    return merged.groupby(keys, as_index=False).agg(
        volume=("volume", "sum"), avg_daily=("avg_daily", "sum"),
        match_km=("match_km", "min"))


def load_and_normalize(path: str | Path | None = None, mapping: dict | None = None,
                       source: str | None = None, unit_type: str = "tollgate",
                       value_is_daily: bool | None = None) -> pd.DataFrame:
    path = Path(path or (RAW / "traffic.csv"))
    return normalize(read_any(path), mapping, source or path.stem, unit_type, value_is_daily)
