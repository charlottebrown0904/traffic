"""동시 수집이 순차 수집과 같은 결과를 내는지 검사한다 (네트워크 없음).

동시 처리는 조용히 틀어지기 쉽다. 결과가 뒤섞이거나, 실패한 셀이 성공으로
기록되거나, 차단당했는데 계속 두드려 남은 셀을 전부 '실패' 로 태워버리거나.
셋 다 예외를 던지지 않고 그냥 잘못된 자료를 남긴다.

  python scripts/test_trades_concurrent.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from redt import cli

FAIL = []


def check(name, ok, detail=""):
    print(f"  {'통과' if ok else '실패'}  {name}" + ("" if ok or not detail else f" — {detail}"))
    if not ok:
        FAIL.append(name)


class FakeCon:
    """DB 대신. 어느 스레드에서 쓰였는지도 함께 기록한다."""

    def __init__(self):
        self.rows = []
        self.preserved = []
        self.logs = []
        self.threads = set()

    def note(self):
        self.threads.add(threading.get_ident())


def patch(monkey_fetch, con):
    cli.rtms.fetch_month = monkey_fetch
    # 진짜 upsert 와 같은 서명이어야 한다. **kw 로 뭉뚱그리면 호출
    # 쪽이 preserve 를 빠뜨려도 이 검사는 통과한다 — 지오코딩이
    # 지워지는 사고가 검사를 지나간 것이 바로 그 모양이었다.
    def _stub(c, t, df, preserve=None):
        c.note()
        c.rows.append(df)
        c.preserved.append(preserve)
        return len(df)
    cli.db.upsert = _stub
    cli.db.log_cell = lambda c, k, code, ym, n, st, msg=None: (
        c.note(), c.logs.append((code, ym, n, st)))[-1]


def main():
    todo = [(f"4159{i:01d}", f"20240{j}") for i in range(5) for j in range(1, 6)]  # 25칸

    # 1) 결과가 빠짐없이, 뒤섞이지 않고 저장되는가
    def ok_fetch(kind, code, ym):
        time.sleep(0.005)                       # 왕복 대기를 흉내
        return pd.DataFrame([{"cell": f"{code}|{ym}"}])

    con = FakeCon()
    patch(ok_fetch, con)
    n, stopped = cli._collect_cells(con, "land", todo, workers=6)
    check("모든 셀을 저장한다", n == len(todo), f"{n} != {len(todo)}")
    check("중단하지 않는다", stopped is False)
    saved = {df["cell"].iat[0] for df in con.rows}
    expect = {f"{c}|{y}" for c, y in todo}
    check("셀과 자료가 뒤바뀌지 않는다", saved == expect,
          f"빠짐 {len(expect - saved)}건")
    check("기록도 셀마다 남는다", len(con.logs) == len(todo))
    check("DB 쓰기는 한 스레드에서만", len(con.threads) == 1, f"{len(con.threads)}개 스레드")

    # 2) 셀 하나가 실패해도 나머지는 계속되는가
    def flaky(kind, code, ym):
        if ym == "202403":
            raise RuntimeError("일시 오류")
        return pd.DataFrame([{"cell": f"{code}|{ym}"}])

    con = FakeCon()
    patch(flaky, con)
    n, stopped = cli._collect_cells(con, "land", todo, workers=6)
    bad = [l for l in con.logs if l[3] == "error"]
    check("실패한 셀만 error 로 남는다", len(bad) == 5, f"{len(bad)}건")
    check("나머지는 계속 저장된다", n == len(todo) - 5, f"{n}건")

    # 3) 연달아 실패하면 멈추는가 (차단 감지)
    def always_fail(kind, code, ym):
        raise RuntimeError("차단")

    many = [(f"41{i:03d}", "202401") for i in range(200)]
    con = FakeCon()
    patch(always_fail, con)
    n, stopped = cli._collect_cells(con, "land", many, workers=6)
    check("연속 실패가 쌓이면 멈춘다", stopped is True)
    check("멈춘 뒤 남은 셀은 건드리지 않는다", len(con.logs) < len(many),
          f"{len(con.logs)}/{len(many)}")

    # 4) 빈 목록
    con = FakeCon()
    patch(ok_fetch, con)
    n, stopped = cli._collect_cells(con, "land", [], workers=6)
    check("빈 목록은 조용히 넘어간다", (n, stopped) == (0, False))

    # 5) 지오코딩 결과를 지키며 저장하는가
    #
    # run 16 에서 거래가 10배 늘었는데 지도에 찍히는 거래는 674 → 387 로
    # 줄었다. 재수집이 좌표를 NULL 로 덮었기 때문이다. 하루 4,000건짜리
    # 호출로 산 좌표가 예외도 경고도 없이 사라졌다.
    con = FakeCon()
    patch(ok_fetch, con)
    cli._collect_cells(con, "land", todo[:3], workers=2)
    check("거래 저장이 좌표를 지키라고 넘긴다",
          bool(con.preserved) and all(
              p and {"lat", "lon", "geocode_level"} <= set(p)
              for p in con.preserved))

    print("\n실패 " + str(len(FAIL)) + "건" if FAIL else "\n동시 수집 검사 전부 통과")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
