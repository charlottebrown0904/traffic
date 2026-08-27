"""이미 확보한 교통량 데이터를 표준 스키마(traffic 테이블)로 정규화.

사용자가 도로공사 API로 받아둔 파일 형태를 모르므로:
  * `inspect()` 로 컬럼을 먼저 확인하고
  * `COLUMN_HINTS` 에 실제 컬럼명을 추가하거나 `mapping` 인자로 직접 지정한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import RAW, settings

COLUMN_HINTS = {
    "tollgate_id": ["unitCode", "tcsUnitCode", "영업소코드", "tollgate_id", "icCode"],
    "name": ["unitName", "영업소명", "tollgate_name", "name"],
    "year": ["year", "년도", "연도", "aggYear", "sumYm", "집계연도"],
    "date": ["sumDate", "집계일자", "date", "ymd", "aggDate"],
    "vehicle_type": ["carType", "차종", "vehicle_type", "tcsCarKnd"],
    "direction": ["direction", "방향", "ioType", "구분"],
    "volume": ["trafficAmout", "trafficAmount", "교통량", "volume", "tcsVol", "합계"],
}


def inspect(path: str | Path) -> pd.DataFrame:
    """어떤 컬럼이 들어있는지 먼저 보여준다. 매핑 작성용."""
    df = read_any(path)
    print(f"행 {len(df):,} / 열 {len(df.columns)}")
    print("컬럼:", list(df.columns))
    print(df.head(5).to_string())
    return df


def read_any(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() in (".csv", ".txt"):
        return pd.read_csv(path, dtype=str)
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() in (".json", ".jsonl"):
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".jsonl":
            return pd.DataFrame([json.loads(line) for line in text.splitlines() if line.strip()])
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = next(
                (v for v in payload.values() if isinstance(v, list)), []
            )
        return pd.DataFrame(payload)
    raise ValueError(f"지원하지 않는 파일 형식: {path.suffix}")


def _resolve(columns, hints: list[str]) -> str | None:
    lowered = {str(c).lower(): c for c in columns}
    for hint in hints:
        if hint.lower() in lowered:
            return lowered[hint.lower()]
    return None


def normalize(df: pd.DataFrame, mapping: dict | None = None) -> pd.DataFrame:
    """원본 → traffic 스키마. 연도별 차종별 합계로 집계한다."""
    mapping = mapping or {}
    resolved = {
        field: mapping.get(field) or _resolve(df.columns, hints)
        for field, hints in COLUMN_HINTS.items()
    }

    missing = [f for f in ("tollgate_id", "volume") if not resolved[f]]
    if missing:
        raise ValueError(
            f"필수 컬럼을 찾지 못했습니다: {missing}\n"
            f"실제 컬럼: {list(df.columns)}\n"
            f"redt.collect.traffic.COLUMN_HINTS 에 추가하거나 mapping= 으로 지정하세요."
        )

    out = pd.DataFrame({
        "tollgate_id": df[resolved["tollgate_id"]].astype(str).str.strip(),
        "volume": pd.to_numeric(df[resolved["volume"]], errors="coerce"),
    })

    # 연도: year 컬럼이 없으면 날짜 컬럼 앞 4자리에서 뽑는다
    if resolved["year"]:
        out["year"] = pd.to_numeric(
            df[resolved["year"]].astype(str).str.extract(r"(\d{4})")[0], errors="coerce"
        )
    elif resolved["date"]:
        out["year"] = pd.to_numeric(
            df[resolved["date"]].astype(str).str.extract(r"(\d{4})")[0], errors="coerce"
        )
    else:
        raise ValueError("연도를 만들 컬럼(year 또는 date)이 없습니다.")

    out["vehicle_type"] = (
        pd.to_numeric(df[resolved["vehicle_type"]], errors="coerce").fillna(0).astype(int)
        if resolved["vehicle_type"] else 0
    )
    out["direction"] = (
        df[resolved["direction"]].astype(str).str.strip() if resolved["direction"] else "all"
    )

    out = out.dropna(subset=["year", "volume"])
    out["year"] = out["year"].astype(int)

    period = settings()["period"]
    out = out[out["year"].between(period["start_year"], period["end_year"])]

    # 일별/월별 원본이면 연 합계로 접는다
    agg = (
        out.groupby(["tollgate_id", "year", "vehicle_type", "direction"], as_index=False)["volume"]
        .sum()
    )
    agg["volume"] = agg["volume"].round().astype("int64")
    return agg


def load_and_normalize(path: str | Path | None = None, mapping: dict | None = None):
    path = path or (RAW / "traffic.csv")
    return normalize(read_any(path), mapping)
