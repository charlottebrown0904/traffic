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
# 표준데이터(api.data.go.kr)는 한글이 아니라 축약 영문 키로 옵니다. 실제로
# 받아보고 확인한 이름을 함께 둡니다 — 추측이 아니라 관측입니다.
#
#   bizNm 사업명 · bizBgngYm 사업시작연월 · lctnLotnoAddr 소재지지번
#   lat 위도 · lot 경도(lon 이 아닙니다) · bzar 사업면적
#   bizMthSeNm 사업방식 · ctpvNm 시도명 · sggNm 시군구명
ZONE_COLS = {
    "name": ["단지명", "산업단지명", "지구명", "구역명", "명칭", "단지_명",
             "사업명", "bizNm"],
    "type": ["단지구분", "유형", "구분", "종류", "단지유형",
             "사업방식", "bizMthSeNm"],
    # 도시개발사업에는 '지정일' 이 없고 **사업시작연월**이 옵니다. 지정과
    # 착수는 다른 사건이지만, 둘 다 '그 자리에 개발이 시작된 시점' 이고
    # 우리가 재는 것은 전후 비교입니다. 무엇을 읽었는지 로그에 남으므로
    # 결과를 쓸 때 어느 쪽인지 말할 수 있습니다.
    "designated_date": ["지정일", "지정일자", "최초지정일", "지정고시일",
                        "고시일", "승인일", "사업시작연월", "bizBgngYm"],
    "area_m2": ["지정면적", "면적", "총면적", "사업면적", "규모", "bzar"],
    "address": ["소재지", "주소", "위치", "소재지지번", "소재지도로명",
                "lctnLotnoAddr", "lctnRoadNmAddr"],
    "lat": ["위도", "lat", "y좌표", "ycod"],
    # **lot 이 경도입니다.** longitude 를 lot 으로 줄여 쓴 것이라, lon 만
    # 찾으면 좌표가 반쪽만 붙습니다 — 위도만 읽히고 경도는 결측이 됩니다.
    "lon": ["경도", "lon", "lng", "lot", "x좌표", "xcod"],
    "sigungu_cd": ["시군구코드", "법정동코드", "행정구역코드"],
    # 코드가 없고 이름만 오는 자료가 있습니다. 코드로 바꾸는 표가 아직
    # 없으므로 이름 그대로 들고 있다가, 표가 생기면 붙입니다.
    "sido_nm": ["시도", "시도명", "ctpvNm"],
    "sigungu_nm": ["시군", "시군구", "시군구명", "sggNm"],
}
# KOSIS 는 자기 이름으로 줍니다. 실제로 받아보고 확인한 것입니다.
#
#   C1     지역코드   ("00" = 전국)
#   C1_NM  지역명     ("전국")
#   PRD_DE 기간       ("2006")
#   DT     값         ("48991779")
#   ITM_NM 항목       ("총인구수")
#
# ⚠ C1 이 **법정동 시군구 코드인지 KOSIS 자체 코드인지 아직 모릅니다.**
#   KOSIS 의 시도 코드는 법정동과 다른 체계였습니다(부산 21 vs 26). C1 도
#   그럴 수 있습니다. 확인 전까지는 지역명(C1_NM)으로 맞추는 편이 안전합니다.
REGION_COLS = {
    "sigungu_cd": ["시군구코드", "법정동코드", "행정구역코드", "코드", "C1"],
    "sigungu_nm": ["지역명", "행정구역", "C1_NM"],
    "year": ["연도", "년도", "기준연도", "기준년도", "기준일", "PRD_DE"],
    "population": ["총인구", "인구수", "인구", "주민등록인구", "DT"],
    "households": ["세대수", "세대"],
    "businesses": ["사업체수", "사업체"],
    "employees": ["종사자수", "종사자", "고용"],
    "item_nm": ["항목", "ITM_NM"],
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


TABLE_SUFFIXES = (".csv", ".xlsx", ".xls", ".tsv", ".txt")


def read_table(path: Path) -> pd.DataFrame:
    """공공기관이 주는 모양 그대로 읽는다 — 엑셀이든 cp949 든.

    예전에는 utf-8 CSV 만 읽었다. 그런데 data.go.kr·KOSIS·팩토리온이 주는
    것은 대개 **엑셀(xlsx)이거나 cp949 로 저장된 CSV** 다. 받는 사람에게
    '엑셀에서 열어 UTF-8 CSV 로 다시 저장하세요' 를 시키면, 그 과정에서
    날짜 칸이 숫자로 바뀌거나 시군구코드 앞의 0 이 떨어진다. 그러면 자료가
    조용히 틀어진다.

    교통량 파일에서 이미 같은 벽에 부딪혔다(cp949, 확장자는 zip 인데 실제는
    gzip). 받은 그대로 읽는 쪽이 맞다.
    """
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    last = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError as exc:
            last = exc
    raise RuntimeError(f"{path.name}: 인코딩을 알 수 없습니다 ({last})")


def load_zones(pattern: str = "zones_*.*") -> pd.DataFrame:
    """산업단지·택지지구 지정 현황 CSV → zone_event 모양."""
    frames = []
    for path in sorted(Path(RAW).glob(pattern)):
        if path.suffix.lower() not in TABLE_SUFFIXES:
            continue
        df = read_table(path)
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

    # 빈 칸을 빈 문자열로 바꾼 뒤에 잇는다.
    #
    # 예전에는 astype(str) 만 했다. 그때는 결측이 "nan" 이라는 **글자**가
    # 돼서 zone_id 가 어쨌든 만들어졌는데, pandas 3 의 문자열 dtype 은
    # 결측을 결측인 채로 둔다. 그러면 이어붙인 zone_id 가 통째로 결측이
    # 되고, 적재가 NOT NULL 로 터진다 — zones_housing.csv 의 유형이 빈
    # 한 줄 때문에 172건이 통째로 안 들어갔다. 값 하나가 없다고 파일
    # 전체를 못 쓰게 두면 안 된다.
    def _s(col):
        return col.astype("string").fillna("").str.strip()

    allz["zone_id"] = (_s(allz["type"]) + "|" + _s(allz["name"]) + "|"
                       + _s(allz["designated_date"].dt.strftime("%Y%m%d")))
    # 날짜가 없으면 이벤트가 아니다(위에서 걸렀지만 한 번 더 못박는다).
    empty = allz["zone_id"].str.endswith("|")
    if empty.any():
        print(f"  ⚠ 지정일이 비어 zone_id 를 못 만든 {int(empty.sum())}행 제외")
        allz = allz[~empty]
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


def load_region(pattern: str = "region_*.*") -> pd.DataFrame:
    """시군구×연도 인구·사업체 CSV → region_year 모양 (long)."""
    frames = []
    for path in sorted(Path(RAW).glob(pattern)):
        if path.suffix.lower() not in TABLE_SUFFIXES:
            continue
        df = read_table(path)
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
