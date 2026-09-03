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

    # 6) 예산이 한 종류에 다 먹히지 않는가
    #
    # 예전에는 `for kind in kinds` 로 토지를 다 받은 다음에야 공장 차례가
    # 왔다. 전국 × 2006~2025 는 한 종류만 61,200셀이고 한 번에 35,000셀씩
    # 받으므로, 공장은 세 번째 실행이 되어서야 시작된다. 실제로 그렇게
    # 됐다 — 토지는 2006~2025 20년인데 공장은 2021~2025 5년뿐이었다.
    #
    # 공장이 이 제품의 기준 물건이라 더 나쁘다. 토지는 필지별로 값이 크게
    # 흔들리지만 공장은 용도가 정해져 있어 효과를 읽기에 안정적이다.
    # 그 기준 물건이 맨 뒤에 있었다.
    import argparse                                          # noqa: PLC0415

    class _Ctx:
        def __enter__(self): return FakeCon()
        def __exit__(self, *a): return False

    called = []
    real_connect, real_collect = cli.db.connect, cli._collect_cells
    real_done, real_target = cli.db.done_cells, cli._target_sigungu
    try:
        cli.db.connect = lambda *a, **k: _Ctx()
        cli.db.done_cells = lambda con, kind: set()
        cli._target_sigungu = lambda args, con: {f"C{i}": None for i in range(10)}
        cli._collect_cells = lambda con, kind, todo, workers: (
            called.append((kind, len(todo))), (0, False))[-1]
        cli.cmd_trades(argparse.Namespace(
            kind="land,factory", region="nationwide",
            start="2006-01", end="2025-12",
            max_cells=100, workers=1, refresh=False))
    finally:
        cli.db.connect, cli._collect_cells = real_connect, real_collect
        cli.db.done_cells, cli._target_sigungu = real_done, real_target

    got = dict(called)
    # 시군구 10 × 240개월 = 2,400셀씩, 예산 100 → 50/50
    check("예산을 두 종류가 나눠 쓴다", set(got) == {"land", "factory"},
          f"받은 종류: {sorted(got)}")
    check("한쪽이 예산을 다 먹지 않는다",
          all(v > 0 for v in got.values()) and sum(got.values()) <= 100,
          f"{got}")
    check("고르게 나눈다", abs(got.get("land", 0) - got.get("factory", 0)) <= 1,
          f"{got}")

    # 한쪽이 거의 끝났으면 남는 몫은 다른 쪽이 가져가야 한다 —
    # 안 그러면 마지막에 예산이 놀면서 실행 횟수만 늘어난다.
    called.clear()
    try:
        cli.db.connect = lambda *a, **k: _Ctx()
        cli._target_sigungu = lambda args, con: {f"C{i}": None for i in range(10)}
        cli._collect_cells = lambda con, kind, todo, workers: (
            called.append((kind, len(todo))), (0, False))[-1]
        # 토지는 20셀만 남았다고 둔다 (나머지는 이미 완료)
        allcells = {(c, ym) for c in [f"C{i}" for i in range(10)]
                    for ym in cli._months("2006-01", "2025-12")}
        few = set(list(allcells)[:20])
        cli.db.done_cells = lambda con, kind: (
            set() if kind == "factory" else allcells - few)
        cli.cmd_trades(argparse.Namespace(
            kind="land,factory", region="nationwide",
            start="2006-01", end="2025-12",
            max_cells=100, workers=1, refresh=False))
    finally:
        cli.db.connect, cli._collect_cells = real_connect, real_collect
        cli.db.done_cells, cli._target_sigungu = real_done, real_target
    got = dict(called)
    check("남는 몫은 다른 종류가 가져간다",
          got.get("land") == 20 and got.get("factory") == 80, f"{got}")

    print("\n실패 " + str(len(FAIL)) + "건" if FAIL else "\n동시 수집 검사 전부 통과")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
