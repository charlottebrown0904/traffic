"""철도역과 개통일 — 사용자가 올려 준 네 파일 (2026-09-14).

무엇이 왔나.

    stations.csv        역 416곳 · 위경도 · 주소 215 · 역등급 · 정차횟수
    lines.csv           표준데이터 노선 47개 · 정거장구성 · 노선연장 · 개통일자
    urban_sections.csv  도시철도 구간 38개 · 역개수 · 연장 · 개통일자

**두 가지를 섞지 않는다.** 역에는 개통일이 없다. 노선 파일의 정거장구성
으로 역 이름을 이어 개통일을 붙여 봤더니 광명역이 1974년이 됐다 — 실제로는
2004년이다. 나중에 생긴 역이 노선의 첫 개통일을 뒤집어쓰기 때문이다. 그렇게
만든 날짜로 사건 연구를 하면 결과가 통째로 거짓이 된다.

그래서 역은 **자리**로만 쓴다 (최근접 역까지의 거리 — IC 거리와 같은 꼴).
개통일은 노선·구간 단위로 따로 둔다. 어느 역이 언제 열렸는지가 필요해지면
그때 역별 개통일이 든 자료를 따로 구한다 — 지어내지 않는다.

전화번호 칸(운영기관전화번호)은 정규화할 때 이미 버렸다.
"""
from __future__ import annotations

import pandas as pd

from ..config import ROOT

RAIL_DIR = "data/rail"


def _read(name: str) -> pd.DataFrame:
    path = ROOT / RAIL_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"{path} 가 없습니다")
    return pd.read_csv(path)


def load_stations(con) -> int:
    df = _read("stations.csv")
    df = df.dropna(subset=["위도", "경도"])
    # 좌표가 한반도 밖이면 버린다 — 하나가 거리 계산을 통째로 흔든다.
    ok = df["위도"].between(33, 39) & df["경도"].between(124, 132)
    if (~ok).any():
        print(f"  ⚠ 한반도 밖 좌표 {int((~ok).sum())}행 제외")
        df = df[ok]
    rows = [
        (str(r["역명"]).strip(), float(r["위도"]), float(r["경도"]),
         None if pd.isna(r.get("주소")) else str(r["주소"])[:200],
         None if pd.isna(r.get("역등급")) else str(r["역등급"]),
         (lambda n: None if n is None else int(n))(_num(r.get("정차횟수"))),
         None if pd.isna(r.get("관련노선")) else str(r["관련노선"])[:200],
         "stations.csv")
        for _, r in df.iterrows()
    ]
    con.executemany(
        "INSERT OR REPLACE INTO rail_station"
        " (name, lat, lon, address, grade, trains, lines_txt, source)"
        " VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _num(v) -> float | None:
    """숫자 칸에 '-' 가 섞여 온다. 빈 값과 같게 다룬다."""
    n = pd.to_numeric(v, errors="coerce")
    return None if pd.isna(n) else float(n)


def load_openings(con) -> int:
    rows = []
    ln = _read("lines.csv")
    for _, r in ln.iterrows():
        day = pd.to_datetime(r.get("개통일자"), errors="coerce")
        if pd.isna(day):
            continue
        nm = str(r.get("노선명", "")).strip()
        rows.append((f"노선|{nm}|{day:%Y%m%d}", "노선",
                     str(r.get("운영기관명", "") or ""), nm,
                     f"{r.get('기점명', '')}↔{r.get('종점명', '')}",
                     None,
                     (lambda m: None if m is None else m / 1000)(_num(r.get("노선연장"))),
                     day.date(), str(r.get("정거장구성", ""))[:2000], "lines.csv"))
    us = _read("urban_sections.csv")
    for _, r in us.iterrows():
        day = pd.to_datetime(r.get("개통일자"), errors="coerce")
        if pd.isna(day):
            continue
        line = str(r.get("호선", "")).strip()
        sec = str(r.get("구간", "")).strip()
        rows.append((f"도시철도|{line}|{sec}|{day:%Y%m%d}", "도시철도구간",
                     str(r.get("기관", "") or ""), line, sec,
                     _num(r.get("역개수")), _num(r.get("연장(km)")),
                     day.date(), "", "urban_sections.csv"))
    con.executemany(
        "INSERT OR REPLACE INTO rail_open"
        " (open_id, kind, operator, line_nm, section, n_stations, length_km,"
        "  opened_on, stations_txt, source) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def describe(con) -> None:
    n = con.execute("SELECT count(*) FROM rail_station").fetchone()[0]
    xy = con.execute("SELECT count(*) FROM rail_station WHERE lat IS NOT NULL").fetchone()[0]
    ad = con.execute("SELECT count(*) FROM rail_station WHERE address IS NOT NULL").fetchone()[0]
    print(f"철도역 {n:,} · 좌표 {xy:,} · 주소 {ad:,}")
    top = con.execute(
        "SELECT name, trains FROM rail_station WHERE trains IS NOT NULL"
        " ORDER BY trains DESC LIMIT 5").fetchall()
    if top:
        print("  정차 많은 역: " + " · ".join(f"{a} {b:,}회" for a, b in top))
    rows = con.execute(
        "SELECT kind, count(*), min(opened_on), max(opened_on)"
        " FROM rail_open GROUP BY kind ORDER BY 1").fetchall()
    for kind, cnt, lo, hi in rows:
        print(f"  개통 {kind}: {cnt}건 · {lo} ~ {hi}")
    print("  ※ 역별 개통일은 **없다** — 노선 이름으로 이으면 틀린 날이 나온다"
          " (광명역이 1974년이 됐다). 역은 거리 인자로만 쓴다.")
