"""가설3 자료를 파일에서 싣는다 — 산업단지·택지지구·인구.

왜 API 가 아니라 파일인가
-------------------------
odcloud 데이터셋은 uddi 로 부르는데, 그 uddi 는 포털 페이지에만 적혀 있고
그 페이지가 자바스크립트로 그려집니다. 서버가 주는 HTML 에는 없습니다.
탐침(scripts/probe_h3.py)에서 확인했습니다. 서비스 이름을 추측하는 길도
NSDI 에서 이미 한 번 막혔습니다(docs/land-price-fallback.md).

교통량이 똑같은 벽에 막혔을 때 파일로 우회해 잘 돌아가고 있습니다
(data/raw/tcs_annual_*.csv). 같은 방법을 씁니다. 파일 하나만 올리면
나머지는 이 모듈이 합니다.

컬럼 이름은 기관마다 다릅니다. 정확일치로 걸면 한 글자 차이로 통째로
비는데, 그러면 '자료가 없다' 와 '못 읽었다' 를 구분할 수 없습니다.
그래서 후보를 여러 개 두고 부분일치로 찾고, **무엇을 무엇으로 읽었는지
반드시 찍습니다.**
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..config import RAW

# 컬럼 후보. 앞에 있는 것이 우선.
ZONE_COLS = {
    "name": ["단지명", "산업단지명", "지구명", "구역명", "명칭", "단지_명"],
    "type": ["단지구분", "유형", "구분", "종류", "단지유형"],
    "designated_date": ["지정일", "지정일자", "최초지정일", "지정고시일", "고시일", "승인일"],
    "area_m2": ["지정면적", "면적", "총면적", "사업면적", "규모"],
    "address": ["소재지", "주소", "위치", "소재지지번", "소재지도로명"],
    "lat": ["위도", "lat", "y좌표", "ycod"],
    "lon": ["경도", "lon", "x좌표", "xcod"],
    "sigungu_cd": ["시군구코드", "법정동코드", "행정구역코드"],
}
REGION_COLS = {
    "sigungu_cd": ["시군구코드", "법정동코드", "행정구역코드", "코드"],
    "year": ["연도", "년도", "기준연도", "기준년도", "기준일"],
    "population": ["총인구", "인구수", "인구", "주민등록인구"],
    "households": ["세대수", "세대"],
    "businesses": ["사업체수", "사업체"],
    "employees": ["종사자수", "종사자", "고용"],
}

# 면적 단위. 파일마다 ㎡ 로도 천㎡ 로도 준다. 단위를 잘못 읽으면 면적이
# 1000배 틀리는데, 회귀에서는 계수 크기만 달라져 눈에 안 띈다.
AREA_UNITS = {"천m2": 1000.0, "천㎡": 1000.0, "ha": 10000.0, "헥타": 10000.0,
              "km2": 1_000_000.0, "㎢": 1_000_000.0}


def _pick(df: pd.DataFrame, names: list[str]) -> str | None:
    cols = list(df.columns)
    for want in names:
        for col in cols:
            if want.replace(" ", "") in str(col).replace(" ", ""):
                return col
    return None


def _map_columns(df: pd.DataFrame, spec: dict[str, list[str]],
                 label: str) -> dict[str, str]:
    found = {}
    for field, names in spec.items():
        col = _pick(df, names)
        if col:
            found[field] = col
    missing = [f for f in spec if f not in found]
    print(f"  [{label}] 읽은 컬럼: " +
          ", ".join(f"{k}←{v}" for k, v in found.items()))
    if missing:
        print(f"  [{label}] 못 찾은 칸: {missing}")
        print(f"  [{label}] 실제 컬럼: {list(df.columns)[:15]}")
    return found


def _to_year(series: pd.Series) -> pd.Series:
    """'2019', '2019-12-31', '20191231' 을 모두 연도로."""
    text = series.astype(str).str.strip()
    return pd.to_numeric(text.str.extract(r"(\d{4})")[0], errors="coerce")


def _to_area_m2(series: pd.Series, header: str) -> pd.Series:
    factor = 1.0
    for token, mult in AREA_UNITS.items():
        if token.lower() in header.lower():
            factor = mult
            break
    if factor != 1.0:
        print(f"  면적 단위 '{header}' → ㎡ 로 {factor:g}배 환산합니다")
    nums = pd.to_numeric(
        series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
        errors="coerce")
    return nums * factor


def load_zones(pattern: str = "zones_*.csv") -> pd.DataFrame:
    """산업단지·택지지구 지정 현황 CSV → zone_event 모양."""
    frames = []
    for path in sorted(Path(RAW).glob(pattern)):
        df = pd.read_csv(path, encoding="utf-8-sig")
        print(f"  {path.name}  {len(df):,}행")
        cols = _map_columns(df, ZONE_COLS, path.name)
        if "designated_date" not in cols:
            print(f"  ⚠ {path.name}: 지정일이 없어 건너뜁니다 — 전후를 가를 수 없습니다")
            continue

        out = pd.DataFrame({
            "name": df[cols["name"]].astype(str).str.strip() if "name" in cols else "",
            "type": (df[cols["type"]].astype(str).str.strip() if "type" in cols
                     else re.sub(r"^zones_|\.csv$", "", path.name)),
            "designated_date": pd.to_datetime(df[cols["designated_date"]],
                                              errors="coerce"),
        })
        out["area_m2"] = (_to_area_m2(df[cols["area_m2"]], cols["area_m2"])
                          if "area_m2" in cols else pd.NA)
        for axis in ("lat", "lon"):
            out[axis] = (pd.to_numeric(df[cols[axis]], errors="coerce")
                         if axis in cols else pd.NA)
        out["sigungu_cd"] = (df[cols["sigungu_cd"]].astype(str).str.strip().str[:5]
                             if "sigungu_cd" in cols else pd.NA)
        out["address"] = (df[cols["address"]].astype(str).str.strip()
                          if "address" in cols else "")
        out["source"] = path.name

        bad = out["designated_date"].isna()
        if bad.any():
            print(f"  ⚠ {path.name}: 지정일을 못 읽은 {int(bad.sum()):,}행 제외")
            out = out[~bad]
        # 좌표가 한반도 밖이면 버린다. 잘못 찍힌 좌표 하나가 밴드를 뒤집는다.
        has_xy = out["lat"].notna() & out["lon"].notna()
        off = has_xy & ~(out["lat"].between(33, 39) & out["lon"].between(124, 132))
        if off.any():
            print(f"  ⚠ {path.name}: 한반도 밖 좌표 {int(off.sum())}행의 좌표를 비웁니다")
            out.loc[off, ["lat", "lon"]] = pd.NA
        out["geocode_level"] = out["lat"].notna().map({True: "parcel", False: None})
        frames.append(out)

    if not frames:
        return pd.DataFrame()
    allz = pd.concat(frames, ignore_index=True)
    allz["zone_id"] = (allz["type"].astype(str) + "|" + allz["name"].astype(str)
                       + "|" + allz["designated_date"].dt.strftime("%Y%m%d"))
    before = len(allz)
    allz = allz.drop_duplicates(subset=["zone_id"])
    if before != len(allz):
        print(f"  중복 {before - len(allz)}행 병합 ({before} → {len(allz)})")

    n_xy = int(allz["lat"].notna().sum())
    print(f"  개발사건 {len(allz):,}건 · 좌표 있음 {n_xy:,} ({n_xy / max(1, len(allz)):.0%})")
    if n_xy < len(allz):
        print("  좌표 없는 건은 주소를 지오코딩해야 반경 안에 넣을 수 있습니다"
              " (redt.cli geocode-zones).")
    span = allz["designated_date"].dt.year
    print(f"  지정연도 {int(span.min())}~{int(span.max())} · 유형 "
          f"{allz['type'].value_counts().to_dict()}")
    return allz


def load_region(pattern: str = "region_*.csv") -> pd.DataFrame:
    """시군구×연도 인구·사업체 CSV → region_year 모양 (long)."""
    frames = []
    for path in sorted(Path(RAW).glob(pattern)):
        df = pd.read_csv(path, encoding="utf-8-sig")
        print(f"  {path.name}  {len(df):,}행")
        cols = _map_columns(df, REGION_COLS, path.name)
        if "year" not in cols or "sigungu_cd" not in cols:
            print(f"  ⚠ {path.name}: 연도 또는 시군구코드가 없어 건너뜁니다")
            continue

        base = pd.DataFrame({
            "sigungu_cd": df[cols["sigungu_cd"]].astype(str).str.strip().str[:5],
            "year": _to_year(df[cols["year"]]),
        })
        metrics = [m for m in ("population", "households", "businesses", "employees")
                   if m in cols]
        if not metrics:
            print(f"  ⚠ {path.name}: 인구·사업체 값이 하나도 없습니다")
            continue
        for metric in metrics:
            vals = pd.to_numeric(
                df[cols[metric]].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
                errors="coerce")
            part = base.assign(metric=metric, value=vals, source=path.name)
            frames.append(part.dropna(subset=["year", "value"]))

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["year"] = out["year"].astype(int)
    out = out[out["sigungu_cd"].str.fullmatch(r"\d{5}", na=False)]
    out = out.drop_duplicates(subset=["sigungu_cd", "year", "metric"])
    print(f"  지역지표 {len(out):,}행 · 시군구 {out['sigungu_cd'].nunique()}개"
          f" · 연도 {out['year'].min()}~{out['year'].max()}"
          f" · 지표 {sorted(out['metric'].unique())}")
    # 연도가 하나뿐이면 변화율을 못 만든다. 통제로 못 쓰므로 미리 알린다.
    per = out.groupby("metric")["year"].nunique()
    thin = per[per < 2]
    if len(thin):
        print(f"  ⚠ 연도가 하나뿐인 지표: {list(thin.index)} — 변화율을 만들 수 없어"
              " 통제로 쓰지 못합니다.")
    return out[["sigungu_cd", "year", "metric", "value", "source"]]
