"""백필 파서·롤업 검증 (API 키 불필요).

두 가지를 확인한다.
  1) 응답 필드명이 제각각이고 차로별로 쪼개져 와도 영업소 단위로 올바르게 접히는가
  2) 수집이 덜 된 해가 '교통량 감소'로 잘못 잡히지 않는가  ← 이게 진짜 위험
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redt.collect import backfill  # noqa: E402


def test_parse_rows():
    items = [
        {"unitCode": "101", "sumDate": "20240115", "tcsCarKnd": "1", "ioType": "1",
         "tcsHipassGbnCd": "0", "trafficAmout": "1,200", "laneNo": "1"},
        {"unitCode": "101", "sumDate": "20240115", "tcsCarKnd": "1", "ioType": "1",
         "tcsHipassGbnCd": "0", "trafficAmout": "800", "laneNo": "2"},
        {"unitCode": "101", "stdDt": "20240115", "tcsCarKnd": "3", "ioType": "출구",
         "tcsHipassGbnCd": "1", "trafficAmout": "450"},
        {"unitCode": "101", "sumDate": "bad"},
    ]
    df = backfill.parse_rows(items, "20240115")
    assert len(df) == 2, f"불량행이 걸러지지 않음: {df}"
    assert df[df.vehicle_type == 1]["volume"].iat[0] == 2000, "차로별 합산 실패"
    assert set(df["direction"]) == {"in", "out"}, "방향 매핑 실패"
    print("✅ parse_rows: 차로별 합산 / 방향 매핑 / 불량행 제거")


def test_rollup_ignores_missing_days():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE traffic_daily (tollgate_id VARCHAR, sum_date DATE,
        vehicle_type INTEGER, direction VARCHAR, hipass VARCHAR, volume BIGINT)""")
    rows = [("101", d.date(), 1, "all", "0", 1000)
            for year, n in [(2023, 365), (2024, 180)]
            for d in pd.date_range(f"{year}-01-01", periods=n)]
    con.executemany("INSERT INTO traffic_daily VALUES (?,?,?,?,?,?)", rows)

    out = backfill.rollup(con)
    v23 = out[out.year == 2023]["avg_daily"].iat[0]
    v24 = out[out.year == 2024]["avg_daily"].iat[0]
    assert out[out.year == 2024]["volume"].iat[0] == 180_000
    assert abs(v23 - v24) < 1e-6, "수집 누락이 교통량 변화로 새어나옴"
    print("✅ rollup: 연 합계는 -51%지만 avg_daily 는 동일 "
          "→ 수집 누락이 '교통량 감소'로 잡히지 않음")


if __name__ == "__main__":
    test_parse_rows()
    print()
    test_rollup_ignores_missing_days()
