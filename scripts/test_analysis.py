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

# 사장님이 '수도권제2순환고속도로에 마도IC가 있습니다' 라고 하셨는데
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
# 달라지면 사장님이 자료를 못 믿는다.
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

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
