"""일별 교통량 백필 — '하루씩 뽑아 1년치를 합친다' 방식의 구현.

`probe-history` 로 과거 조회가 된다는 걸 확인한 뒤 사용한다.
날짜 단위로 traffic_fetch_log 에 기록해 중단되면 이어받는다.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .. import db
from . import ex_api

# 응답 필드명이 확정적이지 않아 후보를 순서대로 탐색한다
ALIASES = {
    "tollgate_id": ["unitCode", "tcsUnitCode", "unitcode", "영업소코드", "icCode"],
    "sum_date":    ["sumDate", "stdDt", "집계일자", "trafficDate", "기준일자", "aggDate"],
    "vehicle_type": ["tcsCarKnd", "tcsCarTypeCd", "carType", "차종", "tcsCarKndCd"],
    "direction":   ["ioType", "tcsIoTypeCd", "입출구구분코드", "입출구구분", "ioTypeCd"],
    # 하이패스 구분을 놓치면 시계열이 통째로 왜곡된다 (모듈 하단 주석 참고)
    "hipass":      ["tcsHipassGbnCd", "hipassGbn", "TCS하이패스구분코드",
                    "tcsHipassGbn", "hipassType"],
    "volume":      ["trafficAmout", "trafficAmount", "교통량", "tcsVol", "통행량"],
}

DIRECTION_MAP = {"1": "in", "2": "out", "입구": "in", "출구": "out",
                 "in": "in", "out": "out"}


def _pick(row: dict, aliases: list[str]):
    for key in aliases:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def parse_rows(items: list[dict], fallback_date: str) -> pd.DataFrame:
    records = []
    for row in items:
        volume = _pick(row, ALIASES["volume"])
        tollgate = _pick(row, ALIASES["tollgate_id"])
        if volume is None or tollgate is None:
            continue
        raw_date = str(_pick(row, ALIASES["sum_date"]) or fallback_date)
        digits = "".join(ch for ch in raw_date if ch.isdigit())[:8]
        if len(digits) != 8:
            continue
        raw_dir = str(_pick(row, ALIASES["direction"]) or "all").strip()
        hipass = _pick(row, ALIASES["hipass"])
        vtype = _pick(row, ALIASES["vehicle_type"])
        records.append({
            "tollgate_id": str(tollgate).strip(),
            "sum_date": f"{digits[:4]}-{digits[4:6]}-{digits[6:]}",
            "vehicle_type": int(pd.to_numeric(vtype, errors="coerce") or 0),
            "direction": DIRECTION_MAP.get(raw_dir.lower(), raw_dir.lower() or "all"),
            "hipass": str(hipass).strip() if hipass is not None else "all",
            "volume": int(pd.to_numeric(str(volume).replace(",", ""), errors="coerce") or 0),
        })
    if not records:
        return pd.DataFrame()
    frame = pd.DataFrame(records)
    # 같은 키가 여러 행으로 쪼개져 오는 경우가 있어 합산 (예: 차로별 → 영업소별)
    return frame.groupby(
        ["tollgate_id", "sum_date", "vehicle_type", "direction", "hipass"],
        as_index=False)["volume"].sum()


def run(endpoint: str, date_param: str, start: date, end: date,
        refresh: bool = False, rows: int = 1000) -> int:
    total = 0
    with db.connect() as con:
        con.execute(db.COLLECT_LOG)
        done = set()
        if not refresh:
            done = {r[0] for r in con.execute(
                "SELECT sum_date FROM traffic_fetch_log WHERE status <> 'error'"
            ).fetchall()}

        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        todo = [d for d in days if d not in done]
        print(f"백필 대상 {len(todo):,}일 (전체 {len(days):,}일 / 완료 {len(done):,}일)")

        for i, day in enumerate(todo, 1):
            stamp = day.strftime("%Y%m%d")
            try:
                items = ex_api.fetch(endpoint, {date_param: stamp}, rows=rows)
                frame = parse_rows(items, stamp)
                n = db.upsert(con, "traffic_daily", frame)
                con.execute(
                    "INSERT OR REPLACE INTO traffic_fetch_log VALUES (?, ?, ?, ?)",
                    [day, n, "ok" if n else "empty", ""])
                total += n
            except Exception as exc:
                con.execute(
                    "INSERT OR REPLACE INTO traffic_fetch_log VALUES (?, ?, ?, ?)",
                    [day, 0, "error", str(exc)[:500]])
                print(f"  실패 {stamp}: {exc}")
            if i % 30 == 0 or i == len(todo):
                print(f"  {i:,}/{len(todo):,}  누적 {total:,}행")
    return total


def rollup(con) -> pd.DataFrame:
    """traffic_daily → 연 단위 traffic.

    핵심은 **관측일수(n_days)를 세는 것**이다. 수집이 덜 된 해의 합계를
    그대로 쓰면 '교통량이 줄었다'는 가짜 신호가 된다.
    """
    composition = con.execute("""
        SELECT hipass, count(*) AS n, sum(volume) AS vol
        FROM traffic_daily GROUP BY hipass ORDER BY vol DESC
    """).fetchdf()
    if not composition.empty:
        print("하이패스 구분 분포")
        print(composition.to_string(index=False))
        if len(composition) == 1 and composition["hipass"].iat[0] not in ("all", "None"):
            print("\n⚠️ 구분값이 하나뿐입니다. 현금(TCS)만 또는 하이패스만 받고 있다면")
            print("   하이패스 이용률 상승이 '교통량 변화'로 잘못 잡힙니다. 파라미터를 확인하세요.")

    daily = con.execute("""
        SELECT tollgate_id,
               CAST(year(sum_date) AS INTEGER) AS year,
               vehicle_type, direction,
               sum(volume)               AS volume,
               count(DISTINCT sum_date)  AS n_days
        FROM traffic_daily
        GROUP BY tollgate_id, year(sum_date), vehicle_type, direction
    """).fetchdf()
    if daily.empty:
        return daily

    daily["avg_daily"] = daily["volume"] / daily["n_days"].clip(lower=1)
    thin = daily[daily["n_days"] < 300]
    if len(thin):
        print(f"\n⚠️ 관측일수 300일 미만 셀 {len(thin):,}개 "
              f"(전체 {len(daily):,}개) — 분석은 avg_daily 를 쓰므로 영향은 제한적입니다")

    daily["source"] = "tcs"
    daily["unit_type"] = "tollgate"
    daily["match_km"] = 0.0
    return daily.drop(columns=["n_days"])
