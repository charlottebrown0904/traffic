"""지시 2·3 분석과 지시 4 익스포트의 회귀 검사.

실제 자료로는 '계수가 이상하다' 와 '코드가 틀렸다' 를 구분할 수 없다. 답을
아는 가짜 자료를 만들어 넣고, 넣은 값이 그대로 나오는지 본다. 여기서 걸리는
것은 자료 문제가 아니라 전부 코드 문제다.

  실행: python scripts/test_analysis.py   (make test 에 포함)
"""
import json
import os
import sys
from pathlib import Path

# 키를 읽는 시점이 첫 호출이라 redt 를 들이기 전에 넣는다. 가짜 값이면 충분하다
# — 아래 검사는 그물을 던지지 않고 응답을 흉내 낸다.
os.environ.setdefault("VWORLD_KEY", "test-key")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redt.analyze import cross, events          # noqa: E402

fail = []


def check(cond, msg):
    print(("  통과  " if cond else "  실패  ") + msg)
    if not cond:
        fail.append(msg)


# ────────────────────────────────────────────────────────────────
print("1. 지시3 — 횡단 비교가 심어둔 탄력성을 되찾는가")

TRUE_BETA = 0.35
rng = np.random.default_rng(7)
n_ic = 60
traffic = rng.uniform(8_000, 90_000, n_ic)
# 지가를 교통량으로만 만든다. 잡음이 없으니 계수는 정확히 나와야 한다.
ln_price = 10.0 + TRUE_BETA * np.log(traffic)

rows = []
for i in range(n_ic):
    for band in ("0-1", "1-3", "3-5"):
        rows.append({
            "tollgate_id": f"T{i:03d}", "year": 2024, "band": band, "kind": "land",
            "price_index": ln_price[i], "n_trades": 20,
            "sigungu_cd": f"S{i % 8:02d}", "volume_total": traffic[i],
        })
panel = pd.DataFrame(rows)
tgs = pd.DataFrame({
    "tollgate_id": [f"T{i:03d}" for i in range(n_ic)],
    "name": [f"IC{i}" for i in range(n_ic)],
    "sido": ["경기도"] * n_ic, "sigungu": ["화성시"] * n_ic,
    "lat": 37.0 + rng.uniform(-0.4, 0.4, n_ic),
    "lon": 127.0 + rng.uniform(-0.4, 0.4, n_ic),
})

table = cross.build(panel, tgs, year=2024, kind="land", volume_col="volume_total")
check(len(table) == n_ic, f"IC {n_ic}개가 모두 표에 남는다 (실제 {len(table)})")
check(table["교통량순위"].iloc[0] == 1 and
      table["volume_total"].iloc[0] == table["volume_total"].max(),
      "1위가 교통량 최댓값이다")
check(table["교통량순위"].is_monotonic_increasing, "교통량 순위가 1부터 순서대로다")

fits = cross.fit(table, volume_col="volume_total")
raw = fits.loc[fits["모형"] == "raw", "beta"].iloc[0]
check(abs(raw - TRUE_BETA) < 0.02, f"심어둔 β={TRUE_BETA} 를 되찾는다 (얻은 값 {raw:.4f})")
check((fits["모형"] == "+서울거리").any(), "서울거리 통제 모형이 함께 보고된다")

# 거래건수가 적은 IC 는 순위에 넣지 않는다 — 중앙값이 우연이 되기 때문
thin = panel.copy()
thin.loc[thin["tollgate_id"] == "T000", "n_trades"] = 1
kept = cross.build(thin, tgs, year=2024, kind="land", volume_col="volume_total")
check("T000" not in set(kept["tollgate_id"]),
      "IC 당 거래건수가 모자라면 순위에서 뺀다")

# 가격지수가 통째로 비면 빈 표를 돌려주고 죽지 않아야 한다
blank = panel.assign(price_index=np.nan)
check(cross.build(blank, tgs, volume_col="volume_total").empty,
      "가격지수가 전부 없으면 예외 대신 빈 표")


# ────────────────────────────────────────────────────────────────
print("\n2. 지시2 — 이중차분이 심어둔 개통효과를 되찾는가")

TRUE_EFFECT = 0.12
OPEN_FROM = 2023
YEARS = [2021, 2022, 2023, 2024]

trade_rows, link_rows = [], []
tid = 0
for group, tollgates in (("new", ["N1", "N2", "N3"]), ("old", ["O1", "O2", "O3"])):
    for tg in tollgates:
        for year in YEARS:
            for _ in range(40):
                tid += 1
                base = 11.0 + 0.04 * (year - 2021)      # 두 군 공통 추세
                if group == "new" and year >= OPEN_FROM:
                    base += TRUE_EFFECT
                trade_rows.append({
                    "trade_id": f"X{tid}", "kind": "land", "deal_year": year,
                    "sigungu_cd": "41590", "adj_ln_price": base,
                })
                link_rows.append({
                    "trade_id": f"X{tid}", "tollgate_id": tg,
                    "distance_km": 1.2, "band": "1-3", "is_nearest": True,
                })
trades = pd.DataFrame(trade_rows)
links = pd.DataFrame(link_rows)

# load_events 를 가짜 명단으로 바꿔 끼운다 — 저장소의 CSV 에 기대지 않는다.
real_load = events.load_events
events.load_events = lambda: pd.DataFrame({
    "tollgate_id": ["N1", "N2", "N3"],
    "open_year": [OPEN_FROM] * 3,
    "post_from": [OPEN_FROM] * 3,
})
try:
    built = events.build(trades, links, kind="land")
    check(not built.empty, "처치·대조군 패널이 만들어진다")
    check(set(built.loc[built["treated"] == 1, "tollgate_id"]) == {"N1", "N2", "N3"},
          "개통 영업소만 처치군이 된다")
    check(set(built.loc[built["treated"] == 0, "tollgate_id"]) == {"O1", "O2", "O3"},
          "기존 영업소가 대조군이 된다")
    check(built["post"].nunique() == 2, "개통 전후가 모두 남는다")

    model = events.did(built)
    beta = model.params["treated:post"]
    check(abs(beta - TRUE_EFFECT) < 0.01,
          f"심어둔 개통효과 {TRUE_EFFECT} 를 되찾는다 (얻은 값 {beta:.4f})")

    # 효과를 0 으로 두면 계수도 0 이어야 한다 — 설계가 없는 효과를 만들지 않는지
    flat = built.copy()
    flat["adj_ln_price"] = 11.0 + 0.04 * (flat["year"] - 2021)
    zero = events.did(flat).params["treated:post"]
    check(abs(zero) < 1e-6, f"효과가 없으면 계수도 0 이다 (얻은 값 {zero:.6f})")

    # 좌측절단(개통 아님)은 처치군에 들어가면 안 된다
    events.load_events = lambda: pd.DataFrame(
        columns=["tollgate_id", "open_year", "post_from"])
    check(events.build(trades, links, kind="land").empty,
          "개통이 확인된 영업소가 없으면 빈 표")
finally:
    events.load_events = real_load


# ────────────────────────────────────────────────────────────────
print("\n3. 지시4 — 순위 탭이 읽을 traffic.json")

path = ROOT / "public" / "app" / "data" / "traffic.json"
if not path.is_file():
    print("  건너뜀 — traffic.json 이 아직 없습니다 (export-web 실행 전)")
else:
    data = json.loads(path.read_text(encoding="utf-8"))
    ny, nt = len(data["years"]), len(data["types"])
    check(ny > 0 and nt > 0, f"연도 {ny}개 · 차종 {nt}개")
    check(len(data["vehicle_types"]) == nt, "차종 설명이 차종 수와 맞는다")
    check(all(v.get("desc") for v in data["vehicle_types"]),
          "모든 차종에 분류 기준 설명이 있다")
    check(all(g.get("desc") for g in data["vehicle_groups"]),
          "모든 묶음에 설명이 있다")

    bad_shape = [r["id"] for r in data["rows"]
                 if len(r["v"]) != ny or any(len(x) != nt for x in r["v"])]
    check(not bad_shape, f"모든 행이 [{ny}][{nt}] 격자다 (어긋난 행 {bad_shape[:5]})")

    negative = [r["id"] for r in data["rows"]
                if any(v < 0 for row in r["v"] for v in row)]
    check(not negative, f"음수 통행량이 없다 ({negative[:5]})")

    unnamed = [r["id"] for r in data["rows"] if not r.get("name")]
    check(not unnamed, f"이름 없는 영업소가 없다 ({unnamed[:5]})")

    check(data.get("unit", "").find("일평균") >= 0,
          f"단위가 일평균임을 밝힌다 ('{data.get('unit')}')")

# ────────────────────────────────────────────────────────────────
print("\n4. 지시1 — 영업소 좌표 보충의 판정과 캐시")

import json as _json                              # noqa: E402
import tempfile                                   # noqa: E402
from pathlib import Path as _Path                 # noqa: E402

from redt.collect import tollgate_fill as tf      # noqa: E402

# 검색 결과를 캐시에 적을 수 있어야 한다. 고른 후보를 candidates 에 그대로
# 담았다가 json.dumps 가 'Circular reference detected' 로 죽은 적이 있다.
# 실행 8초 만에 80개를 통째로 놓쳤고, 로그에는 파이썬 스택만 남았다.
with tempfile.TemporaryDirectory() as tmp:
    cache = tf._Cache(_Path(tmp) / "c.jsonl")

    class _Resp:
        @staticmethod
        def json():
            return {"response": {"result": {"items": [
                {"title": "서시흥영업소", "point": {"x": "126.79", "y": "37.38"}},
                {"title": "서시흥나들목", "point": {"x": "126.80", "y": "37.39"}},
            ]}}}

    # 이름 검색은 재시도 없는 get_once 를 쓴다 (없는 이름은 다시 물어도 없다).
    real_get = tf.get_once
    tf.get_once = lambda *a, **k: _Resp()
    try:
        row = tf.search_place("서시흥영업소", cache)
        check(row is not None and abs(row["lat"] - 37.38) < 1e-6,
              f"검색 결과에서 좌표를 읽는다 ({row})")
        lines = (_Path(tmp) / "c.jsonl").read_text(encoding="utf-8").strip().splitlines()
        check(len(lines) == 1, "캐시에 한 줄이 적힌다")
        check(_json.loads(lines[0])["title"] == "서시흥영업소", "캐시가 다시 읽힌다")
        # 두 번째 호출은 그물을 다시 던지지 않아야 한다
        tf.get_once = lambda *a, **k: (_ for _ in ()).throw(AssertionError("캐시를 안 썼습니다"))
        again = tf.search_place("서시흥영업소", cache)
        check(again is not None, "두 번째 호출은 캐시로 답한다")

        # 호출이 실패한 것은 캐시하지 않아야 한다. 키가 없거나 중계기가 잠깐
        # 죽은 것을 '그런 곳은 없다' 로 굳히면 고친 뒤에도 영원히 못 찾는다.
        before = len((_Path(tmp) / "c.jsonl").read_text(encoding="utf-8").strip().splitlines())
        tf.get_once = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("중계기 죽음"))
        check(tf.search_place("없는영업소", cache) is None, "호출 실패는 None 을 준다")
        after = len((_Path(tmp) / "c.jsonl").read_text(encoding="utf-8").strip().splitlines())
        check(before == after, f"호출 실패는 캐시에 남기지 않는다 ({before} → {after})")
    finally:
        tf.get_once = real_get

# 판정: 억지로 채우지 않는다
known = [(37.3800, 126.7900)]
good = {"lat": 37.5, "lon": 127.0, "title": "서시흥영업소"}
check(tf._accept("서시흥", good, [])[0], "이름이 맞고 범위 안이면 받는다")
check(not tf._accept("서시흥", {"lat": 51.5, "lon": -0.1, "title": "서시흥영업소"}, [])[0],
      "한반도 밖 좌표는 버린다")
check(not tf._accept("서시흥", {"lat": 37.5, "lon": 127.0, "title": "행복한주유소"}, [])[0],
      "이름이 다르면 버린다")
check(not tf._accept("서시흥", {"lat": 37.3801, "lon": 126.7901, "title": "서시흥영업소"},
                     known)[0],
      "기존 영업소와 200m 안이면 같은 곳으로 보고 버린다")
check(tf._core("장안본선") == "장안" and tf._core("기장서JC") == "기장서",
      "본선·JC 접미사를 떼어 어간을 만든다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
