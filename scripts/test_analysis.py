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

# 통제를 넣었을 때 계수가 어떻게 변했는지를 말로 옮기는 부분.
# '줄었습니다' 하나로 처리했다가 계수가 커진 경우에 '-40% 줄었다',
# 부호가 뒤집힌 경우에 '143% 줄었다' 로 찍혔다. 둘 다 헛소리였다.
_say = cross._explain_control
check("28%" in _say(0.333, 0.239) and "줄었" in _say(0.333, 0.239),
      "계수가 줄면 줄었다고 말한다")
check("커졌" in _say(0.071, 0.100) and "억제" in _say(0.071, 0.100),
      "계수가 커지면 '커졌다' 로 말한다 (억제 효과)")
check("뒤집" in _say(-0.405, 0.174), "부호가 뒤집히면 그렇게 말한다")
check("절반" in _say(0.40, 0.05), "절반 넘게 줄면 입지 탓임을 밝힌다")
check("줄었" not in _say(0.071, 0.100) and "줄었" not in _say(-0.405, 0.174),
      "커지거나 뒤집힌 경우에 '줄었다' 고 말하지 않는다")

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
        raised = False
        try:
            tf.search_place("없는영업소", cache)
        except tf.CallFailed:
            raised = True
        check(raised, "호출 실패는 CallFailed 로 알린다 ('없더라' 와 구분)")
        after = len((_Path(tmp) / "c.jsonl").read_text(encoding="utf-8").strip().splitlines())
        check(before == after, f"호출 실패는 캐시에 남기지 않는다 ({before} → {after})")

        # 답은 왔는데 결과가 없는 경우는 예외가 아니라 None 이어야 한다.
        # 이 둘을 뭉뚱그린 탓에, 민자 이름이 장소 색인에 없다는 정상적인
        # 결과로 회로가 끊겨 2초 만에 멈춘 적이 있다.
        class _Empty:
            @staticmethod
            def json():
                return {"response": {"status": "NOT_FOUND", "result": {}}}
        tf.get_once = lambda *a, **k: _Empty()
        check(tf.search_place("있을리없는영업소", cache) is None,
              "'답은 왔는데 없더라' 는 None 이지 예외가 아니다")
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

# ────────────────────────────────────────────────────────────────
print("\n5. 중계기 허용목록과 클라이언트 목록이 어긋나지 않는가")

import re as _re                                  # noqa: E402

_relay = (ROOT / "api" / "relay.js").read_text(encoding="utf-8")
_allow = set(_re.findall(r'"([a-z0-9.\-]+\.(?:kr|com|go\.kr))":\s*\{', _relay))
_http = (ROOT / "src" / "redt" / "collect" / "http.py").read_text(encoding="utf-8")
_block = _http.split("RELAYED_HOSTS = {")[1].split("}")[0]
_client = set(_re.findall(r'"([^"]+)"', _block))

# 한쪽에만 있으면 호출이 미국 러너에서 직접 나가 지오블록에 막힌다.
# 그러면 '중계기가 그 호스트를 막고 있다' 로 오해하게 된다. 실제로
# api.odcloud.kr 이 중계기에는 있는데 클라이언트에 없었다.
check(not (_allow - _client),
      f"중계기에만 있는 호스트가 없다 ({sorted(_allow - _client)})")
check(not (_client - _allow),
      f"클라이언트에만 있는 호스트가 없다 ({sorted(_client - _allow)})")

# ────────────────────────────────────────────────────────────────
print("\n6. 거리 밴드 설정 — 영향범위 5km, 대조 밴드 존재")

import yaml as _yaml                              # noqa: E402

_cfg = _yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
_bands = [tuple(b) for b in _cfg["spatial"]["bands"]]
_far = max(hi for _, hi in _bands)
_influence = [b for b in _bands if b[1] <= 5]
check(max(hi for _, hi in _influence) == 5,
      f"영향범위 최대가 5km 다 ({_influence})")
check(len(_bands) > len(_influence),
      "영향범위 바깥에 대조 밴드가 하나 이상 남아 있다"
      " — 없으면 계수를 IC 효과라고 부를 근거가 사라진다")
check(_cfg["spatial"]["max_link_km"] == _far,
      f"max_link_km({_cfg['spatial']['max_link_km']}) 가 가장 먼 밴드({_far})와 같다"
      " — 크면 어느 밴드에도 안 들어가는 연결을 만들어 버린다")
check(_cfg["spatial"]["primary_band"] in [f"{lo:g}-{hi:g}" for lo, hi in _bands],
      f"primary_band({_cfg['spatial']['primary_band']}) 가 실제 밴드 목록에 있다")

# ────────────────────────────────────────────────────────────────
print("\n7. 추이 비교가 읽을 chart.json")

_chart = ROOT / "public" / "app" / "data" / "chart.json"
if not _chart.is_file():
    print("  건너뜀 — chart.json 이 아직 없습니다 (export-web 실행 전)")
else:
    _c = json.loads(_chart.read_text(encoding="utf-8"))
    check(isinstance(_c.get("rows"), dict) and len(_c["rows"]) > 0,
          f"영업소 {len(_c.get('rows', {}))}개")
    _inf = _c.get("influence_bands", [])
    check(_inf and all(float(b.split("-")[1]) <= 5 for b in _inf),
          f"영향범위 밴드가 5km 이하다 ({_inf})")

    # 계열마다 관측 연도가 최소 기준을 넘어야 한다. 점 두 개를 선으로 이으면
    # 잡음이 추세처럼 보인다.
    _minyr = _c.get("min_years", 3)
    _thin = []
    for tid, row in _c["rows"].items():
        for group, series in row.items():
            for name, pts in series.items():
                if len(pts) < _minyr:
                    _thin.append(f"{tid}/{group}/{name}({len(pts)}년)")
    check(not _thin, f"관측 {_minyr}년 미만인 계열이 없다 ({_thin[:3]})")

    _neg = [f"{t}/{g}/{n}" for t, row in _c["rows"].items()
            for g, ser in row.items() for n, pts in ser.items()
            for v in pts.values() if v is not None and v <= 0]
    check(not _neg, f"0 이하 단가가 없다 ({_neg[:3]})")

    _lp = _c.get("landprice", {})
    check("available" in _lp, "공시지가 칸이 있다/없다를 명시한다")
    if not _lp.get("available"):
        check(bool(_lp.get("reason")),
              "공시지가가 없으면 왜 없는지 적는다 — 선이 안 보이는 것과 다른 말이다")

# ────────────────────────────────────────────────────────────────
print("\n8. 세 가설 판정 — 답을 아는 자료로 판정이 제대로 갈리는가")

from redt.analyze import hypotheses as H       # noqa: E402

rng2 = np.random.default_rng(11)


def _panel(effect_by_band, n_tg=40, years=(2019, 2020, 2021, 2022, 2023)):
    """밴드별로 심어둔 탄력성을 갖는 패널을 만든다."""
    rows = []
    for i in range(n_tg):
        tg = f"T{i:03d}"
        sig = f"S{i % 6:02d}"
        for band, beta in effect_by_band.items():
            lnp = 12.0
            for y in years:
                dv = rng2.normal(0.05, 0.10)          # 교통량 변화
                lnp += beta * dv + rng2.normal(0, 0.004)
                rows.append({"tollgate_id": tg, "year": y, "band": band,
                             "kind": "land", "sigungu_cd": sig,
                             "price_index": lnp, "n_trades": 20,
                             "d_ln_volume_total_lag1": dv})
    df = pd.DataFrame(rows).sort_values(["tollgate_id", "band", "year"])
    df["d_ln_price"] = df.groupby(["tollgate_id", "band", "kind"])["price_index"].diff()
    return df.dropna(subset=["d_ln_price"])


# (가) 영향범위에만 효과, 위약은 0 → 지지
good = _panel({"0-1": 0.6, "1-3": 0.5, "3-5": 0.3, "5-10": 0.0})
t = H.h2(good, "volume_total", [])
v, why = H.judge_h2(t)
check(v == H.Verdict.SUPPORT, f"영향범위만 효과가 있으면 지지 ({v} — {why[:60]})")

# (나) 위약에서도 똑같이 크면 → 교란. 이게 이 검사의 핵심이다.
#      위약을 안 보면 (가)와 (나)가 똑같아 보인다.
bad = _panel({"0-1": 0.6, "1-3": 0.5, "3-5": 0.5, "5-10": 0.6})
v2, why2 = H.judge_h2(H.h2(bad, "volume_total", []))
check(v2 == H.Verdict.CONFOUNDED,
      f"위약 밴드에서도 유의하면 교란으로 판정 ({v2} — {why2[:60]})")

# (다) 아무 효과도 없으면 '기각' 이 아니라 '아직 모름'
flat = _panel({"0-1": 0.0, "1-3": 0.0, "3-5": 0.0, "5-10": 0.0})
v3, why3 = H.judge_h2(H.h2(flat, "volume_total", []))
check(v3 == H.Verdict.UNKNOWN, f"효과가 없으면 '아직 모름' ({v3})")
check("효과가 없다는 뜻이 아니라" in why3,
      "'효과 없음' 과 '판정 못함' 을 구분해 말한다")

# (라) 위약을 추정 못 하면 판정 자체를 보류한다
noplacebo = _panel({"0-1": 0.6, "1-3": 0.5, "3-5": 0.3})
v4, why4 = H.judge_h2(H.h2(noplacebo, "volume_total", []))
check(v4 == H.Verdict.UNKNOWN, f"위약 밴드가 없으면 보류 ({v4})")
check("위약" in why4, "보류 이유가 위약임을 밝힌다")

# (마) 유의한 음수는 '아직 모름' 이 아니라 '기각' 이다.
#      실제 실행에서 화물 0-1km β=-0.78(p=0.045)이 나왔는데, 옛 코드가
#      절댓값으로 정점을 골라 "✅ IC 효과로 해석 가능" 이라고 찍었다.
#      그 값의 뜻은 '화물이 늘수록 그 땅값이 내려간다' 로 정반대다.
negp = _panel({"0-1": -0.6, "1-3": -0.2, "3-5": -0.1, "5-10": 0.0})
v9, why9 = H.judge_h2(H.h2(negp, "volume_total", []))
check(v9 == H.Verdict.REJECT, f"유의한 음수는 기각으로 판정 ({v9} — {why9[:50]})")
check("음수" in why9 and "반대" in why9, "반대 방향임을 말로 밝힌다")

# correlation.interpret 도 같은 함정을 밟지 않아야 한다
from redt.analyze import correlation as C          # noqa: E402
_el = pd.DataFrame([
    {"band": "0-1", "kind": "land", "n": 100, "beta": -0.78, "se": 0.39, "p": 0.045},
    {"band": "1-3", "kind": "land", "n": 100, "beta": -0.40, "se": 0.42, "p": 0.34},
    {"band": "5-10", "kind": "land", "n": 100, "beta": 0.11, "se": 0.15, "p": 0.48},
])
_txt = C.interpret(_el)
check("✅" not in _txt, f"음수 정점에 초록 체크를 붙이지 않는다 ({_txt[:70]})")
check("반대 방향" in _txt, "가설과 반대 방향임을 밝힌다")

# 위약이 유의한 양수면 크기 비교로 통과시키지 않는다
_el2 = pd.DataFrame([
    {"band": "0-1", "kind": "land", "n": 100, "beta": 0.90, "se": 0.20, "p": 0.001},
    {"band": "5-10", "kind": "land", "n": 100, "beta": 0.50, "se": 0.15, "p": 0.001},
])
_txt2 = C.interpret(_el2)
check("✅" not in _txt2 and "지역 효과" in _txt2,
      f"위약이 유의하면 크기가 커도 통과시키지 않는다 ({_txt2[:70]})")

# 정상적인 경우에는 여전히 통과해야 한다 (검사가 전부를 막아버리면 안 된다)
_el3 = pd.DataFrame([
    {"band": "0-1", "kind": "land", "n": 100, "beta": 0.90, "se": 0.20, "p": 0.001},
    {"band": "5-10", "kind": "land", "n": 100, "beta": 0.05, "se": 0.15, "p": 0.70},
])
check("✅" in C.interpret(_el3), "영향범위만 유의한 양수면 통과시킨다")

# H1 — 평행추세가 깨지면 계수가 커도 교란
t1 = pd.DataFrame([{"모형": "통제 전", "n": 500, "영업소": 20, "beta": 0.20,
                    "se": 0.05, "p": 0.0001, "비고": ""}])
v5, _ = H.judge_h1(t1, pre_trend_ok=False)
check(v5 == H.Verdict.CONFOUNDED, f"사전추세가 깨지면 교란 ({v5})")
v6, why6 = H.judge_h1(t1, pre_trend_ok=True)
check(v6 == H.Verdict.SUPPORT, f"사전추세가 버티고 유의하면 지지 ({v6})")
check("%" in why6, "지지 근거에 실제 상승률을 적는다")
t1b = t1.assign(p=0.6, se=0.3)
v7, why7 = H.judge_h1(t1b, pre_trend_ok=True)
check(v7 == H.Verdict.UNKNOWN, f"유의하지 않으면 '아직 모름' ({v7})")
check("0 을 품고" in why7, "구간이 0 을 품는다는 것을 밝힌다")

# H3 — 자료가 없으면, 그것이 H1·H2 해석의 한계임을 말해야 한다
v8, why8 = H.judge_h3(pd.DataFrame(columns=["변수", "n", "영업소", "beta", "se", "p"]))
check(v8 == H.Verdict.UNKNOWN, "H3 자료가 없으면 '아직 모름'")
check("교란" in why8 or "IC 효과" in why8,
      "H3 가 없으면 H1·H2 도 IC 효과로 못 부른다는 것을 밝힌다")

# 통제 붙이기 — 결측이 많은 통제는 스스로 빼야 한다
_reg = pd.DataFrame([{"sigungu_cd": "S00", "year": y, "metric": "population",
                      "value": 100000 * (1.02 ** i)}
                     for i, y in enumerate((2019, 2020, 2021, 2022, 2023))])
_with, _usable = H.attach_controls(good, _reg, None)
check("d_ln_population" not in _usable,
      "한 시군구만 있는 통제는 결측이 많아 스스로 빠진다")

# ────────────────────────────────────────────────────────────────
print("\n9. 교통량 원본의 손상된 행을 걸러내는가")

import importlib.util as _ilu                      # noqa: E402

_spec = _ilu.spec_from_file_location("cnv", ROOT / "scripts" / "convert_tcs_daily.py")
_cnv = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_cnv)

# 남고창(567) 2015-11-06 에 실제로 있던 모양. 같은 날 정상 행은 1종이 571·1414·610
# 인데 한 행만 562,715 였다. 4종 하루 80만 대는 전국 총량보다 많다.
_days = pd.date_range("2015-11-01", periods=30)
_rows = []
for d in _days:
    for lane in range(3):                          # 정상 행: 하루 총 ~4,100
        _rows.append({"집계일자": d, "영업소코드": 567,
                      **{f"{i}종교통량": v for i, v in
                         zip(range(1, 7), [1200, 60, 40, 30, 20, 20])}})
_rows.append({"집계일자": pd.Timestamp("2015-11-06"), "영업소코드": 567,
              **{f"{i}종교통량": v for i, v in
                 zip(range(1, 7), [562715, 56339, 130749, 804480, 578379, 216358])}})
# 규모가 다른 영업소도 함께 둔다 — 절대값으로 자르면 큰 영업소가 통째로 날아간다
for d in _days:
    _rows.append({"집계일자": d, "영업소코드": 1,
                  **{f"{i}종교통량": v for i, v in
                     zip(range(1, 7), [200000, 8000, 6000, 4000, 3000, 9000])}})
_raw = pd.DataFrame(_rows)
_clean = _cnv.drop_spikes(_raw, "테스트")

check(len(_clean) == len(_raw) - 1, f"손상된 행 하나만 버린다 ({len(_raw)} → {len(_clean)})")
check(int(_clean[_clean["영업소코드"] == 1].shape[0]) == 30,
      "규모가 큰 영업소는 절대값이 커도 안 버린다")
_kept = _clean[(_clean["영업소코드"] == 567)]
check(_kept["1종교통량"].max() == 1200, "남은 값에 이상치가 없다")

# 명절 수준(평소의 3배)은 실제 교통이므로 버리면 안 된다
_holiday = _raw.copy()
_mask = (_holiday["영업소코드"] == 1) & (_holiday["집계일자"] == _days[10])
for i in range(1, 7):
    _holiday.loc[_mask, f"{i}종교통량"] *= 3
check(len(_cnv.drop_spikes(_holiday, "명절")) == len(_holiday) - 1,
      "평소의 3배(명절 수준)는 버리지 않는다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
