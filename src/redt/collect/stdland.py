"""표준지공시지가 — 세 원천을 하나의 std_land 표로.

'현재 가치' 2판(공시지가기준법)의 첫 마디가 표준지공시지가다
(docs/radar-and-current-value.md §3). 2026-09-11 에 원천 셋이 한꺼번에
열렸다.

  1. 파일 — 국토교통부_표준지공시지가_20260101.csv (168MB, 구글 드라이브).
     연결기로는 안 읽힌다(빈 문자열). 러너가 '링크가 있는 모든 사용자'
     로 열린 파일을 직접 받는다.
  2. odcloud API — data.go.kr 15004246, Base URL api.odcloud.kr/api,
     승인됨. uddi 는 포털 페이지에만 적혀 있어 긁어서 찾는다
     (scripts/odcloud_landprice.py 와 같은 길).
  3. 브이월드 속성 조회 — /ned/data/getReferLandPriceAttr. 앞서
     'StdrLandPrice' 로 추측해 못 찾던 그 오퍼레이션이다. 이름은
     'ReferLandPrice'(참조 표준지) 였다.

셋의 열 이름을 **여기서 미리 알지 못한다.** 그래서 probe() 가 먼저
필드와 첫 행을 찍고, 적재는 열 이름을 뜻으로 맞추는 사전(COLUMNS)으로
한다 — 못 맞춘 열은 버리지 않고 이름을 출력해 다음 사람이 사전에 더한다.

사람 이름은 이 자료에 없다(표준지는 소유자 정보가 없다). PNU·지번은
공개 자료 그대로 둔다 — 감정평가서와 달리 개인을 가리키지 않는다.
"""
from __future__ import annotations

import io
import json
import re
import time

import pandas as pd

from ..config import keys, settings
from .http import get_once, polite_sleep

PORTAL = "https://www.data.go.kr/data/15004246/openapi.do"
# 승인 화면의 Swagger 주소. 포털의 openapi.do 는 이 데이터셋에 없다(404).
SWAGGER = "https://infuser.odcloud.kr/oas/docs?namespace=15004246/v1"
ODCLOUD = "https://api.odcloud.kr/api/15004246/v1"
VWORLD_ATTR = "https://api.vworld.kr/ned/data/getReferLandPriceAttr"
DOMAIN = "toji.fyi"

# 표준지 열 → 우리 이름. 왼쪽은 후보(부분 일치, 대소문자 무시)이고
# 먼저 맞는 것을 쓴다. 세 원천이 같은 뜻을 다른 이름으로 부른다:
#   파일  : 한글 머리글 (고유번호, 법정동코드, 기준연도, 공시지가, 지목 …)
#   odcloud: 파일과 같은 한글 머리글일 가능성이 큼
#   브이월드: lower_snake (pnu, stdr_year, pblntf_pclnd, lndcgr_code_nm …)
COLUMNS = {
    "pnu":           ("고유번호", "pnu", "필지고유번호", "표준지고유번호"),
    "ld_code":       ("법정동코드", "ldcodenm!", "ld_code", "ldcode", "법정동 코드"),
    "ld_name":       ("법정동명", "ld_code_nm", "ldcodenm", "법정동 명", "소재지"),
    "special":       ("특수지구분", "regstrsecodenm", "regstr_se_code_nm", "대장구분"),
    "jibun":         ("지번", "mnnmslno", "lnm", "본번"),
    # 2026 파일(국토교통부_표준지공시지가_20260101.csv)의 조각 열. PNU 가 빈 행이
    # 있어 이것으로 PNU 를 만든다: 시군구5 + 읍면동리5 + 지번구분1 + 본번4 + 부번4.
    "sgg_code":      ("시군구",),
    "umd_code":      ("읍면동리",),
    "bun":           ("본번지",),
    "ji":            ("부번지",),
    "jibun_kind":    ("지번구분",),
    "prev_price":    ("전년지가",),
    "std_no":        ("표준지일련번호", "stdlandsn", "일련번호", "refer_land_no", "stdland_no"),
    "year":          ("기준연도", "기준년도", "stdr_year", "stdryear", "공시연도"),
    "month":         ("기준월", "stdr_mt", "stdrmt"),
    "price":         ("공시지가", "pblntf_pclnd", "pblntfpclnd", "단위면적당가격", "가격"),
    "jimok":         ("지목", "lndcgrcodenm", "lndcgr_code_nm", "lndcgr"),
    "area_m2":       ("면적", "lndpcl_ar", "lndpclar", "토지면적"),
    "land_use":      ("용도지역1", "용도지역", "prposareanm1", "prpos_area_1_nm", "prposarea1", "prpos_area_1", "용도지역명1"),
    "land_use2":     ("용도지역2", "prposareanm2", "prpos_area_2_nm", "prposarea2", "prpos_area_2", "용도지역명2"),
    "district":      ("용도지구1", "용도지구", "prposdstrcnm1", "prpos_dstrc_nm_1"),
    "district2":     ("용도지구2", "prposdstrcnm2", "prpos_dstrc_nm_2"),
    "use_situation": ("이용상황", "ladusesittnnm", "lad_use_sittn_nm", "lad_use_sittn", "토지이용상황"),
    "surroundings":  ("주위환경", "주위 환경", "surrounding"),
    "road_side":     ("도로접면", "roadsidecodenm", "road_side_code_nm", "road_side", "도로 접면", "도로교통"),
    "road_dist":     ("도로거리", "roaddstnccodenm", "road_dstnc_code_nm"),
    "slope":         ("지형높이", "지세", "tpgrphhgcodenm", "tpgrph_hg_code_nm", "tpgrph_hg", "고저"),
    "shape":         ("지형형상", "형상", "tpgrphfrmcodenm", "tpgrph_frm_code_nm", "tpgrph_frm"),
    "cnflc_rt":      ("저촉률", "cnflcrt", "cnflc_rt"),
    # 코드 열. 이름 열이 빈 행이 있어(2026-09-11 탐침) 코드로 이름을 채운다.
    "land_use_code": ("prposarea1",),
    "land_use2_code": ("prposarea2",),
    "use_code":      ("ladusesittn",),
    "road_side_code": ("roadsidecode",),
    "road_dist_code": ("roaddstnccode",),
    "slope_code":    ("tpgrphhgcode",),
    "shape_code":    ("tpgrphfrmcode",),
    "notice_date":   ("공시일자", "pblntf_de", "고시일자", "lastupdtdt"),
    "lon":           ("경도", "lon", "x좌표", "x"),
    "lat":           ("위도", "lat", "y좌표", "y"),
}

NUMERIC = ("price", "area_m2", "lon", "lat")


def _norm(c) -> str:
    return re.sub(r"[\s_()]", "", str(c)).lower()


def map_columns(cols: list[str]) -> tuple[dict[str, str], list[str]]:
    """원천 열 이름 → 우리 이름. (사전, 못 맞춘 열)

    두 바퀴 돈다. 먼저 **정확히 같은** 이름, 그다음 부분 일치. 그래야
    'ldCode' 가 'ldCodeNm' 을, 'tpgrphFrmCode' 가 'tpgrphFrmCodeNm' 을
    가로채지 않는다 (2026-09-11 탐침에서 실제로 그랬다).
    """
    low = {c: _norm(c) for c in cols}
    out: dict[str, str] = {}
    used: set[str] = set()
    for exact in (True, False):
        for ours, needles in COLUMNS.items():
            if ours in out.values():
                continue
            for n in needles:
                if n.endswith("!"):
                    continue
                nn = _norm(n)
                for c in cols:
                    if c in used:
                        continue
                    hit = (low[c] == nn) if exact else (len(nn) > 1 and nn in low[c])
                    if hit:
                        out[c] = ours
                        used.add(c)
                        break
                if ours in out.values():
                    break
    unmatched = [c for c in cols if c not in used]
    return out, unmatched


def normalize(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """원천 표 → std_land 열. 못 맞춘 열 이름을 함께 돌려준다."""
    mapping, unmatched = map_columns(list(df.columns))
    out = df.rename(columns=mapping)[[c for c in mapping.values()]].copy()
    for c in NUMERIC:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", ""), errors="coerce")
    if "year" in out.columns:
        out["year"] = pd.to_numeric(out["year"], errors="coerce").astype("Int64")
    for c in ("pnu", "ld_code", "jibun", "std_no", "sgg_code", "umd_code", "bun", "ji", "jibun_kind"):
        if c in out.columns:
            out[c] = out[c].astype(str).str.strip().replace({"nan": None, "None": None, "<NA>": None})
    # 2026 파일: 조각 열로 법정동코드·PNU·지번을 만든다 (PNU 가 빈 행이 있다).
    if {"sgg_code", "umd_code"} <= set(out.columns):
        ld = out["sgg_code"].fillna("").str.zfill(5) + out["umd_code"].fillna("").str.zfill(5)
        ld = ld.where(ld.str.len() == 10, None)
        if "ld_code" not in out.columns:
            out["ld_code"] = ld
        else:
            out["ld_code"] = out["ld_code"].fillna(ld)
        if {"bun", "ji"} <= set(out.columns):
            kind = out["jibun_kind"].fillna("1") if "jibun_kind" in out.columns else "1"
            bun = out["bun"].fillna("0").str.zfill(4)
            ji = out["ji"].fillna("0").str.zfill(4)
            made = ld + kind + bun + ji
            made = made.where(made.str.len() == 19, None)
            if "pnu" not in out.columns:
                out["pnu"] = made
            else:
                out["pnu"] = out["pnu"].fillna(made)
            # PNU 도 못 만들면 조각을 그대로 이어 열쇠로 쓴다 — 지번만으로 열쇠를
            # 만들면 전국이 한 지번으로 겹친다 (run 14: 60만 행이 2,370 행으로 줄었다).
            out["_key"] = (out["sgg_code"].fillna("") + "|" + out["umd_code"].fillna("") + "|"
                           + kind.astype(str) + "|" + bun + "|" + ji)
            jb = bun.str.lstrip("0").replace("", "0") + "-" + ji.str.lstrip("0").replace("", "0")
            jb = jb.str.replace(r"-0$", "", regex=True)
            jb = jb.where(kind.astype(str) != "2", "산 " + jb)
            out["jibun"] = jb
    # PNU 가 없고 법정동코드+지번이 있으면 앞 10자리만이라도 채운다 —
    # 화면은 법정동리(앞 10자리)로 후보 표준지를 고른다.
    if "pnu" not in out.columns and "ld_code" in out.columns:
        out["pnu"] = None
    if "ld_code" not in out.columns and "pnu" in out.columns:
        out["ld_code"] = out["pnu"].str.slice(0, 10)
    out["sigungu_cd"] = out["ld_code"].astype(str).str.slice(0, 5) if "ld_code" in out.columns else None
    # 브이월드는 빈 값을 "" 로 준다. 빈 문자열은 값이 아니다.
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].where(out[c].astype(str).str.strip() != "", None)
    out = learn_and_fill(out)
    out = out.dropna(subset=["price"]) if "price" in out.columns else out
    return out, unmatched


# ── 1. 파일 (구글 드라이브 → 러너) ──────────────────────────────

def drive_download(file_id: str, dest: str) -> int:
    """'링크가 있는 모든 사용자' 로 열린 드라이브 파일을 받는다.

    큰 파일은 '바이러스 검사를 못 했다' 는 중간 페이지가 끼는데,
    usercontent 주소에 confirm=t 를 붙이면 그것을 건너뛴다. 받은 것이
    HTML 이면(공유가 안 열린 경우) 그 사실을 바로 말한다.
    """
    import requests
    url = "https://drive.usercontent.google.com/download"
    with requests.get(url, params={"id": file_id, "export": "download", "confirm": "t"},
                      stream=True, timeout=120) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "text/html" in ctype:
            raise RuntimeError("드라이브가 HTML 을 돌려줬습니다 — 파일이 '링크가 있는 "
                               "모든 사용자' 로 열려 있는지 확인하세요")
        n = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                n += len(chunk)
    return n


def read_csv_any(path: str, nrows: int | None = None) -> pd.DataFrame:
    """인코딩을 모른다. cp949 → utf-8-sig → utf-8 순으로 연다."""
    last = None
    for enc in ("cp949", "utf-8-sig", "utf-8", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc, nrows=nrows, dtype=str, low_memory=False)
        except UnicodeDecodeError as exc:
            last = exc
    raise last  # type: ignore[misc]


def load_csv(con, path: str, chunk: int = 200_000, year: int | None = None) -> dict:
    """CSV → std_land. 168MB 라 통째로 안 읽고 조각으로 넣는다.

    year: 파일에 기준연도 열이 없을 때 (2026 파일이 그렇다) 쓸 연도.
    파일 이름에 20260101 처럼 날짜가 있으면 거기서 읽는다."""
    from .. import db
    head = read_csv_any(path, nrows=5)
    mapping, unmatched = map_columns(list(head.columns))
    if year is None and "year" not in mapping.values():
        m = re.search(r"(20\d{2})[01]\d[0-3]\d", str(path))
        if m:
            year = int(m.group(1))
    if "year" not in mapping.values():
        if year is None:
            raise ValueError("파일에 기준연도 열이 없습니다 — year 를 주세요 (예: 2026)")
        print(f"  기준연도 열이 없어 {year} 으로 넣습니다")
    # 무엇이 들어 있는지 눈으로 — 열 이름만 맞고 값이 딴것인 일이 있다.
    show = [c for c in head.columns if mapping.get(c) in ("pnu", "ld_code", "sgg_code", "umd_code",
                                                            "bun", "ji", "jibun_kind", "jibun", "year", "price")]
    if show:
        print("  첫 세 행:")
        for _, r in head[show].head(3).iterrows():
            print("    " + " · ".join(f"{c}={str(r[c])[:22]}" for c in show))
    print(f"  열 {len(head.columns)}개 중 {len(mapping)}개를 맞췄습니다")
    for src, ours in mapping.items():
        print(f"    {src!s:24s} → {ours}")
    if unmatched:
        print(f"  못 맞춘 열 {len(unmatched)}개 (사전에 더할 것): {unmatched}")
    total = 0
    enc = None
    for e in ("cp949", "utf-8-sig", "utf-8", "euc-kr"):
        try:
            pd.read_csv(path, encoding=e, nrows=2, dtype=str)
            enc = e
            break
        except UnicodeDecodeError:
            continue
    # 파일은 그 연도의 전체다 — 지난번에 잘못 들어간 행이 남지 않게 먼저 비운다.
    if year is not None:
        gone = con.execute("SELECT count(*) FROM std_land WHERE source='file' AND year=?", [int(year)]).fetchone()[0]
        if gone:
            con.execute("DELETE FROM std_land WHERE source='file' AND year=?", [int(year)])
            print(f"  예전 파일 적재분 {gone:,}행을 비웠습니다")
    empty_pnu = 0
    for part in pd.read_csv(path, encoding=enc, dtype=str, chunksize=chunk, low_memory=False):
        rows, _ = normalize(part)
        if "year" not in rows.columns or rows["year"].isna().all():
            rows["year"] = year
        if "pnu" in rows.columns:
            empty_pnu += int(rows["pnu"].isna().sum())
        rows = _complete(rows)
        total += db.upsert(con, "std_land", rows)
    if empty_pnu:
        print(f"  PNU 가 빈 행 {empty_pnu:,} (조각으로 만들었거나 조각 열쇠로 넣음)")
    return {"rows": total, "mapped": mapping, "unmatched": unmatched, "encoding": enc}


STD_COLS = ["pnu", "ld_code", "ld_name", "special", "jibun", "std_no", "year", "month",
            "price", "jimok", "area_m2", "land_use", "land_use2", "district", "district2",
            "use_situation", "surroundings", "road_side", "road_dist", "slope", "shape",
            "cnflc_rt", "notice_date", "lon", "lat", "sigungu_cd", "source",
            "land_use_code", "land_use2_code", "use_code", "road_side_code",
            "road_dist_code", "slope_code", "shape_code"]

# 코드 열 ↔ 이름 열. 같은 행에 둘 다 있으면 코드표를 배우고, 이름이 빈
# 행은 배운 코드표로 채운다. 코드표는 추측하지 않는다 — 자료가 준
# 짝에서만 배우고, 못 배운 코드는 빈 채로 둔다.
CODE_PAIRS = {
    "land_use_code": "land_use", "land_use2_code": "land_use2", "use_code": "use_situation",
    "road_side_code": "road_side", "road_dist_code": "road_dist",
    "slope_code": "slope", "shape_code": "shape",
}
_CODEBOOK: dict[str, dict[str, str]] = {}


def _codebook_path():
    from ..config import PROCESSED
    return PROCESSED / "stdland_codes.json"


def load_codebook() -> dict:
    global _CODEBOOK
    if not _CODEBOOK:
        try:
            _CODEBOOK = json.loads(_codebook_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CODEBOOK = {}
    return _CODEBOOK


def save_codebook() -> None:
    try:
        _codebook_path().parent.mkdir(parents=True, exist_ok=True)
        _codebook_path().write_text(json.dumps(_CODEBOOK, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    except OSError:
        pass


def learn_and_fill(df: pd.DataFrame) -> pd.DataFrame:
    """코드·이름 짝에서 코드표를 배우고 빈 이름을 채운다."""
    book = load_codebook()
    for code_col, name_col in CODE_PAIRS.items():
        if code_col not in df.columns:
            continue
        if name_col not in df.columns:
            df[name_col] = None
        code = df[code_col].astype(str).str.strip()
        name = df[name_col].astype(str).str.strip()
        both = (code != "") & (code != "None") & (code != "nan") & (name != "") & (name != "None") & (name != "nan")
        table = book.setdefault(code_col, {})
        for c, n in zip(code[both], name[both]):
            table.setdefault(c, n)
        blank = ~both & (code != "") & (code != "None") & (code != "nan")
        if blank.any() and table:
            df.loc[blank, name_col] = code[blank].map(table).where(code[blank].map(table).notna(), None)
    return df


def _complete(rows: pd.DataFrame, source: str = "file") -> pd.DataFrame:
    for c in STD_COLS:
        if c not in rows.columns:
            rows[c] = None
    rows["source"] = source
    # 열쇠. PNU 가 없으면 법정동코드+지번+연도로 만든다.
    #
    # pandas 3 은 빈 값을 문자열로 바꿔도 <NA> 로 두고, <NA> 와 이어 붙이면
    # 통째로 <NA> 가 된다. 2026 파일에는 연도 열이 없어 std_id 가 전부 비었고
    # NOT NULL 에 걸렸다 (run 13). 그래서 빈 값은 먼저 글자로 메운다.
    def txt(col, empty=""):
        return rows[col].astype("object").where(rows[col].notna(), empty).astype(str)
    pnu = txt("pnu").replace({"None": "", "nan": "", "<NA>": ""})
    fallback = txt("_key") if "_key" in rows.columns else txt("ld_code") + "-" + txt("jibun")
    key = pnu.where(pnu != "", fallback)
    rows["std_id"] = key + "-" + txt("year", "0")
    dup = rows["std_id"].duplicated().sum()
    if dup:
        print(f"  ! 열쇠가 겹치는 행 {dup:,} — 마지막 것만 남는다")
    return rows[["std_id"] + STD_COLS]


# ── 2. odcloud ─────────────────────────────────────────────────

def find_uddis() -> list[str]:
    """스웨거 문서 → 경로(uddi). 포털 페이지가 404 라 스웨거로 간다.
    infuser 는 중계 목록에 없어 러너가 직접 부른다 — 막히면 그 사실을 적는다."""
    import requests
    found: list[str] = []
    try:
        r = requests.get(SWAGGER, timeout=30)
        print(f"  스웨거 HTTP {r.status_code} · {len(r.text):,}바이트")
        if r.status_code == 200:
            try:
                doc = r.json()
                paths = list((doc.get("paths") or {}).keys())
                print(f"  경로 {len(paths)}개: {paths[:6]}")
                for p in paths:
                    m = re.search(r"uddi:[0-9a-fA-F-]{8,}", p)
                    found.append(m.group(0) if m else p.strip("/"))
                # 열 이름도 스웨거에 있다 — 응답 스키마의 properties.
                for name, schema in (doc.get("components", {}).get("schemas") or {}).items():
                    props = list((schema.get("properties") or {}).keys())
                    if props:
                        print(f"  스키마 {name}: {props[:40]}")
            except ValueError:
                found = sorted(set(re.findall(r"uddi:[0-9a-fA-F-]{8,}", r.text)))
    except Exception as exc:                      # noqa: BLE001
        print(f"  스웨거 실패: {exc}")
    if not found:
        try:
            resp = get_once(PORTAL, {})
            found = sorted(set(re.findall(r"uddi:[0-9a-fA-F-]{8,}", resp.text)))
            print(f"  포털 HTTP {resp.status_code} · uddi {len(found)}개")
        except Exception as exc:                  # noqa: BLE001
            print(f"  포털 페이지 실패: {exc}")
    return found


def odcloud_page(uddi: str, page: int, per_page: int, cond: dict | None = None) -> dict:
    params = {"page": page, "perPage": per_page, "returnType": "JSON",
              "serviceKey": keys().require("data_go_kr"), **(cond or {})}
    resp = get_once(f"{ODCLOUD}/{uddi}", params, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} {resp.text[:200]}")
    return json.loads(resp.text)


def fetch_odcloud(con, uddi: str, per_page: int = 1000, max_pages: int | None = None) -> dict:
    """odcloud 를 끝까지 넘겨 std_land 에 넣는다. 재개 가능하게 페이지마다 넣는다."""
    from .. import db
    first = odcloud_page(uddi, 1, per_page)
    total = int(first.get("totalCount") or 0)
    pages = (total + per_page - 1) // per_page
    if max_pages:
        pages = min(pages, max_pages)
    print(f"  전체 {total:,}행 · {per_page}행씩 {pages}쪽")
    got = 0
    unmatched: list[str] = []
    for page in range(1, pages + 1):
        payload = first if page == 1 else odcloud_page(uddi, page, per_page)
        data = payload.get("data") or []
        if not data:
            break
        rows, unmatched = normalize(pd.DataFrame(data))
        rows = _complete(rows, source="odcloud")
        got += db.upsert(con, "std_land", rows)
        save_codebook()
        if page % 20 == 0:
            print(f"    {page}/{pages}쪽 · {got:,}행")
        polite_sleep(0.2)
    return {"rows": got, "total": total, "unmatched": unmatched}


# ── 3. 브이월드 속성 조회 ──────────────────────────────────────

def vworld_attr(params: dict) -> tuple[list[dict], str]:
    p = {"format": "json", "numOfRows": "5", "pageNo": "1", "domain": DOMAIN, **params}
    resp = get_once(VWORLD_ATTR, p, timeout=30)
    body = resp.text
    if resp.status_code != 200:
        return [], f"HTTP {resp.status_code} {body[:160]}"
    try:
        payload = json.loads(body)
    except ValueError:
        return [], "JSON 아님: " + re.sub(r"\s+", " ", body[:160])
    rows = _rows(payload)
    if not rows:
        return [], re.sub(r"\s+", " ", body[:200])
    return rows, ""


def _rows(payload) -> list[dict]:
    if isinstance(payload, dict):
        for v in payload.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
            if isinstance(v, dict):
                r = _rows(v)
                if r:
                    return r
    return []


# ── 브이월드 적재 ─────────────────────────────────────────────
#
# 2026-09-11 탐침: ldCode(법정동 10자리)만 주면 그 동리의 표준지가 **모든
# 해**(2012 부터) 로 온다. pnu 는 받지 않고(INVALID_TYPE), stdrYear=2026 은
# 0건이었다 — 어느 해까지 있는지는 probe 가 센다. ldCode 는 2~10자리라
# 시군구(5자리)로 부르면 한 번에 시군구 전체가 온다.

def fetch_vworld(con, sigungu_codes: list[str], years: list[int] | None = None,
                 per_page: int = 1000) -> dict:
    """시군구 단위로 표준지 속성을 받아 std_land 에 넣는다. 재개 가능 —
    이미 그 시군구·연도가 들어 있으면 건너뛴다."""
    from .. import db
    total = 0
    skipped = 0
    for code in sigungu_codes:
        for year in (years or [None]):
            if year is not None:
                # 5자리면 그 시군구, 2자리(훑어 둔 코드가 없는 시도)면 그 시도 전체.
                have = con.execute("SELECT count(*) FROM std_land WHERE source='vworld' "
                                   "AND sigungu_cd LIKE ? AND year=?", [code + "%", year]).fetchone()[0]
                if have:
                    skipped += 1
                    continue
            page = 1
            got = 0
            while True:
                params = {"ldCode": code, "numOfRows": str(per_page), "pageNo": str(page)}
                if year is not None:
                    params["stdrYear"] = str(year)
                rows, msg = vworld_attr(params)
                if not rows:
                    if page == 1 and msg and "totalCount" not in msg:
                        print(f"  {code} {year or '전체'}: {msg[:120]}")
                    break
                df, _ = normalize(pd.DataFrame(rows))
                df = _complete(df, source="vworld")
                got += db.upsert(con, "std_land", df)
                if len(rows) < per_page:
                    break
                page += 1
                polite_sleep(0.15)
            total += got
            print(f"  {code} {year or '전체'}: {got:,}행")
            polite_sleep(0.15)
    save_codebook()
    return {"rows": total, "skipped": skipped}


# ── 탐침 ────────────────────────────────────────────────────────

# 화성 향남 (계획관리 공장 지대) · 용인 처인 (평가서 표본이 많은 곳)
SAMPLE_LD = ["4159025329", "4146125025"]
SAMPLE_PNU = "4159025329106740000"


def probe() -> dict:
    out: dict = {}
    print("1. odcloud (15004246)")
    uddis = find_uddis()
    out["odcloud"] = []
    for u in uddis[:6]:
        try:
            payload = odcloud_page(u, 1, 3)
        except Exception as exc:                  # noqa: BLE001
            print(f"  {u}: 실패 — {exc}")
            continue
        data = payload.get("data") or []
        total = payload.get("totalCount")
        fields = list(data[0].keys()) if data else []
        mapping, unmatched = map_columns(fields)
        print(f"  {u}: totalCount={total} · 필드 {len(fields)}개")
        print(f"     필드: {fields}")
        print(f"     맞춘 것: {mapping}")
        print(f"     못 맞춘 것: {unmatched}")
        if data:
            print(f"     첫 행: {json.dumps(data[0], ensure_ascii=False)[:500]}")
        out["odcloud"].append({"uddi": u, "total": total, "fields": fields,
                               "mapped": mapping, "unmatched": unmatched,
                               "sample": data[0] if data else None})

    print("\n2. 브이월드 getReferLandPriceAttr")
    out["vworld"] = []
    # 어느 해까지 있는가 — 한 동리를 연도별로 센다.
    years_have = {}
    for y in range(2020, 2027):
        rows, msg = vworld_attr({"ldCode": SAMPLE_LD[0], "stdrYear": str(y), "numOfRows": "1"})
        years_have[y] = len(rows)
        polite_sleep(0.2)
    print(f"  연도별 (동리 {SAMPLE_LD[0]}, 1건 요청): {years_have}")
    out["vworld_years"] = years_have
    # 시군구 5자리로 한 번에 오는가 — totalCount 를 본다.
    for params, label in [({"ldCode": SAMPLE_LD[0][:5], "numOfRows": "3"}, "시군구 5자리 · 연도 없이"),
                          ({"ldCode": SAMPLE_LD[0][:5], "stdrYear": "2025", "numOfRows": "3"}, "시군구 5자리 · 2025"),
                          ({"ldCode": SAMPLE_LD[1], "stdrYear": "2025", "numOfRows": "3"}, "용인 처인 동리 · 2025")]:
        p = {"format": "json", "pageNo": "1", "domain": DOMAIN, **params}
        resp = get_once(VWORLD_ATTR, p, timeout=30)
        body = resp.text
        tc = re.search(r'"totalCount"\s*:\s*"?(\d+)', body)
        rows = _rows(json.loads(body)) if resp.status_code == 200 and body.lstrip().startswith("{") else []
        print(f"  [{label}] HTTP {resp.status_code} · totalCount {tc.group(1) if tc else '?'} · 받은 {len(rows)}건")
        if rows:
            mapping, unmatched = map_columns(list(rows[0].keys()))
            print(f"     맞춘 것: {mapping}")
            print(f"     못 맞춘 것: {unmatched}")
            print(f"     첫 행: {json.dumps(rows[0], ensure_ascii=False)[:600]}")
        out["vworld"].append({"params": label, "http": resp.status_code,
                              "total": tc.group(1) if tc else None, "n": len(rows),
                              "sample": rows[0] if rows else None})
        polite_sleep(0.3)
    return out


def describe(con) -> None:
    n = con.execute("SELECT count(*) FROM std_land").fetchone()[0]
    print(f"std_land {n:,}행")
    if not n:
        return
    df = con.execute("""
        SELECT source, year, count(*) AS n,
               count(DISTINCT sigungu_cd) AS sigungu,
               sum(CASE WHEN lat IS NOT NULL THEN 1 ELSE 0 END) AS with_xy,
               sum(CASE WHEN road_side IS NOT NULL THEN 1 ELSE 0 END) AS with_road,
               sum(CASE WHEN land_use IS NOT NULL THEN 1 ELSE 0 END) AS with_zone
        FROM std_land GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchdf()
    print(df.to_string(index=False))
