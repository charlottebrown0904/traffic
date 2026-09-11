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
    "ld_code":       ("법정동코드", "ld_code", "ldcode", "법정동 코드"),
    "ld_name":       ("법정동명", "ld_code_nm", "법정동 명", "소재지"),
    "special":       ("특수지구분", "regstr_se", "대장구분"),
    "jibun":         ("지번", "lnm", "본번"),
    "std_no":        ("표준지일련번호", "일련번호", "refer_land_no", "stdland_no"),
    "year":          ("기준연도", "기준년도", "stdr_year", "stdryear", "공시연도"),
    "month":         ("기준월", "stdr_mt", "stdrmt"),
    "price":         ("공시지가", "pblntf_pclnd", "pblntfpclnd", "단위면적당가격", "가격"),
    "jimok":         ("지목", "lndcgr", "lndcgr_code_nm"),
    "area_m2":       ("면적", "lndpcl_ar", "토지면적"),
    "land_use":      ("용도지역1", "용도지역", "prpos_area_1", "prpos_area_1_nm", "용도지역명1"),
    "land_use2":     ("용도지역2", "prpos_area_2", "prpos_area_2_nm", "용도지역명2"),
    "use_situation": ("이용상황", "lad_use_sittn", "토지이용상황"),
    "surroundings":  ("주위환경", "주위 환경", "surrounding"),
    "road_side":     ("도로접면", "road_side", "도로 접면", "도로교통"),
    "slope":         ("지형높이", "지세", "tpgrph_hg", "고저"),
    "shape":         ("지형형상", "형상", "tpgrph_frm"),
    "notice_date":   ("공시일자", "pblntf_de", "고시일자"),
    "lon":           ("경도", "lon", "x좌표", "x"),
    "lat":           ("위도", "lat", "y좌표", "y"),
}

NUMERIC = ("price", "area_m2", "lon", "lat")


def map_columns(cols: list[str]) -> tuple[dict[str, str], list[str]]:
    """원천 열 이름 → 우리 이름. (사전, 못 맞춘 열)"""
    low = {c: re.sub(r"[\s_()]", "", str(c)).lower() for c in cols}
    out: dict[str, str] = {}
    used: set[str] = set()
    for ours, needles in COLUMNS.items():
        for c in cols:
            if c in used:
                continue
            if any(re.sub(r"[\s_()]", "", n).lower() in low[c] for n in needles):
                # 'x' 같은 한 글자 후보는 정확히 같을 때만
                if any(len(n) <= 1 for n in needles) and low[c] not in (n.lower() for n in needles):
                    if not any(len(n) > 1 and re.sub(r"[\s_()]", "", n).lower() in low[c] for n in needles):
                        continue
                out[c] = ours
                used.add(c)
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
    for c in ("pnu", "ld_code", "jibun", "std_no"):
        if c in out.columns:
            out[c] = out[c].astype(str).str.strip().replace({"nan": None, "None": None})
    # PNU 가 없고 법정동코드+지번이 있으면 앞 10자리만이라도 채운다 —
    # 화면은 법정동리(앞 10자리)로 후보 표준지를 고른다.
    if "pnu" not in out.columns and "ld_code" in out.columns:
        out["pnu"] = None
    if "ld_code" not in out.columns and "pnu" in out.columns:
        out["ld_code"] = out["pnu"].str.slice(0, 10)
    out["sigungu_cd"] = out["ld_code"].astype(str).str.slice(0, 5) if "ld_code" in out.columns else None
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


def load_csv(con, path: str, chunk: int = 200_000) -> dict:
    """CSV → std_land. 168MB 라 통째로 안 읽고 조각으로 넣는다."""
    from .. import db
    head = read_csv_any(path, nrows=5)
    mapping, unmatched = map_columns(list(head.columns))
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
    for part in pd.read_csv(path, encoding=enc, dtype=str, chunksize=chunk, low_memory=False):
        rows, _ = normalize(part)
        rows = _complete(rows)
        total += db.upsert(con, "std_land", rows)
    return {"rows": total, "mapped": mapping, "unmatched": unmatched, "encoding": enc}


STD_COLS = ["pnu", "ld_code", "ld_name", "special", "jibun", "std_no", "year", "month",
            "price", "jimok", "area_m2", "land_use", "land_use2", "use_situation",
            "surroundings", "road_side", "slope", "shape", "notice_date", "lon", "lat",
            "sigungu_cd", "source"]


def _complete(rows: pd.DataFrame, source: str = "file") -> pd.DataFrame:
    for c in STD_COLS:
        if c not in rows.columns:
            rows[c] = None
    rows["source"] = source
    # 열쇠. PNU 가 없으면 법정동코드+지번+연도로 만든다.
    key = rows["pnu"].where(rows["pnu"].notna() & (rows["pnu"].astype(str) != "None"),
                            rows["ld_code"].astype(str) + "-" + rows["jibun"].astype(str))
    rows["std_id"] = key.astype(str) + "-" + rows["year"].astype(str)
    return rows[["std_id"] + STD_COLS]


# ── 2. odcloud ─────────────────────────────────────────────────

def find_uddis() -> list[str]:
    try:
        resp = get_once(PORTAL, {})
    except Exception as exc:                      # noqa: BLE001
        print(f"  포털 페이지 실패: {exc}")
        return []
    found = sorted(set(re.findall(r"uddi:[0-9a-fA-F-]{8,}", resp.text)))
    print(f"  포털 HTTP {resp.status_code} · uddi {len(found)}개: {found[:6]}")
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
    tries = [
        ({"pnu": SAMPLE_PNU, "stdrYear": "2026"}, "pnu+연도"),
        ({"pnu": SAMPLE_PNU}, "pnu"),
        ({"ldCode": SAMPLE_LD[0], "stdrYear": "2026"}, "ldCode(법정동)+연도"),
        ({"ldCode": SAMPLE_LD[0][:5], "stdrYear": "2026"}, "ldCode(시군구)+연도"),
        ({"ldCode": SAMPLE_LD[0]}, "ldCode(법정동)"),
        ({"stdrYear": "2026"}, "연도만"),
    ]
    out["vworld"] = []
    for params, label in tries:
        rows, msg = vworld_attr(params)
        if rows:
            fields = list(rows[0].keys())
            mapping, unmatched = map_columns(fields)
            print(f"  [{label}] {len(rows)}건 · 필드 {fields}")
            print(f"     맞춘 것: {mapping} · 못 맞춘 것: {unmatched}")
            print(f"     첫 행: {json.dumps(rows[0], ensure_ascii=False)[:500]}")
            out["vworld"].append({"params": label, "n": len(rows), "fields": fields,
                                  "sample": rows[0]})
        else:
            print(f"  [{label}] 없음 — {msg[:160]}")
            out["vworld"].append({"params": label, "n": 0, "memo": msg[:200]})
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
