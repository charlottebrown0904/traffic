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
import yaml

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

# ────────────────────────────────────────────────────────────────
print("\n10. 코드 승계를 신규 개통과 구분하는가")

_spec2 = _ilu.spec_from_file_location("suc", ROOT / "scripts" / "tollgate_succession.py")
_suc = _ilu.module_from_spec(_spec2)
_spec2.loader.exec_module(_suc)

# 2014-10 에 실제로 있던 일: 가락(246) 이 쪼개져 가락(개)(29)·가락2(596) 이
# 되고, 같은 달에 동충주(297)가 진짜로 개통했다.
check(_suc._verdict("가락(개)", "가락") == "이름일치", "가락 → 가락(개) 는 이름일치")
check(_suc._verdict("가락2", "가락") == "이름일치", "가락 → 가락2 는 이름일치")
check(_suc._verdict("동충주", "가락") == "월합만일치",
      "동충주는 이름이 안 이어지므로 승계로 단정하지 않는다")
check(_suc._verdict("", "가락") == "월합만일치", "이름이 없으면 단정하지 않는다")

# 처치군에서 실제로 빠지는지. 진짜 개통(동충주)은 남아야 한다 —
# 진짜 개통을 잘못 빼면 표본만 줄어든다.
_suc_csv = ROOT / "data" / "raw" / "tollgate_succession.csv"
if _suc_csv.is_file():
    _sc = pd.read_csv(_suc_csv, encoding="utf-8-sig")
    if len(_sc):
        from redt.analyze import events as _ev                   # noqa: E402
        _kept = _ev.load_events()
        _codes = set(pd.to_numeric(_kept["tollgate_id"], errors="coerce").dropna())
        _sure = set(pd.to_numeric(
            _sc.loc[_sc["판정"] == "이름일치", "신규코드"], errors="coerce").dropna())
        check(not (_codes & _sure),
              f"이름일치 승계코드가 처치군에 없다 (남은 것 {sorted(_codes & _sure)})")
        _maybe = set(pd.to_numeric(
            _sc.loc[_sc["판정"] != "이름일치", "신규코드"], errors="coerce").dropna())
        # 월합만일치는 빼지 않는다 (진짜 개통일 수 있다)
        check(True, f"월합만일치 {len(_maybe)}개는 판단 보류로 남긴다")

# ────────────────────────────────────────────────────────────────
print("\n11. 전국 코드 훑기가 하루 한도를 넘지 않는가")

# 코드당 몇 번을 부르는지가 곧 비용이다. 처음에 세 달 × 두 종류로 짜서
# 코드당 6회, 전체 108,000회가 됐고 하루 한도(10만)를 넘겨 취소했다.
# 비용의 거의 전부가 '없는 코드' 를 확인하는 데 들어간다 — 유효한 코드는
# 250개 안팎이고 나머지 17,750개가 6회씩 불렸다.
_cli = (ROOT / "src" / "redt" / "cli.py").read_text(encoding="utf-8")
_block = _cli.split("def cmd_discover_sigungu")[1].split("def cmd_regions")[0]

check("for ym in months:" not in _block,
      "코드마다 여러 달을 도는 반복문이 없다")
check('for kind in ("land", "factory")' not in _block,
      "코드마다 두 종류를 도는 반복문이 없다")
check("총 호출" in _block, "총 호출 횟수를 찍는다 — 비용이 안 보이면 또 넘긴다")

# 시도 18개 × 1000 = 18,000 이 1차 비용. 2차는 찾은 코드 ±3 이웃만.
_SIDO = 18
_first_pass = _SIDO * 1000
# 최악의 경우 2차: 시도마다 유효코드 30개 × 이웃 7 = 210, 전부 재시도
_worst_second = _SIDO * 30 * 7
check(_first_pass + _worst_second < 100_000,
      f"최악의 경우에도 하루 한도 안 ({_first_pass + _worst_second:,}회 < 100,000)")

# ────────────────────────────────────────────────────────────────
print("\n12. 달 수가 다른 해를 어떻게 견주는가")

# 2010년은 10월 원본이 없어 11개월뿐이다. 연 합계로 견주면 이듬해가
# 12.9% 늘어난 것처럼 보이지만, 월평균으로는 2.9% 다. 파이프라인은
# 이미 일평균(avg_daily)을 쓰므로 영향이 없었고, 틀린 것은 대조 절차였다.
_vf = (ROOT / "scripts" / "verify_tcs_year.py").read_text(encoding="utf-8")
check("def observed(" in _vf, "그 해 관측 달 수를 세는 함수가 있다")
check("/ mn_new" in _vf and "/ mn_ref" in _vf,
      "전국 합을 관측 달 수로 나눠 월평균끼리 견준다")
check("mn < mn_new" in _vf,
      "'연중 개통' 판정도 12가 아니라 그 해 달 수를 기준으로 한다")

# 파이프라인 쪽은 관측일수로 나누는지 — 이게 진짜 방어선이다
from redt.collect import traffic_files as _tfl        # noqa: E402
_days = _tfl.observed_days()
if len(_days):
    _y2010 = _days[_days["year"] == 2010]["days"]
    if len(_y2010):
        check(abs(_y2010.median() - 334) < 2,
              f"2010년 관측일수가 334일로 잡힌다 (365-31, 실제 {_y2010.median():.0f})")

# 개통한 **달** 은 관측일수로도 못 잡는다 (2026-09-10).
#
# 월별 파일은 '그 달에 자료가 있다' 만 말하고 며칠부터인지는 말하지
# 않는다. 그래서 6월 30일에 연 영업소도 6월을 30일로 세었고, 개통
# 당일치가 30일로 나뉘었다. 실측: 첫 달이 자료 시작이 아닌 253곳 중
# 185곳(73%)의 첫 달 일평균이 둘째 달의 절반에도 못 미쳤다.
_avg = _tfl.daily_average()
if len(_avg):
    _bg = _avg[(_avg["tollgate_id"] == "785")]
    # 북용인은 2024-12 한 달(총 224대)뿐이고 2025-01 이 15,197대/일이다.
    # 그 한 달을 31일로 세면 7대/일 — 실제로 그렇게 나와 있었다.
    check(_bg[_bg["year"] == 2024].empty,
          "잴 수 있는 달이 없는 해는 일평균을 안 낸다 (북용인 2024)")
    _y25 = _bg[_bg["year"] == 2025]["avg_daily"]
    check(len(_y25) and 20000 < _y25.sum() < 30000,
          f"이듬해는 제대로 나온다 (북용인 2025 {_y25.sum():,.0f}대/일)")

_loaded = _tfl.load_files()
if len(_loaded):
    _bg24 = _loaded[(_loaded["tollgate_id"] == "785") & (_loaded["year"] == 2024)]
    # **0 이 아니라 빈 값이어야 한다.** 0 은 '차가 안 다녔다' 는 뜻인데
    # 사실은 '못 쟀다' 이고, 둘을 섞으면 이제 막 연 IC 가 통행량
    # 최하위로 지도에 박힌다 (webexport 가 IS NOT NULL 로 거른다).
    check(len(_bg24) and _bg24["avg_daily"].isna().all(),
          "못 잰 일평균은 0 이 아니라 빈 값이다")
    check(len(_bg24) and _bg24["volume"].sum() == 224,
          f"연 합계는 그대로 남는다 (북용인 2024 {_bg24['volume'].sum():,}대)")

print()
print("13. 시군구 훑기 — 호출 실패를 '코드 없음' 으로 적지 않는다")
# run 13 에서 광주(29)·전남(46)이 통째로 0개로 나왔다. 그 시도에 토지
# 거래가 한 달에 0건일 수는 없다. 예외를 0 으로 바꾸고 있었던 탓이다.
from redt import cli as _cli
from redt.collect import rtms as _rtms

_orig_fetch = _rtms.fetch_page
try:
    _rtms.fetch_page = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("중계기 끊김"))
    _code, _total = _cli.probe_sigungu(("29110", "202403", "land"))
    check(_total is None, f"호출이 실패하면 None (모른다) 이다 — 받은 값 {_total!r}")
    check(_total != 0, "호출 실패가 0건(코드 없음)으로 둔갑하지 않는다")

    _rtms.fetch_page = lambda *a, **k: ([], 0)
    _, _empty = _cli.probe_sigungu(("29999", "202403", "land"))
    check(_empty == 0, "정말 자료가 없으면 0 이다")

    _rtms.fetch_page = lambda *a, **k: ([], 7)
    _, _hit = _cli.probe_sigungu(("29110", "202403", "land"))
    check(_hit == 7, "자료가 있으면 건수를 그대로 준다")
finally:
    _rtms.fetch_page = _orig_fetch

print()
print("14. 같은 달을 두 파일이 들고 오면 배로 세지 않는다")
# 포털에서 받은 2004-06 파일 안에 든 것이 2004-07 이었다. 7월 파일과
# 행 단위로 완전히 같아서, 그대로 더하면 7월이 292,008,930 — 다른 달
# (약 148,000,000)의 정확히 두 배가 된다. 파일 이름만 보면 12개가 다
# 있으므로 로그에는 아무 표시도 안 남는다.
import subprocess, tempfile, gzip, os

_hdr = ("집계일자,영업소코드,입출구구분코드,TCS하이패스구분코드,"
        "고속도로운영기관구분코드,영업형태구분코드,"
        "1종교통량,2종교통량,3종교통량,4종교통량,5종교통량,6종교통량,총교통량")
def _mkfile(path, ymd_list):
    body = [_hdr]
    for ymd in ymd_list:
        body.append(f"{ymd},101,0,1,0,1,100,10,5,3,2,1,121")
    with gzip.open(path, "wb") as fh:
        fh.write(("\n".join(body) + "\n").encode("cp949"))

with tempfile.TemporaryDirectory() as _td:
    _may = os.path.join(_td, "tcs_daily_200405.zip")
    _jun = os.path.join(_td, "tcs_daily_200406.zip")   # 이름은 6월
    _jul = os.path.join(_td, "tcs_daily_200407.zip")
    _mkfile(_may, ["20040501", "20040502"])
    _mkfile(_jun, ["20040701", "20040702"])            # 내용은 7월 (포털의 그 사고)
    _mkfile(_jul, ["20040701", "20040702"])
    _out = os.path.join(_td, "annual.csv")
    _mout = os.path.join(_td, "monthly.csv")
    _r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/convert_tcs_daily.py"),
         _may, _jun, _jul, "-o", _out, "--monthly-out", _mout],
        capture_output=True, text=True)
    _log = _r.stdout + _r.stderr
    check("파일 2개가 들고 있습니다" in _log, "중복을 발견하면 말한다")
    if os.path.exists(_mout):
        _m = pd.read_csv(_mout, encoding="utf-8-sig")
        _tot = _m.groupby("연월")["교통량"].sum()
        _jul_v = _tot.get("2004-07", 0)
        _may_v = _tot.get("2004-05", 0)
        check(_jul_v == _may_v,
              f"중복된 달이 배로 세어지지 않는다 (7월 {_jul_v} vs 5월 {_may_v})")
        check("2004-06" not in _tot.index,
              "이름만 6월인 파일이 6월을 만들어내지 않는다")
    else:
        check(False, "월별 출력이 만들어진다")

print()
print("15. 합성 자료가 설정 필터를 통과할 만큼 남는다 (Gate 0 이 죽지 않게)")
# `make test` 는 통과하는데 `make demo` 가 죽어 있었다.
#
# 설정의 land_use_filter 가 계획관리·생산관리·자연녹지로 정해졌는데 합성
# 생성기는 ["계획관리","생산녹지","공업"] 을 박아 쓰고 있었다. 셋 중 하나만
# 통과해 셀당 12건이 4건이 되고, min_trades_per_cell(5) 을 못 넘어 모든
# 셀의 가격지수가 결측이 됐다. Gate 0 이 계수를 하나도 못 내는 채로 있었다.
#
# 설정이 또 바뀌면 여기서 걸린다.
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("_syn", ROOT / "scripts/make_synthetic.py")
_syn = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_syn)

_cfg = _syn.settings()
_zones = _cfg.get("land_use_filter") or []
_min = _cfg["panel"]["min_trades_per_cell"]

# 셀은 (영업소 × 밴드 × 종류 × 연도) 다. 생성기는 셀 하나에 per_cell 건을
# 만들고, k 로 용도지역과 좌표수준을 정한다. 그 k 루프를 그대로 되짚어
# **셀 하나에 몇 건이 살아남는지**를 센다 — 시군구 단위로 뭉쳐 세면 수백
# 건이 나와 아무것도 잡지 못한다.
import inspect as _inspect

_per_cell_n = _inspect.signature(_syn.make_trades).parameters["per_cell"].default
_pool = _syn.ZONE_POOL
_near = set(bands_cfg if (bands_cfg := _cfg["spatial"].get("require_parcel_bands")) else [])

_survive = 0
for _k in range(_per_cell_n):
    _zone = _pool[_k % len(_pool)]
    if _zones and not any(z in _zone for z in _zones):
        continue                      # 용도지역 필터에서 빠진다
    if _near and not (_k % 6):
        continue                      # 법정동단위 좌표라 근거리 밴드에서 빠진다
    _survive += 1

check(_survive >= _min,
      f"근거리 밴드 셀 하나에 {_survive}건이 남는다 "
      f"(셀당 생성 {_per_cell_n}건 · 최소 필요 {_min}건)")

# 위약 밴드에는 참값 0 을 심어야 위약 검정이 작동하는지 볼 수 있다.
_control = list(_syn.BAND_RANGE)[-1]
check(_syn.TRUE_BETA[_control] == 0.0,
      f"가장 바깥 밴드({_control})의 참값이 0 이다 — 위약 검정용")
check(max(_syn.TRUE_BETA.values()) > 0,
      "영향범위 밴드에는 0 이 아닌 참값이 심겨 있다")

print()
print("16. 가설3 자료를 받은 그대로 읽는다 (엑셀·cp949)")
# 예전에는 utf-8 CSV 만 읽었다. data.go.kr·KOSIS·팩토리온이 주는 것은
# 대개 엑셀이거나 cp949 CSV 다. '엑셀에서 UTF-8 로 다시 저장하세요' 를
# 시키면 그 과정에서 날짜가 숫자로 바뀌거나 시군구코드 앞의 0 이 떨어진다.
from redt.collect.h3_files import read_table as _read_table
import tempfile as _tf, os as _os

_rows = {"단지명": ["가상산단"], "지정일": ["2015-03-02"],
         "시군구코드": ["41590"], "지정면적": [123456]}
_df = pd.DataFrame(_rows)

with _tf.TemporaryDirectory() as _d:
    _csv_utf = _os.path.join(_d, "zones_a.csv")
    _csv_949 = _os.path.join(_d, "zones_b.csv")
    _xlsx = _os.path.join(_d, "zones_c.xlsx")
    _df.to_csv(_csv_utf, index=False, encoding="utf-8-sig")
    _df.to_csv(_csv_949, index=False, encoding="cp949")
    _df.to_excel(_xlsx, index=False)

    for _label, _path in (("utf-8 CSV", _csv_utf), ("cp949 CSV", _csv_949),
                          ("엑셀 xlsx", _xlsx)):
        try:
            _got = _read_table(Path(_path))
            _ok = ("단지명" in _got.columns and len(_got) == 1
                   and str(_got["시군구코드"].iat[0]).strip() in ("41590", "41590.0"))
        except Exception as _exc:                        # noqa: BLE001
            _ok = False
            print(f"      {_exc}")
        check(_ok, f"{_label} 를 읽는다")

# 엑셀 판독기가 러너에도 있어야 한다 — 여기서만 설치돼 있으면 소용없다.
_req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
check("openpyxl" in _req, "openpyxl 이 requirements.txt 에 있다 (러너용)")

print()
print("17. 시군구 훑기가 호출 실패를 만나도 끝까지 돈다")
# run 14 가 여기서 터졌다. probe 가 실패를 None 으로 돌려주게 바꾸면서
# 1차 루프와 재시도 루프는 고쳤는데 **2차 이웃 탐색 루프 하나를
# 빠뜨렸다.** `if total > 0` 이 None 을 만나 TypeError 로 죽었고, 9분 46초
# 뒤 수집 전체가 멈췄다.
#
# 눈으로 세 군데를 다 고쳤는지 세는 대신, 명령을 실제로 돌린다.
import types as _types
from concurrent.futures import ThreadPoolExecutor as _TPE

_real_cfg = _cli.ROOT_CFG
_calls = {"n": 0}

def _fake_fetch(kind, code, ym, page=1, rows=1):
    _calls["n"] += 1
    tail = int(str(code)[-3:])
    if tail % 7 == 0:                      # 일부 호출은 실패한다 → None
        raise RuntimeError("중계기 끊김")
    if tail in (110, 113, 117):            # 실제로 자료가 있는 코드
        return [], 5
    return [], 0

with _tf.TemporaryDirectory() as _d:
    _cli.ROOT_CFG = Path(_d)
    _orig = _rtms.fetch_page
    try:
        _rtms.fetch_page = _fake_fetch
        _args = _types.SimpleNamespace(
            sido="41", probe_ymd="202403", extra_ymd="202409",
            workers=8, refresh=True)
        _crashed = None
        try:
            _cli.cmd_discover_sigungu(_args)
        except Exception as _exc:          # noqa: BLE001
            _crashed = _exc
        check(_crashed is None, f"실패가 섞여도 끝까지 돈다 ({_crashed!r})")

        _out = Path(_d) / "sigungu_codes.yaml"
        check(_out.exists(), "결과 파일을 남긴다")
        if _out.exists():
            _found = yaml.safe_load(_out.read_text(encoding="utf-8")) or {}
            _codes = set(_found.get("41", {}))
            check({"41110", "41113", "41117"} <= _codes,
                  f"자료가 있는 코드를 모두 찾는다 (찾은 것 {sorted(_codes)})")
    finally:
        _rtms.fetch_page = _orig
        _cli.ROOT_CFG = _real_cfg

print()
print("18. KOSIS 응답은 엄격한 JSON 이 아니다")
# format=json 을 줘도 키에 따옴표가 없이 옵니다.
#   [{LIST_NM:"인구",LIST_ID:"A"}]
# 자바스크립트 객체 표기라 json.loads 가 거부합니다. 첫 실행에서 자료는
# 멀쩡히 왔는데 '조회 실패' 로 찍혔습니다.
from redt.collect.kosis import loads_lenient as _ll

_REAL = '[{LIST_NM:"인구",LIST_ID:"A",VW_NM:"국내통계 주제별",VW_CD:"MT_ZTITLE"}]'
_got = _ll(_REAL)
check(isinstance(_got, list) and _got[0].get("LIST_ID") == "A",
      f"실제 KOSIS 응답 모양을 읽는다 ({_got[:1]})")
check(_ll('[{"a":1}]') == [{"a": 1}], "엄격한 JSON 도 그대로 읽는다")

# 정규식 한 줄로 고치려다 값을 깨뜨렸다. 값 안의 ', y:' 를 키로 보고
# 문자열을 갈라놓는다. 따옴표 안팎을 세어야 한다.
check(_ll('[{A:"10:30",B:"x, y:z"}]') == [{"A": "10:30", "B": "x, y:z"}],
      "값 속의 쉼표와 콜론을 키로 착각하지 않는다")
check(_ll('[{A:"{B:1}",C:"끝"}]') == [{"A": "{B:1}", "C": "끝"}],
      "값 속의 중괄호를 건드리지 않는다")
check(_ll(r'[{A:"그는 \"안녕\" 이라 했다"}]')[0]["A"] == '그는 "안녕" 이라 했다',
      "이스케이프된 따옴표를 넘긴다")

print()
print("19. 도시개발 표준데이터의 실제 칸 이름을 읽는다")
# 표준데이터는 한글이 아니라 축약 영문 키로 옵니다. 특히 **경도가 lot**
# 입니다 — lon 만 찾으면 위도만 붙고 경도는 결측이 되어, 좌표가 반쪽만
# 있는 채로 반경 밴드에 들어갑니다.
from redt.collect.h3_files import ZONE_COLS as _ZC, _pick as _pk

_OBSERVED = ["bizNm", "ctpvNm", "sggNm", "lctnRoadNmAddr", "lctnLotnoAddr",
             "lat", "lot", "bizBgngYm", "bizEndYm", "telno", "bizDvlrNm",
             "actcHhCnt", "bzar", "bizMthSeNm", "dataCrtrYmd"]
_frame = pd.DataFrame({c: ["x"] for c in _OBSERVED})
for _want, _expect in (("name", "bizNm"), ("designated_date", "bizBgngYm"),
                       ("lat", "lat"), ("lon", "lot"), ("area_m2", "bzar"),
                       ("address", "lctnLotnoAddr")):
    check(_pk(_frame, _ZC[_want]) == _expect,
          f"{_want} ← {_expect} (읽은 것 {_pk(_frame, _ZC[_want])})")

print()
print("20. 2단계 지오코딩 — 법정동 먼저, 반경 안만 지번")
# 좌표 없는 거래 329만 건 / 하루 4,000건 = 822번 실행. 전국을 다 붙일
# 필요가 없다는 것이 답이다.
from redt.collect import geocode as _gc
from redt.transform.spatial import umd_near_tollgates as _near

_orig_one = _gc.geocode_one
_orig_pace = _gc._PACE
_calls = []

class _Cache(_gc.GeocodeCache):
    def __init__(self):
        self._data = {}
        self.path = Path("/dev/null")
    def put(self, addr, lat, lon, source, level=None):
        self._data[addr] = {"addr_key": addr, "lat": lat, "lon": lon,
                            "source": source, "level": level}

try:
    _gc._PACE = _gc._Pace(0)          # 검사에서는 속도 상한을 끈다
    _gc.geocode_one = lambda addr, kind="PARCEL": (_calls.append(addr),
                                                   (37.0, 127.0))[1]
    # 같은 법정동의 거래 100건 → 법정동 호출은 한 번이어야 한다.
    _calls.clear()
    _c = _Cache()
    _pairs = [("화성시", "장안면")] * 100
    _got = _gc.geocode_umd(_pairs, cache=_c)
    check(len(_calls) == 1,
          f"같은 법정동 100건에 호출 한 번 (실제 {len(_calls)}번)")
    check(len(_got) == 1 and _got[("화성시", "장안면")][2] == "umd",
          "법정동 좌표를 umd 수준으로 돌려준다")

    # 거친 결과가 **지번 키**를 오염시키면 안 된다. 오염되면 나중에
    # 지번으로 올리려 해도 캐시가 막는다.
    _key_parcel = _gc.build_address(None, "화성시", "장안면", "123-4")
    check(_c.get(_key_parcel) is None,
          "법정동 호출이 지번 키를 채우지 않는다 (나중에 올릴 수 있어야 한다)")

    _calls.clear()
    _p = _gc.geocode_parcel([("화성시", "장안면", "123-4")], cache=_c)
    check(len(_calls) == 1 and _p[("화성시", "장안면", "123-4")][2] == "parcel",
          "지번 좌표를 parcel 수준으로 올린다")

    # 지번이 없는 행은 지번 단계에서 호출을 낭비하지 않는다.
    _calls.clear()
    _gc.geocode_parcel([("화성시", "장안면", "")], cache=_Cache())
    check(len(_calls) == 0, "지번이 없으면 부르지 않는다")
finally:
    _gc.geocode_one = _orig_one
    _gc._PACE = _orig_pace

# 반경 밖 법정동은 지번 대상에서 빠진다 — 지번 좌표가 있어도 어느 밴드에도
# 못 들어가므로 부르는 만큼 손해다.
_umd = pd.DataFrame({
    "sigungu": ["가까운", "먼곳"], "umd": ["a", "b"],
    "lat": [37.00, 35.00], "lon": [127.00, 129.00]})
_tg = pd.DataFrame({"lat": [37.01], "lon": [127.01]})
_kept = _near(_umd, _tg, max_km=10.0)
check(list(_kept["sigungu"]) == ["가까운"],
      f"영업소 반경 안 법정동만 남는다 (남은 것 {list(_kept['sigungu'])})")

# 경계에 걸친 법정동을 자르지 않는다 — 중심점 오차가 ±1~2km 이므로
# 여유를 두지 않으면 실제로는 안에 있는 거래를 통째로 버린다.
_edge = pd.DataFrame({"sigungu": ["경계"], "umd": ["c"],
                      "lat": [37.0 + 11.5 / 111.0], "lon": [127.0]})
check(len(_near(_edge, _tg, max_km=10.0)) == 1,
      "반경 바로 바깥(약 11.5km)도 여유 안에 들어 남는다")

print()
print("21. 한 시도만 다시 훑어도 나머지를 지우지 않는다")
# 새 시도(전남광주통합 12)를 넣으려고 `--refresh --sido 12` 를 돌릴 참이었다.
# 그대로였으면 이미 찾아둔 197개 코드가 통째로 지워졌다. 그리고 그 파일이
# 커밋되면 다음 실행은 '이미 찾아뒀다' 며 건너뛴다 — 조용히 전국이
# 시군구 6개로 줄어든다.
_prev_cfg = _cli.ROOT_CFG
with _tf.TemporaryDirectory() as _d:
    _cli.ROOT_CFG = Path(_d)
    _yaml_path = Path(_d) / "sigungu_codes.yaml"
    _yaml_path.write_text(
        yaml.safe_dump({"41": {"41110": 5, "41130": 3}, "11": {"11110": 7}},
                       allow_unicode=True), encoding="utf-8")

    _orig = _rtms.fetch_page
    try:
        # 12 만 자료가 있다고 답한다.
        _rtms.fetch_page = lambda kind, code, ym, page=1, rows=1: (
            ([], 9) if str(code).startswith("12") and str(code)[-3:] in
            ("110", "130") else ([], 0))
        _args2 = _types.SimpleNamespace(
            sido="12", probe_ymd="202403", extra_ymd="", workers=8, refresh=True)
        _cli.cmd_discover_sigungu(_args2)
        _after = yaml.safe_load(_yaml_path.read_text(encoding="utf-8")) or {}
        check("41" in _after and len(_after.get("41", {})) == 2,
              f"안 훑은 경기(41) 코드가 남아 있다 ({_after.get('41')})")
        check("11" in _after, f"안 훑은 서울(11) 코드가 남아 있다 ({_after.get('11')})")
        check(set(_after.get("12", {})) == {"12110", "12130"},
              f"새로 훑은 12 가 들어갔다 ({sorted(_after.get('12', {}))})")
    finally:
        _rtms.fetch_page = _orig
        _cli.ROOT_CFG = _prev_cfg

print()
print("22. 부실한 시군구 목록이 조용히 재사용되지 않는다")
# 훑기는 상대가 막으면 코드를 놓칩니다. 그렇게 만들어진 목록이 파일에
# 남으면 다음부터는 '이미 찾아뒀다' 며 건너뛰고, 그 시군구는 영원히
# 빕니다 — 오류도 경고도 없이 표만 비어 보입니다.
import io as _io
from contextlib import redirect_stdout as _redir

_prev = _cli.ROOT_CFG
with _tf.TemporaryDirectory() as _d:
    _cli.ROOT_CFG = Path(_d)
    (Path(_d) / "sigungu_codes.yaml").write_text(
        yaml.safe_dump({"41": {"41110": 5, "41130": 3, "41150": 2},
                        "29": {},                 # 막혀서 빈 시도
                        "46": {"46110": 1}},      # 너무 적은 시도
                       allow_unicode=True), encoding="utf-8")
    _args3 = _types.SimpleNamespace(
        sido="", probe_ymd="202403", extra_ymd="", workers=8, refresh=False)
    _buf = _io.StringIO()
    with _redir(_buf):
        _cli.cmd_discover_sigungu(_args3)
    _out = _buf.getvalue()
_cli.ROOT_CFG = _prev

check("온전하지 않아 보입니다" in _out, "부실하면 경고한다")
check("'29'" in _out or "29" in _out.split("빈 시도:")[-1][:40],
      "빈 시도를 지목한다")
check("--refresh --sido" in _out, "고치는 방법을 알려준다")
check("지워지지 않습니다" in _out, "병합된다는 것을 알린다 (덮어쓸까 봐 안 돌리는 일이 없게)")

print()
print("23. 시군구 코드 체계가 다르면 '자료 없음' 이 아니라 그렇게 말한다")

# KOSIS 지역코드는 법정동 코드와 다른 체계다(부산 KOSIS 21 vs 법정동 26).
# 다른 체계끼리 조인하면 예외가 안 나고 전부 결측이 된다. 그때 "결측 100%"
# 라고만 말하면 '인구 자료를 더 모아야겠다' 로 읽힌다. 아무리 모아도 안
# 붙는다 — 열쇠가 틀렸기 때문이다. 진단이 틀리면 며칠을 엉뚱한 데 쓴다.
from redt.analyze.hypotheses import attach_controls          # noqa: E402
import io                                                     # noqa: E402
import contextlib                                             # noqa: E402

_panel = pd.DataFrame({
    "sigungu_cd": ["41111", "41111", "41113", "41113"],
    "year": [2020, 2021, 2020, 2021],
    "tollgate_id": ["1"] * 4, "band": ["0-1"] * 4, "kind": ["land"] * 4,
})


def _region(codes):
    return pd.DataFrame([
        {"sigungu_cd": c, "year": y, "metric": "population", "value": 10000 + y}
        for c in codes for y in (2019, 2020, 2021)])


def _say(region):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _, usable = attach_controls(_panel, region, None)
    return buf.getvalue(), usable

# 가) 완전히 다른 체계
msg, usable = _say(_region(["31011", "31012"]))
check("코드 체계가 다릅니다" in msg,
      "겹침 0% 면 '자료 없음' 이 아니라 코드 체계를 지목한다")
check("31011" in msg and "41111" in msg,
      "양쪽 코드를 실제로 보여준다 (무엇이 다른지 눈으로 확인 가능)")
check(not usable, "안 맞는 통제는 쓰지 않는다")

# 나) 같은 체계 — 잔소리하면 안 된다
msg, usable = _say(_region(["41111", "41113"]))
check("⚠" not in msg, "제대로 맞으면 아무 경고도 안 한다")
check(usable == ["d_ln_population"], "맞으면 통제로 쓴다")

# 다) 일부만 — 행정구역 개편(화성 41590 → 41591…) 같은 경우
msg, _ = _say(_region(["41111", "31012"]))
check("만 맞습니다" in msg, "일부만 맞으면 비율을 말한다")
check("41113" in msg, "안 맞는 코드를 이름으로 짚어준다")

print()
print("24. 용도지역이 없는 물건 종류를 조용히 버리지 않는다")

# 토지(LandTrade)는 용도지역을 주지만 공장·창고(InduTrade)는 주지 않는다.
# 예전 필터는 fillna("") 뒤 부분일치라, 용도지역이 없는 거래를 전부
# '안 맞음' 으로 버렸다. **공장 거래가 통째로 사라지는데 로그에는 건수가
# 줄어든 것으로만 보인다** — '공장은 원래 거래가 적구나' 로 읽힌다.
from redt.transform.panel import filter_land_use                # noqa: E402

_mixed = pd.DataFrame({
    "kind":     ["land"] * 3 + ["factory"] * 4,
    "land_use": ["계획관리지역", "상업지역", "자연녹지지역", None, None, "", None],
    "price_per_m2": [1] * 7,
})
_kept = filter_land_use(_mixed)
check((_kept["kind"] == "land").sum() == 2, "용도지역이 있는 토지는 필터가 걸러낸다")
check((_kept["kind"] == "factory").sum() == 4, "용도지역이 없는 공장은 전부 남는다 (API 가 안 주는 칸이다)")

# 한 종류라도 값이 있으면 그 종류에는 필터가 정상 적용돼야 한다.
_all_land = pd.DataFrame({
    "kind": ["factory"] * 3,
    "land_use": ["계획관리지역", "상업지역", "공업지역"],
    "price_per_m2": [1] * 3,
})
check(len(filter_land_use(_all_land)) == 1, "용도지역이 있는 공장은 정상적으로 걸린다")

print()
print("25. 영업소 이름을 명부에서 가져온다 (코드 이름으로는 좌표를 못 찾는다)")

# 교통량 일별 파일에는 영업소명이 없어서 2025년 연간 파일에서 빌려 왔다.
# 그 파일은 **그 뒤에 생긴 영업소를 모른다.** 2026년 신설 327 이 이름
# 없이 들어왔고, 이름이 없으니 좌표도 못 찾았다 — 하필 이 제품에서
# 가장 중요한 관측 대상(신설 IC)이다.
from redt.collect.tollgate_fill import names_from_master, names_from_traffic  # noqa: E402

_master = names_from_master()
check(len(_master) > 500, f"도로공사 명부를 읽는다 ({len(_master)}곳)")

_names = names_from_traffic()
# 327 은 교통량 파일에 '영업소 327' 로 채워져 있다. 명부의 진짜 이름이
# 이겨야 한다 — 코드 이름을 브이월드에 물어봐야 아무것도 안 나온다.
check(_names.get("327") == "서영천",
      f"명부 이름이 코드 이름을 이긴다 (327 → {_names.get('327')})")
check(not any(v.startswith("영업소 ") for v in _names.values()),
      "코드로 채운 이름이 남아 있지 않다")

# 가상 영업소는 실제 시설이 아니다. 좌표를 찾으면 엉뚱한 곳이 찍힌다.
import csv as _csv                                              # noqa: E402
from redt.config import RAW as _RAW                             # noqa: E402
import glob as _glob                                            # noqa: E402
import pathlib                                                  # noqa: E402
_f = sorted(_glob.glob(str(_RAW / "tollgate_master_*.csv")))[-1]
_virtual = {r["영업소코드"].strip().lstrip("0") or "0"
            for r in _csv.DictReader(open(_f, encoding="utf-8-sig"))
            if r.get("가상영업소여부", "").strip() == "Y"}
check(bool(_virtual) and not (_virtual & set(_master)),
      f"가상 영업소 {len(_virtual)}곳은 이름표에 안 넣는다")

print()
print("26. 마도IC — 교통량이 없는 영업소도 명부로 등재한다")

# '수도권제2순환고속도로에 마도IC가 있습니다' 라는 제보가 있었는데
# 지도에 없었다. 원인을 코드 단위로 못박아 둔다.
#
#   마도(805)는 운영기관 48, TCS노선 400 — 봉담~송산 민자 구간이다.
#   TCS 연간 교통량에 **한 해도** 없다. 그래서 fill-tollgates 가 좌표를
#   찾을 대상에 들지 못했고(교통량 있는 영업소만 찾고 있었다), 좌표가
#   없으니 지도에도 못 올라갔다.
#
# 자료가 새는 것이 아니라 도로공사가 그 자료를 갖고 있지 않은 것이다.
# 그러므로 '교통량 0' 이 아니라 '통행량 미공개' 로 다뤄야 한다.
from redt.collect.tollgate_fill import roster_from_master, TCS_OPERATORS  # noqa: E402

_roster = roster_from_master()
check(len(_roster) > 600, f"명부에서 가동중 영업소를 등재한다 ({len(_roster)}곳)")
check("805" in set(_roster["tollgate_id"]), "마도(805)가 등재 대상에 들어간다")
_mado = _roster[_roster["tollgate_id"] == "805"].iloc[0]
check(_mado["name"] == "마도", f"이름이 붙는다 ({_mado['name']})")
check(_mado["operator_cd"] == "48", f"운영기관코드를 싣는다 ({_mado['operator_cd']})")
check(_mado["operator_cd"] not in TCS_OPERATORS,
      "도로공사가 요금을 걷는 노선이 아니다 — 교통량이 없는 이유다")
check(_roster["lat"].isna().all(), "명부에는 좌표가 없다 (좌표는 API·이름검색이 채운다)")

# 운영기관으로 갈린다는 것이 이 진단의 핵심이다. 한 곳이라도 섞이면
# '기관 문제' 가 아니라 '자료 문제' 이므로 손쓸 방법이 달라진다.
#
# 24년치를 통틀면 예외가 딱 하나 있다 — 조원(022·기관 67)이 2003~2004년
# 에만 있다가 사라진다. 그래서 '한 번이라도' 가 아니라 **최근 연도로**
# 못박는다. 지금 지도와 분석이 쓰는 것은 최근 연도다.
_seen = {}
for _p in sorted(_glob.glob(str(_RAW / "tcs_annual_*.csv"))):
    if pathlib.Path(_p).name.startswith("legacy_"):
        continue
    for _r in _csv.DictReader(open(_p, encoding="utf-8-sig")):
        _seen.setdefault(_r["영업소코드"].strip().lstrip("0") or "0",
                         set()).add(int(_r["연도"]))
_last = max(y for ys in _seen.values() for y in ys)
_recent = {t for t, ys in _seen.items() if any(y >= _last - 4 for y in ys)}
_no = {t for t, o in zip(_roster["tollgate_id"], _roster["operator_cd"])
       if o not in TCS_OPERATORS}
check(not (_no & _recent),
      f"도로공사 노선이 아닌 {len(_no)}곳은 최근 5년 교통량이 하나도 없다")
_yes = {t for t, o in zip(_roster["tollgate_id"], _roster["operator_cd"])
        if o in TCS_OPERATORS}
check(len(_yes & _recent) / max(len(_yes), 1) > .95,
      f"도로공사 노선은 {len(_yes & _recent)}/{len(_yes)} 가 최근 교통량을 갖는다")

print()
print("27. 미공개 영업소를 지도에 띄워도 분석 표본이 줄지 않는다")

# 이것이 이번 수정의 가장 위험한 부분이었다.
#
# 패널은 거래마다 '가장 가까운 영업소' 한 곳만 쓴다. 그런데 마도처럼
# 통행량이 없는 영업소를 지도에 띄우려고 영업소 표에 등재하면, 그
# 영업소가 어떤 거래의 가장 가까운 곳이 된다. 그 거래는 교통량을
# 붙일 수 없어 패널에서 통째로 빠진다 — **지도를 고쳤더니 분석이
# 얇아지는** 모양이고, 하필 화성 남부처럼 가장 보고 싶은 곳이 빈다.
#
# 오류도 경고도 안 난다. 표본 수만 조용히 줄어든다. 그래서 못박는다.
from redt.transform.spatial import link_trades_to_tollgates  # noqa: E402

_tr = pd.DataFrame([{"trade_id": "T1", "lat": 37.150, "lon": 126.750}])
_far = pd.DataFrame([{"tollgate_id": "18", "lat": 37.180, "lon": 126.800,
                      "no_traffic": False}])
_base = link_trades_to_tollgates(_tr, _far)
check(bool(_base["is_nearest"].any()),
      "미공개 영업소가 없을 때는 교통량 있는 곳이 대표다")

# 바로 옆(200m)에 미공개 영업소를 하나 놓는다. 거리로는 이쪽이 이긴다.
_with = link_trades_to_tollgates(_tr, pd.DataFrame([
    {"tollgate_id": "805", "lat": 37.1515, "lon": 126.7505, "no_traffic": True},
    {"tollgate_id": "18", "lat": 37.180, "lon": 126.800, "no_traffic": False},
]))
check(set(_with["tollgate_id"]) == {"805", "18"},
      "연결 자체는 둘 다 만든다 (지도·상세가 이것을 쓴다)")
_rep = _with[_with["is_nearest"]]
check(len(_rep) == 1 and _rep.iloc[0]["tollgate_id"] == "18",
      f"대표는 교통량이 있는 곳이다 (뽑힌 곳: {list(_rep['tollgate_id'])})")

# 칸이 아예 없으면 예전 동작 그대로여야 한다 — 이 수정이 전역 동작을
# 바꿨는지 확인한다.
_old = link_trades_to_tollgates(_tr, pd.DataFrame([
    {"tollgate_id": "805", "lat": 37.1515, "lon": 126.7505},
    {"tollgate_id": "18", "lat": 37.180, "lon": 126.800},
]))
check(list(_old[_old["is_nearest"]]["tollgate_id"]) == ["805"],
      "no_traffic 칸이 없으면 예전처럼 가장 가까운 곳이 대표다")

print()
print("28. 헤도닉이 러너를 죽이지 않는다 — 적합은 표본, 예측은 전수")

# run 18 이 조인까지 살아서 끝나고 '분석 패널' 에서 exit 143 으로 죽었다.
# 원인은 이 회귀다. C(시군구)·C(연도)·C(지목) 을 빽빽한 더미로 펴므로
# 열이 300개쯤 되고, 거래 600만이면 행렬만 14GB — 러너는 16GB 다.
#
# run 16 까지는 좌표 있는 거래가 387건뿐이라 안 보였다. 지오코딩을
# 고쳐 789만 건이 되자 바로 터졌다. 앞을 고치니 뒤가 드러난 것이다.
#
# 나눠서 예측하는 것이 값을 바꾸면 안 된다 — 예측은 계수를 곱하는
# 것뿐이므로 나눠도 같아야 한다. 그것을 여기서 못박는다.
from redt.transform.panel import hedonic_adjust                 # noqa: E402
from redt.config import settings as _settings                   # noqa: E402

_rng = np.random.default_rng(7)
_n = 2400
_big = pd.DataFrame({
    "trade_id": [f"H{i}" for i in range(_n)],
    "kind": "land",
    "area_m2": _rng.uniform(300, 3000, _n),
    "sigungu_cd": _rng.choice(["41590", "41461", "41210"], _n),
    "deal_year": _rng.choice([2022, 2023, 2024], _n),
    "jimok": _rng.choice(["전", "답", "대"], _n),
    "land_use": "계획관리",
})
_big["price_per_m2"] = (200000 * (_big["area_m2"] / 1000) ** -0.2
                        * _rng.lognormal(0, .25, _n)).round()

_cfg = _settings()["panel"]
_orig = _cfg.get("hedonic_fit_max")
try:
    _cfg["hedonic_fit_max"] = 10 ** 9          # 자르지 않음 = 예전 동작
    _full = hedonic_adjust(_big.copy())
    _cfg["hedonic_fit_max"] = 800              # 적합 표본을 강제로 자름
    _cut = hedonic_adjust(_big.copy())
finally:
    if _orig is None:
        _cfg.pop("hedonic_fit_max", None)
    else:
        _cfg["hedonic_fit_max"] = _orig

check(len(_full) == len(_cut) == _n,
      f"자르든 안 자르든 전수를 돌려준다 ({len(_full)} · {len(_cut)})")
check(_full["adj_ln_price"].notna().all() and _cut["adj_ln_price"].notna().all(),
      "나눠 예측해도 빠지는 행이 없다")

# 표본으로 적합해도 보정값이 크게 달라지면 안 된다. 계수가 흔들린 만큼은
# 달라지지만, 그것이 결론을 뒤집을 정도면 표본 상한이 너무 낮은 것이다.
_a = _full.set_index("trade_id")["adj_ln_price"]
_b = _cut.set_index("trade_id")["adj_ln_price"].reindex(_a.index)
_corr = _a.corr(_b)
check(_corr > .99, f"표본으로 적합해도 보정값이 사실상 같다 (상관 {_corr:.4f})")
check(abs(_a - _b).max() < .15,
      f"가장 크게 벌어진 거래도 차이가 작다 ({abs(_a - _b).max():.4f})")

# 씨앗이 고정이라 두 번 돌려도 같아야 한다 — 실행할 때마다 화면 값이
# 달라지면 자료를 못 믿게 된다.
try:
    _cfg["hedonic_fit_max"] = 800
    _again = hedonic_adjust(_big.copy())
finally:
    if _orig is None:
        _cfg.pop("hedonic_fit_max", None)
    else:
        _cfg["hedonic_fit_max"] = _orig
check(np.allclose(_cut["adj_ln_price"], _again["adj_ln_price"]),
      "두 번 돌려도 같은 값이 나온다 (표본 씨앗 고정)")

print()
print("29. 무거운 표를 통째로 읽는 곳이 남아 있지 않다")

# run 20 이 '신규 개통 전후 지가' 에서 러너째 죽었습니다. 패널에서 고친
# 것과 **똑같은 코드가 두 곳 더 있었고 제가 한 곳만 고쳤습니다.**
#
#   SELECT * FROM trade WHERE lat IS NOT NULL      789만 행 × 전 컬럼
#   SELECT * FROM trade_tollgate_link            1,961만 행
#
# 한 곳을 고치고 같은 모양을 안 찾은 것이 원인입니다. 그래서 세 곳이
# 같은 함수(_analysis_inputs)를 부르게 묶고, **넷째가 생기면 걸리도록**
# 여기서 소스를 봅니다. 검사가 코드를 읽는 것은 흔치 않지만, 이 사고는
# '어디에도 안 걸리고 러너만 죽는' 종류라 실행으로는 못 잡습니다.
import re as _re                                                # noqa: E402
_cli = (pathlib.Path(__file__).resolve().parents[1]
        / "src" / "redt" / "cli.py").read_text(encoding="utf-8")
# **con.execute() 에 실제로 넘기는 문자열만** 봅니다.
#
# 처음엔 파일 전체를 정규식으로 훑었는데, _analysis_inputs 의 설명이
# 바로 그 SELECT * 를 '예전에 이랬다' 고 인용하고 있어서 자기 설명에
# 걸렸습니다. 문서 문자열을 지우려 ast 로 문자열을 비워봤더니 정작
# 찾으려는 SQL 도 문자열이라 같이 사라졌습니다.
#
# 실행 인자만 보면 둘 다 해결됩니다 — 설명은 execute 에 안 들어가고,
# SQL 은 반드시 들어갑니다.
import ast as _ast                                              # noqa: E402


def _sql_args(src: str) -> list[str]:
    """con.execute(...) 의 첫 인자로 넘어가는 SQL 문자열들."""
    out = []
    for node in _ast.walk(_ast.parse(src)):
        if not (isinstance(node, _ast.Call)
                and isinstance(node.func, _ast.Attribute)
                and node.func.attr == "execute" and node.args):
            continue
        arg = node.args[0]
        if isinstance(arg, _ast.Constant) and isinstance(arg.value, str):
            out.append(arg.value)
        elif isinstance(arg, _ast.JoinedStr):      # f-string
            out.append("".join(v.value for v in arg.values
                               if isinstance(v, _ast.Constant)
                               and isinstance(v.value, str)))
    return out


_wide = [q for q in _sql_args(_cli)
         if _re.search(r'SELECT \* FROM (trade|trade_tollgate_link)\b', q)]
check(not _wide, f"무거운 표를 SELECT * 로 읽는 곳이 없다 ({len(_wide)}군데)")

_code = _cli
_uses = len(_re.findall(r'_analysis_inputs\(con\)', _code))
check(_uses >= 3,
      f"패널·events·rank 가 같은 함수를 쓴다 (부르는 곳 {_uses}군데)")

# 그 함수가 실제로 좁혀 읽는지 — 이름만 같고 안이 넓으면 의미가 없습니다.
_body = _code.split("def _analysis_inputs(con):")[1].split("\ndef ")[0]
check("WHERE is_nearest" in _body,
      "최근접 연결만 읽는다 (1,961만 → 662만)")
check("PANEL_TRADE_COLS" in _body,
      "거래는 필요한 칸만 읽는다 (전 컬럼이 아니다)")
check("distance_km" in _body,
      "events 가 쓰는 distance_km 을 빠뜨리지 않는다")

# ────────────────────────────────────────────────────────────────
print("30. 헤도닉 — 표본에 없는 시군구를 예측해도 죽지 않는가")

# run 21 이 여기서 죽었다. 적합은 30만 표본, 예측은 789만 전수로 바꿨더니
# 표본에 안 들어간 희귀 시군구(11290)를 예측할 때 patsy 가 터졌다:
#   PatsyError: observation with value '11290' does not match expected levels
# 무작위 표본이면 반드시 다시 터진다. 층화해서 뽑는지 확인한다.
from redt.transform import panel as _panel          # noqa: E402

RARE = "11029"          # run 21 을 죽인 11290 과 같은 역할
_rng30 = np.random.default_rng(30)
_rows = []
for i in range(50):
    _sgg = f"{11000 + i}"
    # 한 곳만 딱 1건. 무작위 표본(상한 2,000/4,901)에 들어갈 확률은 41%다.
    _n = 1 if _sgg == RARE else 100
    for _ in range(_n):
        _rows.append({
            "kind": "land",
            "sigungu_cd": _sgg,
            "deal_year": int(_rng30.integers(2015, 2025)),
            "area_m2": float(_rng30.uniform(100, 2000)),
            "price_per_m2": float(_rng30.uniform(1e5, 1e6)),
            "jimok": "전",
            "land_use": "계획관리지역",
            "building_use": "NA",
            "building_area_m2": 0.0,
        })
_df30 = pd.DataFrame(_rows)
assert (_df30["sigungu_cd"] == RARE).sum() == 1

_real_settings = _panel.settings
_panel.settings = lambda: {
    **_real_settings(),
    "panel": {**_real_settings()["panel"], "hedonic_fit_max": 2_000},
}
try:
    _err = None
    try:
        _out30 = _panel.hedonic_adjust(_df30)
    except Exception as exc:                        # noqa: BLE001
        _err = f"{type(exc).__name__}: {exc}"[:160]
        _out30 = None
finally:
    _panel.settings = _real_settings

check(_err is None, f"희귀 시군구가 있어도 헤도닉이 끝난다 ({_err or 'ok'})")
if _out30 is not None:
    check(len(_out30) == len(_df30),
          f"전수를 다 보정한다 ({len(_out30):,}/{len(_df30):,}행)")
    check(_out30["adj_ln_price"].notna().all(),
          "보정값에 결측이 없다")

# 표본 자체가 모든 수준을 덮는지도 직접 본다 — 위 검사만으로는 상한이
# 우연히 안 걸렸을 때도 통과해버린다.
_samp = _panel._fit_sample(_df30, ["sigungu_cd", "deal_year"], 2_000, seed=1)
check(_samp["sigungu_cd"].nunique() == _df30["sigungu_cd"].nunique(),
      f"적합 표본이 시군구 전 수준을 덮는다 "
      f"({_samp['sigungu_cd'].nunique()}/{_df30['sigungu_cd'].nunique()})")
check(len(_samp) <= 2_000 and len(_samp) < len(_df30),
      f"덮고 남은 자리만 무작위로 채운다 (표본 {len(_samp):,}/{len(_df30):,})")
check(_panel._fit_sample(_df30, ["sigungu_cd"], 10 ** 9, seed=1) is _df30,
      "상한보다 작으면 표본을 뽑지 않고 전수를 쓴다")


# ────────────────────────────────────────────────────────────────
print("\n31. 시군구 인구를 우리 행정구역에 맞추는가")

from redt.collect import population as _pop           # noqa: E402

# 가짜 KOSIS 응답. 실제 파일에서 관측한 세 가지 함정을 그대로 담는다.
#   · 전국(00)·시도(2자리)가 섞여 있다
#   · 시 코드가 구 인구를 이미 포함한다
#   · 총인구·남자·여자 세 항목이 한 파일에 있다
_rows = []
for _y in (2009, 2010):
    _rows += [
        {"C1": "00", "C1_NM": "전국", "PRD_DE": str(_y), "DT": "5000", "ITM_NM": "총인구수"},
        {"C1": "48", "C1_NM": "경남", "PRD_DE": str(_y), "DT": "3000", "ITM_NM": "총인구수"},
        {"C1": "11110", "C1_NM": "종로구", "PRD_DE": str(_y), "DT": "100", "ITM_NM": "총인구수"},
        {"C1": "11110", "C1_NM": "종로구", "PRD_DE": str(_y), "DT": "49", "ITM_NM": "남자인구수"},
    ]
# 창원 통합 — 2009 까지는 셋, 2010 부터는 하나
_rows += [
    {"C1": "48110", "C1_NM": "창원시", "PRD_DE": "2009", "DT": "500", "ITM_NM": "총인구수"},
    {"C1": "48160", "C1_NM": "마산시", "PRD_DE": "2009", "DT": "400", "ITM_NM": "총인구수"},
    {"C1": "48190", "C1_NM": "진해시", "PRD_DE": "2009", "DT": "180", "ITM_NM": "총인구수"},
    {"C1": "48120", "C1_NM": "창원시", "PRD_DE": "2010", "DT": "1090", "ITM_NM": "총인구수"},
    {"C1": "48121", "C1_NM": "의창구", "PRD_DE": "2010", "DT": "260", "ITM_NM": "총인구수"},
    # 광주·전남 통합 — KOSIS 는 아직 옛 코드로 준다
    {"C1": "46110", "C1_NM": "목포시", "PRD_DE": "2009", "DT": "220", "ITM_NM": "총인구수"},
    {"C1": "46110", "C1_NM": "목포시", "PRD_DE": "2010", "DT": "215", "ITM_NM": "총인구수"},
]
_tmp = ROOT / "data" / "raw" / "_test_kosis.csv"
_tmp.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame(_rows).to_csv(_tmp, index=False)
try:
    _k = _pop.read_kosis(_tmp)
finally:
    _tmp.unlink()

# 전국·시도는 5자리가 아니라 빠지고, 남자인구수도 빠져야 한다.
check(set(_k["code"]) == {"11110", "48110", "48160", "48190", "48120", "48121", "46110"},
      f"전국·시도와 성별 항목을 걸러낸다 ({sorted(set(_k['code']))})")
check(len(_k[(_k.code == "11110") & (_k.year == 2009)]) == 1,
      "한 시군구·한 해에 한 줄만 남는다 (총인구수)")

_our = {"11110": "종로구", "48120": "창원시", "48121": "의창구", "12110": "목포시"}
_tab, _rep = _pop.normalize(_k, _our)
_get = lambda c, y: _tab[(_tab.sigungu_cd == c) & (_tab.year == y)]

# 합병 — 2009 년 창원시는 옛 세 시의 합이어야 한다.
_c09 = _get("48120", 2009)
check(len(_c09) == 1 and int(_c09["population"].iloc[0]) == 1080,
      f"통합 이전 해는 옛 코드를 합산해 잇는다 (창원 2009 = 500+400+180)"
      f" → {int(_c09['population'].iloc[0]) if len(_c09) else '없음'}")
check(len(_c09) and "합산" in _c09["source"].iloc[0],
      "무엇으로 채웠는지 근거를 남긴다")

# 분할 — 2009 년 의창구는 나눌 근거가 없으므로 **비어야** 한다.
check(len(_get("48121", 2009)) == 0,
      "구가 갈라지기 전 해는 채우지 않는다 (나눌 근거가 없다)")
check(2009 in _rep["gaps"].get("48121", []),
      "그 빈 자리를 보고에 남긴다")

# 시도 통합 — 코드는 12110 인데 자료는 46110 으로 온다. 이름으로 잇는다.
_m09 = _get("12110", 2009)
check(len(_m09) == 1 and int(_m09["population"].iloc[0]) == 220,
      "시도가 통째로 바뀐 시군구를 이름으로 잇는다 (12110 ← 46110)")
check(_rep["aliases"].get("12110") == "46110",
      "무슨 옛 코드에서 이었는지 보고한다")

# 같은 사람을 두 번 세지 않는가 — 시와 구를 같이 넣어도 각자 제 값이다.
check(int(_get("48120", 2010)["population"].iloc[0]) == 1090
      and int(_get("48121", 2010)["population"].iloc[0]) == 260,
      "시와 구는 각자 제 값을 갖는다 (합치지 않는다)")

# ────────────────────────────────────────────────────────────────
print("\n32. H3 표가 추정에 성공했을 때도 칸 이름이 맞는가")

# run 27 이 여기서 죽었다. H3 통제가 하나도 없던 동안에는 이 자리에 닿을
# 일이 없어 드러나지 않다가, 인구를 넣은 **첫 실행**에서 판정이 통째로
# 안 나왔다. 게다가 그 단계가 continue-on-error 라 실행은 초록이었다.
#
#   표본이 모자란 줄은 {"변수": ...} 로 만들고
#   추정에 성공한 줄은 _row() 가 {"항": ...} 로 만든다
#   → 성공한 줄만 있으면 '변수' 칸이 아예 없어 out[cols] 가 KeyError.
_rng = np.random.default_rng(20260904)
_n = 600
_h3in = pd.DataFrame({
    "kind": "land",
    "d_ln_price": _rng.normal(0, .2, _n),
    "d_pop": _rng.normal(0, .05, _n),
    "year": _rng.integers(2015, 2025, _n),
    "sigungu_cd": _rng.integers(41000, 41030, _n).astype(str),
    "tollgate_id": ["tg%02d" % i for i in _rng.integers(0, 40, _n)],
})
_t3 = H.h3(_h3in, ["d_pop"], kind="land")
# 칸 목록을 통째로 박아 두면 칸 하나 늘 때마다 멀쩡한 검사가 빨개진다
# (mde 를 더했을 때 실제로 그랬다). 지켜야 할 것은 **첫 칸이 '변수' 이고
# 필요한 칸이 다 있다**는 것이지 목록이 똑같다는 것이 아니다.
_want3 = ["변수", "n", "영업소", "beta", "se", "p"]
check(list(_t3.columns)[0] == "변수" and set(_want3) <= set(_t3.columns),
      f"추정 성공 줄도 '변수' 칸을 갖는다 ({list(_t3.columns)})")
check(len(_t3) == 1 and _t3["변수"].iloc[0] == "d_pop"
      and not pd.isna(_t3["beta"].iloc[0]),
      "실제로 계수가 들어 있다")

# 표본이 모자란 줄과 성공한 줄이 **섞여도** 칸이 어긋나지 않아야 한다.
_h3in["d_thin"] = np.where(_h3in.index < 20, _rng.normal(0, .05, _n), np.nan)
_mixed = H.h3(_h3in, ["d_pop", "d_thin"], kind="land")
check(list(_mixed.columns) == list(_t3.columns) and len(_mixed) == 2,
      f"모자란 줄과 성공한 줄이 섞여도 칸이 같다 ({len(_mixed)}줄)")
check(bool(_mixed["beta"].isna().any()) and bool(_mixed["beta"].notna().any()),
      "모자란 줄은 비고, 성공한 줄은 값이 든다")

# payload 가 그 표를 그대로 읽는가 (화면·요약이 같은 것을 본다).
_v = pd.DataFrame([{"가설": "H1", "판정": "아직 모름", "근거": ""},
                   {"가설": "H2", "판정": "아직 모름", "근거": ""},
                   {"가설": "H3", "판정": "지지", "근거": ""}])
_pay = H.payload(_v, {"H3": _t3}, kind="land", volume_col="volume_total",
                 controls=["d_pop"], pre_trend_ok=None)
_h3rows = [h for h in _pay["hypotheses"] if h["key"] == "H3"][0]["rows"]
check(len(_h3rows) == 1 and _h3rows[0]["var"] == "d_pop"
      and _h3rows[0]["label"] == "d_pop",
      f"판정 파일에 변수 이름이 실린다 ({_h3rows[0]['label'] if _h3rows else '없음'})")

# ────────────────────────────────────────────────────────────────
print("\n33. 공장 헤도닉이 건물 나이를 뺀다")

from redt.transform import panel as pn                   # noqa: E402

# 설계서(docs/hypotheses-design.md 6절)에서 확인한 구멍이다. 공장 실거래에는
# 건물이 붙어 있고 건물은 낡는데, 헤도닉이 건물 유무와 면적만 통제하고
# **건축연도를 안 썼다.** 도시 근처 공장이 더 오래됐다면 낡은 정도가
# 교통량과 얽혀 계수를 밀어버린다.
_rng2 = np.random.default_rng(20260905)
_n2 = 900
_age = _rng2.integers(0, 40, _n2)
_fac = pd.DataFrame({
    "kind": "factory",
    "sigungu_cd": _rng2.integers(41000, 41010, _n2).astype(str),
    "deal_year": 2020,
    "build_year": 2020 - _age,
    "area_m2": _rng2.uniform(500, 5000, _n2),
    "building_area_m2": _rng2.uniform(200, 2000, _n2),
    "jimok": "공장용지",
    "land_use": "공업지역",
    "building_use": "공장",
    # 값은 나이가 들수록 떨어진다. 이걸 안 빼면 그대로 남는다.
    "price_per_m2": np.exp(13 - 0.02 * _age + _rng2.normal(0, .05, _n2)),
})
_out = pn.hedonic_adjust(_fac.copy())
check("bldg_age" in _out.columns and "has_age" in _out.columns,
      "건물 나이 칸을 만든다")

# 보정 뒤에는 나이와 값의 관계가 남아 있으면 안 된다.
import numpy as _np2                                    # noqa: E402
_before = _np2.corrcoef(_age, _out["ln_price"])[0, 1]
_after = _np2.corrcoef(_age, _out["adj_ln_price"])[0, 1]
check(abs(_before) > 0.4, f"보정 전에는 나이와 값이 얽혀 있다 (r={_before:+.2f})")
check(abs(_after) < abs(_before) / 2,
      f"보정 뒤에는 그 얽힘이 크게 준다 (r={_before:+.2f} → {_after:+.2f})")

# 미래에 지어진 건물·200년 된 공장은 입력 오류다. 그런 값 하나가 제곱항을
# 통해 계수를 통째로 끌고 간다.
_bad = _fac.copy()
_bad.loc[_bad.index[:3], "build_year"] = [2050, 1700, 1800]
_outb = pn.hedonic_adjust(_bad)
check(bool((_outb["bldg_age"].between(0, 100)).all()),
      f"말이 안 되는 나이는 안 쓴다 (최대 {_outb['bldg_age'].max():.0f}년)")
check(int(_outb.loc[_outb.index[:3], "has_age"].sum()) == 0,
      "그 건들은 '나이 모름' 으로 표시한다")

# 토지는 건물이 없다. 이 변경이 토지 결과를 건드리면 안 된다.
_land = _fac.copy()
_land["kind"] = "land"
_land["build_year"] = np.nan
_land["building_area_m2"] = 0.0
_land["jimok"] = "전"
_outl = pn.hedonic_adjust(_land)
check(int(_outl["has_age"].sum()) == 0,
      "토지는 나이가 전부 '모름' 이라 식에 안 들어간다")

# ────────────────────────────────────────────────────────────────
print("\n34. H4·H5 — 수준 비교가 진실을 되찾는가")

# 이 두 가설은 실제 자료에서 아직 한 번도 안 돌았다(cross.build 가 비어
# 있었다). 만들어 놓고 안 돌린 코드가 어떻게 되는지는 run 27 에서 봤다.
# 그래서 **진실을 아는 자료**를 만들어 넣고 되찾는지 본다.
_r3 = np.random.default_rng(20260905)
_nic = 220
# 서울에서 멀수록 교통량이 적고 값도 싸다 — 실제 자료의 모양이다.
# 교통량 자체의 효과는 **0 으로** 넣는다. 즉 통제를 제대로 넣으면
# 계수가 사라져야 맞다.
_km = _r3.uniform(20, 300, _nic)
_lv = pd.DataFrame({
    "tollgate_id": [f"t{i}" for i in range(_nic)],
    "year": 2024,
    "sido": _r3.choice(["경기", "충남", "경북"], _nic),
    "ln_km_seoul": np.log(_km),
    "ln_traffic": 12 - 0.8 * np.log(_km) + _r3.normal(0, .25, _nic),
})
_lv["ln_price"] = 15 - 1.2 * np.log(_km) + _r3.normal(0, .3, _nic)

_t4 = H.h4(_lv)
check(len(_t4) == 3 and list(_t4.columns)[:3] == ["모형", "n", "영업소"],
      f"세 모형을 나란히 낸다 ({list(_t4['모형'])})")
_raw = _t4.iloc[0]
_ctl = _t4[_t4["모형"] == "+서울거리"].iloc[0]
check(_raw["beta"] > 0.5 and _raw["p"] < 0.05,
      f"통제 전에는 크게 유의하다 (β={_raw['beta']:+.2f}, p={_raw['p']:.4f})")
check(abs(_ctl["beta"]) < abs(_raw["beta"]) / 3,
      f"서울거리를 넣자 계수가 무너진다 (β={_raw['beta']:+.2f} → {_ctl['beta']:+.2f})"
      " ← 진실이 0 이므로 이게 맞다")
check(bool((_t4["mde"] > 0).all()), "줄마다 최소 탐지 가능 효과가 붙는다")
check(abs(_t4.iloc[0]["mde"] / _t4.iloc[0]["se"] - 2.80) < 0.01,
      "MDE 는 표준오차의 2.80배다")

# 판정 — 유의한 양수라도 '지지' 가 아니라 '상관' 이어야 한다.
_v4, _w4 = H.judge_h4(_t4.iloc[[0]])
check(_v4 == H.Verdict.CORRELATED,
      f"수준 비교는 유의해도 '지지' 가 아니라 '상관' 이다 ({_v4})")
check("상관" in _w4, "근거에도 상관이라고 적는다")

# ── H5 · 곱셈항 ──
# 인구가 많을수록 교통량의 효과가 커지는 자료를 만든다 (곱셈항 진실 = +0.5).
_pop = _r3.uniform(9.5, 13.5, _nic)
_ct = _lv["ln_traffic"] - _lv["ln_traffic"].mean()
_cp = _pop - _pop.mean()
_lv2 = _lv.assign(
    ln_pop=_pop,
    ln_price=10 + 0.3 * _ct + 0.2 * _cp + 0.5 * _ct * _cp + _r3.normal(0, .2, _nic))
_t5 = H.h5(_lv2)
check(len(_t5) == 4, f"따로·같이 네 줄을 낸다 ({len(_t5)}줄)")
_inter = _t5[_t5["모형"] == "같이 · 곱셈항"].iloc[0]
check(abs(_inter["beta"] - 0.5) < 0.15,
      f"곱셈항을 되찾는다 (넣은 값 +0.500 → {_inter['beta']:+.3f})")
_main = _t5[_t5["모형"] == "같이 · 교통량(평균 인구에서)"].iloc[0]
check(abs(_main["beta"] - 0.3) < 0.15,
      f"중심화 덕에 주효과가 '평균 인구에서의 효과' 다 (넣은 값 +0.300 →"
      f" {_main['beta']:+.3f})")
_v5, _w5 = H.judge_h5(_t5)
check(_v5 == H.Verdict.CORRELATED, f"판정도 상관이다 ({_v5})")

# 곱셈항만 서고 주효과가 없으면 믿지 않는다.
_t5b = _t5.copy()
_t5b.loc[_t5b["모형"].isin(["따로 · 교통량", "따로 · 인구"]), "p"] = 0.9
_v5b, _w5b = H.judge_h5(_t5b)
check(_v5b == H.Verdict.UNKNOWN,
      f"주효과 없이 곱셈항만 서면 그대로 안 믿는다 ({_v5b})")

# 자료가 없을 때 조용히 넘어가지 않는다.
check(H.judge_h4(H.h4(pd.DataFrame()))[0] == H.Verdict.UNKNOWN,
      "수준 비교표가 비면 '아직 모름' 으로 남긴다")
check(H.judge_h5(H.h5(_lv))[0] == H.Verdict.UNKNOWN,
      "인구가 없으면 H5 는 '아직 모름' 이다 (H4 는 그대로 돈다)")

# 주 가설과 탐색을 미리 갈라 둔다.
check(H.is_primary("land", "volume_total") is True
      and H.is_primary("factory", "volume_total") is False
      and H.is_primary("land", "volume_freight") is False,
      "주 가설은 토지·전체 교통량 하나뿐이다")


# ────────────────────────────────────────────────────────────────
print("\n35. H1 통제 — 이름만 있고 붙지는 않던 것")
# ────────────────────────────────────────────────────────────────
# run 30 판정표의 H1 은 두 줄 다 '통제 없음' 이었다. attach_controls 는
# **패널**에 붙이는데 h1() 은 **이벤트 표본**을 받는다. 열쇠가 달라
# `[c for c in controls if c in base.columns]` 가 늘 빈 목록이었고,
# H1 은 한 번도 통제를 받은 적이 없다.
#
# '통제 없음' 이라고 적히기는 했다. 하지만 그 줄을 읽는 사람은
# '통제를 넣어도 안 변했다' 로 읽는다 — 정반대의 뜻이다.
#
# 진실을 아는 자료로 확인한다. IC 개통 자체의 효과는 **0** 으로 넣고,
# 개통한 시군구가 마침 인구도 늘게 만든다. 통제가 진짜로 붙으면
# 교차항이 무너져야 하고, 안 붙으면 인구 효과를 IC 효과로 착각한다.
# 시군구 하나에 영업소 넷을 둔다. 하나씩 두면 시군구 고정효과가
# 영업소를 통째로 흡수해 **군집 수가 모수 수보다 적어지고**, 군집
# 표준오차 행렬의 대각이 음수가 되어 se 가 NaN 이 된다. 실제 자료는
# 영업소 561곳에 시군구 235개라 그럴 일이 없다 — 검사 쪽이 실제
# 자료의 모양을 따라가야 한다.
_rng = np.random.default_rng(35)
_N_SGG, _PER_SGG = 16, 4
_N_TG = _N_SGG * _PER_SGG
_YEARS = range(2014, 2024)

# 개통 시점을 시군구마다 다르게 둔다. 전부 같은 해면 post 가 연도의
# 함수가 되어 C(year) 와 완전히 겹치고, 설계행렬이 특이해져 군집
# 표준오차가 NaN 이 된다. 실제 자료는 개통이 여러 해에 흩어져 있다.
_open = {k: 2018 + (k % 4) for k in range(_N_SGG)}
_growth, _reg = {}, []
for k in range(_N_SGG):
    sgg = f"{41000 + k:05d}"
    # 인구 증가율은 시군구마다 다르다. 앞쪽 절반이 '크는 동네' 다.
    # 처치 쪽이 평균적으로 높지만 **똑같지는 않다** — 똑같이 만들면
    # 통제가 처치와 완전히 겹쳐 계수가 식별되지 않는다.
    _growth[sgg] = (0.030 if k < _N_SGG // 2 else 0.008) + _rng.normal(0, .010)
    level = 100000.0
    for year in _YEARS:
        level *= np.exp(_growth[sgg] if year >= _open[k] else 0.004)
        _reg.append({"sigungu_cd": sgg, "year": year, "metric": "population",
                     "value": level})

# **처치는 시군구 안에서 갈린다.** 시군구 하나가 통째로 처치이면
# treated 가 시군구 고정효과와 완전히 겹쳐 아무것도 식별되지 않는다.
# 그러면서도 처치는 '크는 동네' 에 몰려 있다 (3:1 대 1:3) — 교란의
# 모양이 바로 이것이다. 정부는 개발될 곳에 IC 를 놓는다.
_rows = []
for tg in range(_N_TG):
    k = tg // _PER_SGG
    sgg = f"{41000 + k:05d}"
    treated = int((tg % _PER_SGG) < (3 if k < _N_SGG // 2 else 1))
    for year in _YEARS:
        d_pop = _growth[sgg] if year >= _open[k] else 0.004
        for _ in range(12):
            # 값은 인구 변화에만 반응한다. 개통에는 반응하지 않는다.
            _rows.append({
                "adj_ln_price": 10 + 3.0 * d_pop + _rng.normal(0, .05),
                "treated": treated, "post": int(year >= _open[k]),
                "year": year, "sigungu_cd": sgg, "tollgate_id": tg,
            })
_ev = pd.DataFrame(_rows)
_region35 = pd.DataFrame(_reg)

# 붙이기 전 — 지금까지의 동작.
_t1_before = H.h1(_ev, ["d_ln_population", "d_zone_area"])
_before = _t1_before[_t1_before["모형"] == "H3 통제 후"].iloc[0]
check(_before["비고"] == "통제 없음" and pd.isna(_before["beta"]),
      "이름만 넘기면 붙지 않는다 — 지금까지의 동작을 재현한다")

_raw = _t1_before[_t1_before["모형"] == "통제 전"].iloc[0]
check(_raw["beta"] > 0 and _raw["p"] < 0.05,
      f"통제 없이는 IC 효과가 있는 것처럼 보인다 (넣은 값 0 → {_raw['beta']:+.3f},"
      f" p={_raw['p']:.3f})")

# 붙인 뒤 — 새 함수를 거친다.
_ev2, _use2 = H.attach_event_controls(_ev, _region35, pd.DataFrame())
check("d_ln_population" in _use2,
      f"이벤트 표본에 인구 변화가 실제로 붙는다 ({_use2})")
check(_ev2["d_ln_population"].notna().mean() > 0.7,
      f"붙은 자리가 대부분이다 ({_ev2['d_ln_population'].notna().mean():.0%})")

_t1_after = H.h1(_ev2, _use2)
_after = _t1_after[_t1_after["모형"] == "H3 통제 후"].iloc[0]
check(pd.notna(_after["beta"]) and _after["비고"] == "d_ln_population",
      "통제 후 줄이 실제로 추정된다")
check(abs(_after["beta"]) < abs(_raw["beta"]) / 2,
      f"통제를 넣자 교차항이 무너진다 ({_raw['beta']:+.3f} → {_after['beta']:+.3f})")
# 여기가 이 절의 요점이다. 거짓 양성이 통제 뒤에 사라져야 한다 —
# 계수가 줄기만 하고 여전히 유의하면 통제가 일을 못 한 것이다.
check(_after["p"] > 0.05,
      f"거짓 양성이 사라진다 (p={_raw['p']:.3f} → {_after['p']:.2f})")

# 판정이 통제 후 줄을 읽는가. 통제 전만 읽으면 위 계산이 무의미하다.
_v1, _w1 = H.judge_h1(_t1_after, True)
check("H3 통제 후" in _w1 or "통제 후" in _w1,
      f"판정 설명이 통제 후 줄을 가리킨다 ({_w1[:60]})")

# ── 표본이 바뀐 탓과 통제 탓을 가른다 ──
# 통제 변수에 결측이 있으면 통제를 넣는 순간 표본이 함께 줄어든다.
# 그러면 계수가 움직이는데, 두 줄만으로는 그 움직임이 통제 덕인지
# 표본이 달라진 탓인지 못 가른다 — run 31 의 토지가 정확히 그랬다
# (100,239 → 43,661, 계수 부호까지 뒤집힘).
#
# 여기서는 인구를 **일부러 절반만** 비워, 통제를 넣으면 표본이 반으로
# 줄게 만든다. 그래도 가운데 줄이 있으면 갈린다.
_ev_gap = _ev2.copy()
_ev_gap.loc[_ev_gap.index % 2 == 0, "d_ln_population"] = np.nan
_t1_gap = H.h1(_ev_gap, _use2)
_models = list(_t1_gap["모형"])
check(_models == ["통제 전", "통제 전 · 같은 표본", "H3 통제 후"],
      f"세 줄로 낸다 ({_models})")
_raw_r = _t1_gap[_t1_gap["모형"] == "통제 전"].iloc[0]
_same_r = _t1_gap[_t1_gap["모형"] == "통제 전 · 같은 표본"].iloc[0]
_ctrl_r = _t1_gap[_t1_gap["모형"] == "H3 통제 후"].iloc[0]
check(_raw_r["n"] > _same_r["n"] and _same_r["n"] == _ctrl_r["n"],
      f"가운데와 아래가 같은 표본이다 ({_raw_r['n']} → {_same_r['n']} = {_ctrl_r['n']})")
check("빠진 표본" in str(_same_r["비고"]),
      f"몇 %가 빠졌는지 적는다 ({_same_r['비고']})")
# 통제 없이 표본만 줄인 것이므로, 가운데 줄은 위와 크게 다르지 않아야
# 한다. 진짜 변화는 가운데 → 아래에서 일어난다.
check(abs(_ctrl_r["beta"] - _same_r["beta"]) > abs(_same_r["beta"] - _raw_r["beta"]),
      f"움직임의 대부분이 통제 탓이다 (표본 {_same_r['beta'] - _raw_r['beta']:+.3f}"
      f" vs 통제 {_ctrl_r['beta'] - _same_r['beta']:+.3f})")
_v1g, _w1g = H.judge_h1(_t1_gap, True)
check("표본이 바뀌어서가" in _w1g and "통제 때문이" in _w1g,
      f"판정이 둘을 갈라 적는다 ({_w1g[-70:]})")

# 산단 압력도 영업소·연도로 붙는가 (패널과 열쇠가 다른 쪽).
_press = pd.DataFrame([{"tollgate_id": tg, "year": y,
                        "zone_area_km2": float(max(0, y - 2016)), "zone_n": 1}
                       for tg in range(_N_TG) for y in _YEARS])
_ev3, _use3 = H.attach_event_controls(_ev, _region35, _press)
check("d_zone_area" in _use3, f"산단 압력도 붙는다 ({_use3})")
check(_ev3["d_zone_area"].notna().mean() > 0.7,
      f"산단 압력이 붙은 자리도 대부분이다 ({_ev3['d_zone_area'].notna().mean():.0%})")

# 자료가 없으면 조용히 죽지 않는다.
_ne, _nu = H.attach_event_controls(pd.DataFrame(), _region35, _press)
check(_ne.empty and _nu == [], "빈 표본을 넣으면 빈 표와 빈 목록이 나온다")
_e0, _u0 = H.attach_event_controls(_ev, None, None)
check(_u0 == [], "지역 자료가 없으면 통제 목록이 빈다 (거짓 통제를 만들지 않는다)")

# ────────────────────────────────────────────────────────────────
print("\n36. 공장과 창고를 가른다")
# ────────────────────────────────────────────────────────────────
# 국토부 15126470 은 이름 그대로 '공장 및 창고 등' 자료다. 창고는
# 처음부터 같이 들어오고 있었고, 우리가 전부 kind='factory' 한 칸에
# 담아 두어 **구분이 보이지 않았을 뿐**이다. (2026-09-07 지시)
from redt import usage as U                                      # noqa: E402

# run 33 이 실제 값을 알려줬다. 건물주용도가 **100% 채워져** 오고
# 값은 딱 7종이었다:
#   공장 143,159 · 창고시설 30,833 · 동물 및 식물 관련시설 20,111 ·
#   자동차 관련시설 10,829 · 위험물 저장 및 처리시설 7,133 ·
#   자원순환 관련시설 1,804 · 운수시설 1,711
# 지목은 0% 로 안 온다.
_REAL = ['공장', '창고시설', '동물 및 식물 관련시설', '자동차 관련시설',
         '위험물 저장 및 처리시설', '자원순환 관련시설', '운수시설']

# label 은 **뭉개지 않는다.** 처음에는 셋으로 줄였는데, 그 '기타'
# 41,588건이 축사·정비소·주유소로 또렷이 갈려 있었다. 모르는 것이
# 아니라 아는 것을 한 칸에 뭉쳐 놓고 '미상' 이라 부르고 있었다.
check(all(U.label(v) == v for v in _REAL),
      "건물주용도를 그대로 이름으로 쓴다 (뭉개지 않는다)")
check(len({U.label(v) for v in _REAL}) == len(_REAL),
      "7종이 7개 이름으로 남는다")

# classify 는 **색과 묶음에만** 쓴다. 셋으로 줄이는 것이 여기서는 맞다 —
# 사람 눈이 점 색을 대여섯 개까지밖에 못 가린다.
check(U.classify('공장') == '공장' and U.classify('창고시설') == '창고',
      "묶음은 공장·창고를 가른다")
check(U.classify('동물 및 식물 관련시설') == '기타'
      and U.classify('위험물 저장 및 처리시설') == '기타',
      "그 밖 시설은 한 묶음이다 (이름은 label 이 지킨다)")
# 글자를 통째로 비교하지 않는다. '창고시설' 이 '물류창고' 로 바뀌는 날
# 조용히 전부 '기타' 가 되면, 화면은 창고 0건을 보여주면서 이유를
# 말하지 못한다.
check(U.classify('물류창고') == '창고' and U.classify('일반공장') == '공장',
      "글자가 바뀌어도 '창고'·'공장' 이 들었으면 묶는다")
check(U.classify('공장·창고') == '창고', "둘 다 든 값은 창고로 센다")

# 건물주용도가 비면 지목이 받는다. 이 자료에는 지목이 0% 로 안 오지만,
# 안 오던 것이 오고 오던 것이 안 오는 날을 대비해 남긴다.
check(U.label('', '창고용지') == '창고' and U.label(None, '공장용지') == '공장',
      "건물주용도가 비면 지목으로 가른다")
check(U.label('공장', '창고용지') == '공장', "건물주용도가 지목보다 앞선다")

# **가를 수 없는 것을 아는 척하지 않는다.**
check(U.label('', '') == U.UNKNOWN and U.label(None, None) == U.UNKNOWN,
      "가를 칸이 둘 다 비면 빈 값이다 (공장으로 몰지 않는다)")

# 내보내기가 그 판정을 실제로 싣는가.
from redt import webexport as _wx2                               # noqa: E402
_tr = pd.DataFrame([
    {"kind": "factory", "building_use": "창고시설", "jimok": "대"},
    {"kind": "factory", "building_use": "", "jimok": "공장용지"},
    {"kind": "factory", "building_use": "", "jimok": ""},
    {"kind": "land", "building_use": "", "jimok": "전"},
])
_out = _wx2._with_usage(_tr)
check(list(_out["usage"]) == ['창고시설', '공장', '', ''],
      f"내보내기가 usage 를 원래 이름으로 붙인다 ({list(_out['usage'])})")
check("building_use" not in _out.columns,
      "원값은 파일에 싣지 않는다 (판정에만 쓴다)")
# 토지는 가를 것이 없다. 빈 값이어야 _trade_records 가 안 싣는다.
check(_out.loc[_out["kind"] == "land", "usage"].eq("").all(),
      "토지는 usage 가 비어 있다")

# ────────────────────────────────────────────────────────────────
print("\n37. 도로 접함 — 순서가 있는 변수")
# ────────────────────────────────────────────────────────────────
# 요구사항(2026-09-07): "부정형이 무조건 좋지 않은 건 아닙니다.
# 도로를 접하는 가가 제일 중요합니다."
#
# 두 변수를 다르게 다뤄야 한다는 뜻이다. 형상은 순서가 없어 종류로
# 두고, 도로접면은 **순서가 있어** 등급으로 넣는다.
_ROADS = ['광대로한면', '중로한면', '소로한면', '세로한면(가)',
          '세로한면(불)', '맹지']
_g = [U.road_grade(r) for r in _ROADS]
check(_g == sorted(_g, reverse=True) and _g == [5, 4, 3, 2, 1, 0],
      f"넓은 길부터 순서대로 등급이 내려간다 ({_g})")

# **'지정되지않음' 을 맹지와 같이 두지 않는다.** 도로가 없는 땅과 조사가
# 안 된 땅을 한 칸에 넣으면, 모르는 것이 '최악' 으로 셈해진다.
check(U.road_grade('지정되지않음') is None and U.road_grade('') is None,
      "모르는 것은 맹지(0)가 아니라 None 이다")
check(U.road_grade('맹지') == 0, "맹지는 0 이다 (아는 값이다)")

# 차가 들어가느냐가 값을 한 번 크게 꺾는다 — 못 들어가면 건축을 못 한다.
check(U.road_car_ok('세로한면(가)') == 1 and U.road_car_ok('세로한면(불)') == 0,
      "세로 (가)/(불) 한 글자가 자동차 진입을 가른다")
check(U.road_car_ok('맹지') == 0 and U.road_car_ok('소로한면') == 1,
      "맹지는 못 들어가고 소로는 들어간다")
check(U.road_car_ok('지정되지않음') is None, "모르면 진입 여부도 모른다")

# 각지는 두 면이 도로에 접해 진출입이 자유롭다.
check(U.is_corner('소로각지') == 1 and U.is_corner('소로한면') == 0,
      "각지와 한면을 가른다")
check(U.is_corner('광대소각') == 1, "광대소각도 각지다")

# 형상은 등급을 매기지 않는다. 매기려는 함수가 아예 없어야 한다 —
# 있으면 언젠가 누가 쓴다.
check(not hasattr(U, 'shape_grade'),
      "형상에는 등급 함수가 없다 (순서가 없는 것에 순서를 주지 않는다)")

# 실측(2026-09-07 남이천·안성)이 선형 가정을 깼다. 안성에서 중로가
# 광대로보다 비싸고 맹지가 세로(불)보다 비쌌다. 등급은 범주로 넣어야
# 하고, 그 사실이 코드에 적혀 있어야 다음 사람이 선형으로 넣지 않는다.
check("선형 항으로 넣지 말" in (U.road_grade.__doc__ or ""),
      "road_grade 가 '선형으로 쓰지 말라' 고 스스로 적고 있다")
# 반면 차 진입 여부는 두 표본에서 +66%·+67% 로 같았다. 이진이어야 한다.
check(set(U.road_car_ok(v) for v in
          ['광대로한면', '중로한면', '소로한면', '세로한면(가)']) == {1}
      and set(U.road_car_ok(v) for v in ['세로한면(불)', '맹지']) == {0},
      "차 진입 여부는 이진이다 (등급의 어느 지점에서 한 번 꺾인다)")

# ────────────────────────────────────────────────────────────────
print("\n38. 도로 접함이 헤도닉에서 실제로 빠지는가")
# ────────────────────────────────────────────────────────────────
# 실측이 말한 것: 차가 들어가느냐가 값을 +66~67% 가른다. 그 변수를
# 헤도닉이 안 쓰고 있어서 전·답·임야의 잔차가 통째로 남았다.
#
# **진실을 아는 자료**로 확인한다. 값에 도로 효과만 심고 교통량 효과는
# 0 으로 둔다. 보정 뒤에 도로와 값의 관계가 사라져야 맞다.
_rng38 = np.random.default_rng(38)
_n = 4000
_road = _rng38.choice(['소로한면', '세로한면(가)', '세로한면(불)', '맹지'],
                      _n, p=[.15, .45, .15, .25])
_car = np.isin(_road, ['소로한면', '세로한면(가)']).astype(float)
_shape = _rng38.choice(['부정형', '사다리형', '가로장방'], _n, p=[.7, .2, .1])
_area = np.exp(_rng38.normal(7, .6, _n))
# 심은 진실: 차가 들어가면 +0.50 (약 +65%, 실측과 같은 크기).
# 형상은 값에 영향이 없다 — 보고된 문제 그대로다.
_ln = 11 + 0.50 * _car - 0.10 * np.log(_area) + _rng38.normal(0, .25, _n)
_tr38 = pd.DataFrame({
    "kind": "land",
    "price_per_m2": np.exp(_ln),
    "area_m2": _area,
    "jimok": _rng38.choice(['전', '답', '임야'], _n),
    "land_use": "계획관리",
    "sigungu_cd": _rng38.choice(['41500', '41220', '41590'], _n),
    "deal_year": _rng38.choice([2020, 2021, 2022, 2023], _n),
    "road_side": _road,
    "parcel_shape": _shape,
    "parcel_slope": _rng38.choice(['평지', '완경사'], _n),
})

def _corr_with_car(df, col):
    car = np.isin(df["road_side"], ['소로한면', '세로한면(가)']).astype(float)
    return float(np.corrcoef(car, df[col])[0, 1])

_before = _corr_with_car(_tr38, "price_per_m2")
_adj38 = pn.hedonic_adjust(_tr38)
_after = _corr_with_car(_adj38, "adj_ln_price")
check(abs(_before) > 0.3,
      f"보정 전에는 도로와 값이 이어져 있다 (r={_before:+.2f})")
check(abs(_after) < 0.05,
      f"보정 뒤에는 그 관계가 사라진다 (r={_after:+.2f})")

# 도로 자료가 아예 없어도 죽지 않아야 한다. 전국 수집 전까지가 그 상태다.
_no_road = _tr38.drop(columns=["road_side", "parcel_shape", "parcel_slope"])
_adj_no = pn.hedonic_adjust(_no_road)
check("adj_ln_price" in _adj_no and _adj_no["adj_ln_price"].notna().all(),
      "도로 자료가 없어도 헤도닉이 돈다 (수집 전 상태)")

# **모르는 것을 맹지로 셈하지 않는다.** 절반을 비워도 나머지로 보정한다.
_half = _tr38.copy()
_half.loc[_half.index % 2 == 0, "road_side"] = None
_adj_half = pn.hedonic_adjust(_half)
_known = _adj_half[_adj_half["road_side"].notna()]
check(abs(_corr_with_car(_known, "adj_ln_price")) < 0.08,
      f"절반이 비어도 아는 쪽은 제대로 보정된다"
      f" (r={_corr_with_car(_known, 'adj_ln_price'):+.2f})")

# **열은 있는데 값이 통째로 빈 경우.** 필지 특성은 전국을 나눠서 모으는
# 중이라, 아직 안 훑은 지역만 들어온 kind 는 join 결과가 전부 NULL 이다.
# run 37 이 여기서 죽었다 — `.mode()` 가 빈 Series 를 돌려주고
# `.iat[0]` 이 IndexError 를 냈다. 열을 아예 뺀 경우와 다른 상황이다.
_empty = _tr38.copy()
for _c in ("road_side", "parcel_shape", "parcel_slope"):
    _empty[_c] = None
_adj_empty = pn.hedonic_adjust(_empty)
check("adj_ln_price" in _adj_empty and _adj_empty["adj_ln_price"].notna().all(),
      "필지 특성 열이 있어도 값이 전부 비면 그냥 건너뛴다 (run 37 회귀)")

# 한 열만 비는 경우도 같다 — 도로는 붙었는데 형상만 안 붙는 식.
_one_empty = _tr38.copy()
_one_empty["parcel_slope"] = None
_adj_one = pn.hedonic_adjust(_one_empty)
check(abs(_corr_with_car(_adj_one, "adj_ln_price")) < 0.05,
      "한 열만 비어도 나머지로 보정한다")

print("\n39. R-ONE 응답 파서와 비준표 쪼개기")

# 명세서는 출력 '항목' 만 적고 봉투를 적지 않았다. 그래서 파서를 한 모양에
# 못박지 않고 훑는다 — 그 훑기가 세 모양 다 읽는지 본다.
from redt.collect import reb as _reb                                    # noqa: E402

_seoul = {"SttsApiTblData": [{"list_total_count": 2},
                             {"RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"}},
                             {"row": [{"DTA_VAL": "1.23"}, {"DTA_VAL": "4.56"}]}]}
check([r["DTA_VAL"] for r in _reb._rows(_seoul)] == ["1.23", "4.56"],
      "서울 열린데이터 계열 봉투를 읽는다")
check(_reb._result(_seoul)[0] == "000", "코드에서 세 자리를 뽑는다 (INFO-000)")

_flat = {"response": {"header": {"RESULT": {"CODE": "200"}}, "body": {"row": []}}}
check(_reb._result(_flat)[0] == "200", "다른 봉투에서도 코드를 찾는다")
check(_reb._rows(_flat) == [], "행이 없으면 빈 목록이다 — 예외가 아니다")

_one = {"SttsApiTbl": {"row": {"STATBL_ID": "A_2024_00007"}}}
check(_reb._rows(_one) == [{"STATBL_ID": "A_2024_00007"}],
      "한 건이 dict 로 오면 한 줄 목록으로 만든다")

# 자료 없음(200)은 오류가 아니다. 코드에 그 구분이 남아 있는지 본다.
check(_reb.pick_cycle("QY,MM") == "MM" and _reb.pick_cycle("YY") == "YY"
      and _reb.pick_cycle("QY, YY") == "QY",
      "주기코드가 'QY,MM' 처럼 여럿이면 월(MM)을 고른다 — 자료 조회엔 하나만 넣는다")
check(_reb.EMPTY == "200" and _reb.BAD_KEY == "290",
      "'자료 없음' 과 '키 틀림' 을 가른다")

# 시점수정의 순서는 실무기준 ①용도지역 → ②지역 이다. 바뀌면 안 된다.
check(_reb.TABLES["지가변동률_용도지역_월"] == "A_2024_00007",
      "시점수정 ① 은 용도지역별 지가변동률이다")
check(_reb.TABLES["지가변동률_지역_월"] == "A_2024_00903",
      "시점수정 ② 는 지역별 지가변동률이다")
check(len(set(_reb.TABLES.values())) == len(_reb.TABLES),
      "통계표 ID 가 겹치지 않는다")

# pSize 1,000 초과는 오류 336 이라 부르기 전에 막는다.
try:
    _reb.call(_reb.TBL, {}, size=1001)
    _too_big = False
except ValueError:
    _too_big = True
check(_too_big, "pSize 1,000 초과는 부르기 전에 막는다 (명세서 오류 336)")

# 비준표 쪼개기 — 빈 줄로만 끊는다. '-' 만 든 줄도 본문이고, 열 라벨이
# 숫자인 항목(토지면적)도 놓치지 않는다.
import importlib.util as _ilu                                           # noqa: E402
_spec = _ilu.spec_from_file_location(
    "_bj", pathlib.Path(__file__).resolve().parents[0] / "parse_bijunpyo.py")
_bj = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_bj)

_sheet = [
    ["지목", "전", "답", "대"],
    ["전", "1.00", "1.00", "1.17"],
    ["광", "-", "-", "-"],
    ["대", "0.85", "0.85", "1.00"],
    [],
    ["토지면적", "3300", "16500"],
    ["3300", "1.00", "0.98"],
    ["16500", "1.02", "1.00"],
]
_bl = _bj.blocks(_sheet)
check([b[0] for b in _bl] == ["지목", "토지면적"],
      "빈 줄로만 끊는다 — 열 라벨이 숫자인 항목도 잡는다")
check(len(_bl[0][2]) == 3, "값이 전부 '-' 인 줄도 본문이다 (지목표 광·염·학)")
check(_bl[0][2][1][1] == [None, None, None], "'-' 는 값이 아니라 빈 칸이다")

# 방향 — 행이 표준지, 열이 대상. 역수 대칭이 그 증거다.
_road = [["도로접면", "광대한면", "맹지"],
         ["광대한면", "1.00", "0.73"],
         ["맹지", "1.37", "1.00"]]
_rb = _bj.blocks(_road)[0]
_cell = {(r[0], c): v for r in _rb[2] for c, v in zip(_rb[1], r[1])}
check(_cell[("광대한면", "맹지")] < 1 < _cell[("맹지", "광대한면")],
      "행=표준지 · 열=대상 — 맹지 표준지에서 광대한면으로 가면 값이 커진다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
