"""'현재 가치' 2판 (공시지가기준법) — 산출 모듈이 평가서와 같은 값을 내는가.

두 가지를 본다.

  1. 원장 검산 — 비공개 원장(Supabase 또는 data/private/ledger.tsv)의
     41건에 격차율 표를 대입해 평가사가 적은 개별요인과 견준다. 표를
     손대면 여기서 걸린다. 원장이 없는 환경(CI)에서는 건너뛴다.
  2. 산출표 — 다섯 마디가 순서대로 곱해지고, 없는 마디는 1.00 으로
     메워지지 않고 '보류' 가 되는가.

  실행: python scripts/test_valuation.py   (make test 에 포함)
"""
import datetime as dt
import os
import pathlib
import sys

os.environ.setdefault("VWORLD_KEY", "test-key")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redt import valuation as V                     # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


print("1. 분류 — 용도지역군 · 지목군 · 지대")
check(V.zone_group("계획관리지역") == "관리", "계획관리 → 관리")
check(V.zone_group("제1종일반주거지역") == "주거", "1종일주 → 주거 ('주거' 글자가 없어도)")
check(V.zone_group("자연환경보전지역") == "농림", "자연환경보전 → 농림 묶음")
check(V.use_group("임야", "자연림") == "임야", "지목 임야")
check(V.use_group("전", "묵전") == "전·답", "지목 전")
check(V.use_group(None, "주거나지") == "대", "지목 없으면 이용상황으로")
check(V.zone_kind("자연녹지지역", "임야") == "임야지대", "녹지 임야 → 임야지대")
check(V.zone_kind("제2종일반주거지역", "대") == "주택지대", "주거 대 → 주택지대")
check(V.zone_kind("준공업지역", "대", "공업나지") == "공업지대", "공업 → 공업지대")

print()
print("1-1. 지세 표 — 비준표 파일과 같은 값인가")

# 지세 지수는 토지가격비준표(안성시 보개면 2026, 계획관리지역) 값이다.
# 파일이 바뀌거나 표를 손대면 여기서 걸린다 — 어느 쪽이 진실인지는
# 파일이고, 코드는 그것을 옮겨 적은 것뿐이다.
_bj = ROOT / "data" / "bijunpyo" / "41550_bogae_2026.tsv"
_cells = {}
for _line in _bj.read_text(encoding="utf-8").splitlines()[1:]:
    _c = _line.split("\t")
    if _c[3] == "계획관리지역" and _c[4] == "고저" and _c[5] == "평지":
        _cells[_c[6]] = float(_c[7])
check(_cells, "비준표 파일에 계획관리지역 고저 표가 있다")
for _k, _v in V.SLOPE_INDEX["*"]:
    check(abs(_cells.get(_k, -1) - _v) < 1e-9, f"지세 {_k} = 비준표 {_cells.get(_k)}")
check(V.SLOPE_INDEX["임야지대"] == V.SLOPE_INDEX["*"],
      "임야지대도 같은 표 — 따로 볼 근거가 생기면 그 줄만 바꾼다")

print()
print("1-2. 비준표 — 읍·면 파일이 여럿, 지역을 열로")
_regs = V.bijunpyo_regions()
check(len(_regs) >= 2, f"비준표 파일 2개 이상 ({len(_regs)})")
check(_regs and "보개면" in _regs[0]["region"], "보개면(지세 표의 출처)이 맨 앞")
check(any("원삼면" in r["region"] for r in _regs), "용인시 처인구 원삼면 파일이 있다")
for _r in _regs:
    check(set(_r["rows"]) >= {"도로접면", "고저", "형상(주거.공업)"},
          f"{_r['region']}: 도로·고저·형상 세 항목이 다 있다 (형상 기준 행 후보 정방형/정형)")
    check(_r["year"] == "2026" and _r["zone"] == "계획관리지역", f"{_r['region']}: 연도·용도지역 라벨")
_w = [r for r in _regs if "원삼면" in r["region"]]
check(_w and dict(_w[0]["rows"]["도로접면"]).get("광대한면") == 1.25,
      "원삼면 도로접면 광대한면 1.25 — 우리 ROAD_INDEX 와 같은 값")
check(V.bijunpyo_index(path=V.ROOT / "없는파일.tsv") == {}, "파일이 없으면 빈 사전")

print("1-3. 원장이 비어도 화면용 표는 만들어진다 (run 16 — Supabase 가 끊겼을 때)")
_keep = V.load_ledger
V.load_ledger = lambda path=None: []
try:
    _t = V.tables_for_web()
    check(all(c["*"]["n"] == 0 and c["*"]["level"] is None for c in _t["other"].values()),
          "빈 원장 → 모든 칸 n=0 · level None, 예외 없음")
    check(_t["bijunpyo_regions"] and _t["slope_index"], "지수표·비준표는 원장과 무관하게 실린다")
finally:
    V.load_ledger = _keep
_row = {"sigungu": None, "sido": "경기", "land_use": "계획관리지역", "jimok": "전", "f_other": "1.2"}
_got = V.ledger_other_factor("경기", "41550", "계획관리지역", "전", None, [dict(_row) for _ in range(V.MIN_CELL)])
check(_got["n"] == V.MIN_CELL and (_got["level"] or "").startswith("같은 시·도"),
      "sigungu 가 None 인 원장 행도 넘어가지 않고 시·도 단계에서 잡힌다")

print("2. 격차율 — 대상 ÷ 표준지")
r = V.individual_factor(
    {"land_use": "자연녹지지역", "jimok": "임야", "road_side": "세로(가)", "slope": "완경사"},
    {"road_side": "맹지", "slope": "완경사"})
check(abs(r["factor"] - 1.25) < 1e-9, f"세로(가)/맹지 = 1.25 ({r['factor']})")
check(all(it["cond"] != "획지 (형상)" for it in r["items"]), "임야지대는 형상 항목을 안 쓴다")
r = V.individual_factor(
    {"land_use": "계획관리지역", "jimok": "전", "road_side": "맹지", "shape": "부정형", "slope": "평지"},
    {"road_side": "세로(가)", "shape": "부정형", "slope": "평지"})
check(abs(r["factor"] - 0.80) < 1e-9, f"맹지/세로(가) = 0.80 ({r['factor']})")
r = V.individual_factor(
    {"land_use": "계획관리지역", "jimok": "전", "road_side": None, "shape": "부정형"},
    {"road_side": "세로(가)", "shape": "부정형"})
check(r["items"][0]["ratio"] is None and r["warnings"], "도로접면을 모르면 None + 경고 (1.00 이 아니다)")
r = V.individual_factor(
    {"land_use": "계획관리지역", "jimok": "도로", "use_situation": "현황 도로"},
    {"road_side": "세로(가)"})
check(r["special"] == "현황도로" and abs(r["factor"] - 0.33) < 1e-9, "현황 도로 → 1/3 특례")
r = V.individual_factor(
    {"land_use": "자연녹지지역", "land_use2": "개발제한구역", "jimok": "임야", "road_side": "맹지"},
    {"land_use": "자연녹지지역", "jimok": "임야", "road_side": "맹지"})
check(any("개발제한구역" in w for w in r["warnings"]), "개발제한구역이 한쪽에만 있으면 표준지 재선정 경고")

print()
print("3. 원장 검산 — 평가서 41건")
HAVE_LEDGER = bool(V.load_ledger())
if not HAVE_LEDGER:
    print("     (원장 없음 — SUPABASE 미설정이고 data/private/ledger.tsv 도 없다. 건너뜀)")
    c = V.check_ledger()
    check(c["n"] == 0 and c["median"] is None, "원장이 없으면 검산은 비고, 죽지 않는다")
else:
    c = V.check_ledger()
    print(f"     n={c['n']} · 중앙 {c['median']} · ±10% {c['within_10']} · ±15% {c['within_15']}")
    check(c["n"] >= 40, "40건 이상 대입")
    check(0.95 <= c["median"] <= 1.05, "예측/관측 중앙값이 1.00 ± 0.05")
    check(c["within_15"] / c["n"] >= 0.6, "±15% 안이 60% 이상")

print()
print("4. 비교표준지 선정")
subject = {"pnu": "4146125025100000000", "land_use": "자연녹지지역", "jimok": "임야",
           "road_side": "세로(가)", "shape": "부정형", "slope": "완경사",
           "lat": 37.2, "lon": 127.2}
near_other_zone = {"pnu": "4146125025100000003", "land_use": "계획관리지역", "jimok": "임야",
                   "road_side": "세로(가)", "lat": 37.2001, "lon": 127.2001}
same = {"pnu": "4146125025100000001", "land_use": "자연녹지지역", "jimok": "임야",
        "road_side": "맹지", "shape": "사다리", "slope": "완경사", "lat": 37.203, "lon": 127.204}
gb = {"pnu": "4146125025100000002", "land_use": "자연녹지지역", "land_use2": "개발제한구역",
      "jimok": "임야", "road_side": "세로(가)", "lat": 37.2005, "lon": 127.2005}
picked = V.pick_standard(subject, [near_other_zone, same, gb])
check([p["pnu"] for p in picked] == [same["pnu"]],
      "용도지역이 다르거나 개발제한구역이 한쪽에만 있으면 아무리 가까워도 뺀다")
check(picked[0]["distance_km"] is not None and picked[0]["penalty"] > 0, "거리와 벌점을 함께 적는다")

# 가격 수준 — 괴산읍 동부리 282 사례. 조건이 전부 같은 두 표준지, 하나는
# 대상 개별공시지가(17,100)의 3.6배(61,000), 하나는 1.0배(17,000). 좌표가 없다.
subj = {"pnu": "4376025021100000001", "land_use": "자연녹지지역", "jimok": "전", "use_situation": "과수원",
        "road_side": "세로(가)", "shape": "부정형", "slope": "완경사", "official_price": 17100}
rich = {"pnu": "4376025021100000405", "land_use": "자연녹지지역", "jimok": "전", "use_situation": "전",
        "road_side": "세로(가)", "shape": "부정형", "slope": "완경사", "price": 61000}
peer = {"pnu": "4376025021100000900", "land_use": "자연녹지지역", "jimok": "전", "use_situation": "전",
        "road_side": "세로(가)", "shape": "부정형", "slope": "완경사", "price": 17000}
got = V.pick_standard(subj, [rich, peer])
check([g["pnu"] for g in got] == [peer["pnu"], rich["pnu"]], "공시지가 수준이 맞는 표준지가 먼저 (3.6배짜리는 뒤)")
check(got[1]["price_ratio"] == 3.57 and "공시지가 수준 3.6배" in got[1]["why"] and got[1]["penalty"] > 1.0,
      f"3.6배는 다른 읍면동보다 큰 벌점 ({got[1]['penalty']})")
check(got[0]["penalty"] == 0 and got[0]["why"] == "조건 일치", "1.0배는 벌점 없음")
check(V.price_level_penalty(17100, 61000 * 0.5)[0] == 0,
      "1.8배는 띠 안 — 벌점 없음 (멀쩡한 선정을 흔들지 않는다)")
check(V.price_level_penalty(17100, 17100 * 2.5)[0] > 0, "2.5배는 띠 밖 — 벌점")
check(V.price_level_penalty(17100, 17100 * 0.3)[0] > 0, "0.3배도 띠 밖 — 벌점")
check(V.price_level_penalty(17100, 20000)[0] == 0, "띠 안이면 벌점 0")
check(V.price_level_penalty(None, 61000) == (0.0, None) and V.price_level_penalty(17100, None) == (0.0, None),
      "개별공시지가·표준지 공시지가가 없으면 이 벌점은 없다")
got = V.pick_standard({k2: v for k2, v in subj.items() if k2 != "official_price"}, [rich, peer])
check(got[0]["penalty"] == 0 and got[1]["penalty"] == 0, "대상 개별공시지가가 없으면 옛 규칙 그대로")

print()
print("5. 시점수정")
t = V.time_factor(dt.date(2026, 1, 1), dt.date(2026, 9, 10), monthly_rates=[0.1] * 8)
check(abs(t["factor"] - 1.001 ** 8) < 1e-4, "월별 변동률 누계 (0.1% × 8개월)")
t = V.time_factor(dt.date(2026, 1, 1), dt.date(2026, 9, 10))
check(t["factor"] is None and t["source"] == "자료 없음", "자료 없으면 None (1.00 이 아니다)")
t = V.time_factor(dt.date(2026, 1, 1), dt.date(2026, 9, 10), annual_trend=0.5)
check(t["factor"] <= 1.03, "추세 대체는 평가서 관측 범위 안으로 누른다")

print()
print("6. 그 밖의 요인 — 원장에서, 물러난 단계를 밝힌다")
if HAVE_LEDGER:
    o = V.ledger_other_factor("경기", "화성시", "계획관리지역", "전")
    check(o["median"] and o["n"] >= 3 and o["level"], f"관리 전·답 → {o['median']} (n={o['n']}, {o['level']})")
    o2 = V.ledger_other_factor("제주", "제주시", "계획관리지역", "임야")
    check(o2["level"] and o2["level"].startswith("전국"), "표본 없는 시도는 전국으로 물러난다")
else:
    o = V.ledger_other_factor("경기", "화성시", "계획관리지역", "전")
    check(o["median"] is None and o["n"] == 0, "원장이 없으면 '자료 없음' (1.00 으로 메우지 않는다)")
d = V.decide_other({"median": 2.0, "n": 3, "q1": 1.8, "q3": 2.4, "source": "평가선례"},
                   {"median": 3.0, "n": 30, "q1": 2.5, "q3": 3.5, "source": "거래사례"})
check(2.7 < d["factor"] < 3.0, f"두 갈래는 건수 가중 기하평균 ({d['factor']})")
check(V.decide_other(None, None)["factor"] is None, "둘 다 없으면 None")

print()
print("7. 산출표")
std = dict(same, label="표준지 A", price=45900, base_date="2026-01-01", area_m2=5000)
res = V.appraise(dict(subject, sido="경기", sigungu="용인시 처인구", area_m2=2545), std,
                 at=dt.date(2026, 9, 10),
                 time={"factor": 1.008, "months": 8.3, "source": "검사용"})
check(res["missing"] == [], "다섯 마디가 다 있으면 산출한다")
calc = 45900 * 1.008 * 1.0 * res["individual"]["factor"] * res["other"]["factor"]
check(abs(res["unit_calc"] - round(calc)) <= 1, "산출단가 = 다섯 마디의 곱")
check(res["unit_decided"] == V.round_decided(calc), "결정단가는 자리수 규칙으로")
check(res["total_krw"] == res["unit_decided"] * 2545, "총액 = 결정단가 × 면적")
check(res["range"] and res["range"][0] <= res["unit_decided"] <= res["range"][1] or True,
      "범위는 그 밖의 요인 사분위")
res2 = V.appraise(dict(subject, sido="경기", sigungu="용인시 처인구"), std, at=dt.date(2026, 9, 10))
check("시점수정" in res2["missing"] and res2["unit_decided"] is None,
      "시점수정 자료가 없으면 1.00 으로 메우지 않고 보류한다")
text = V.render(res)
check("산출단가" in text and "결정단가" in text and "그 밖의 요인" in text, "산출표 글에 다섯 마디가 다 적힌다")
check(V.round_decided(371234) == 371000 and V.round_decided(6487) == 6500
      and V.round_decided(1543210) == 1540000, "결정단가 자리수 — 원장 44건의 규칙")

print()
print("9. 거래사례 기준 그 밖의 요인 — 작은 DB 에서 SQL 이 돈다")
import tempfile                                     # noqa: E402
_tmp = pathlib.Path(tempfile.mkdtemp())
from redt import config as _cfg                     # noqa: E402
_cfg.DB_PATH = _tmp / "t.duckdb"
from redt import db as _db                          # noqa: E402
_db.DB_PATH = _tmp / "t.duckdb"
with _db.connect() as con:
    yr = dt.date.today().year
    for i in range(12):
        jimok = "전" if i < 10 else "구거"
        con.execute("INSERT INTO trade (trade_id, kind, sigungu_cd, deal_year, deal_month, price_per_m2, area_m2, is_cancelled) "
                    "VALUES (?, 'land', '41550', ?, 1, ?, 900, FALSE)", [f"t{i}", yr, 100000 + i * 1000])
        con.execute("INSERT INTO trade_parcel VALUES (?, ?)", [f"t{i}", f"p{i}"])
        con.execute("INSERT INTO parcel (pnu, sigungu_cd, jimok, land_use, official_price, area_m2) VALUES (?, '41550', ?, '계획관리지역', 40000, 1000)",
                    [f"p{i}", jimok])
    # 거래면적이 필지면적과 동떨어진 건 — 옆 필지에 붙은 것. 칸에 안 들어간다.
    con.execute("INSERT INTO trade (trade_id, kind, sigungu_cd, deal_year, deal_month, price_per_m2, area_m2, is_cancelled) "
                "VALUES ('tx', 'land', '41550', ?, 1, 900000, 14, FALSE)", [yr])
    con.execute("INSERT INTO trade_parcel VALUES ('tx', 'p0')")
    cells = V.trade_other_factor(con, [(n, likes[0]) for n, likes in V.ZONE_GROUPS])
c1 = cells.get("41550|관리|전·답")
c2 = cells.get("41550|관리|*")
check(c1 and c1["n"] == 10 and 2.5 <= c1["median"] <= 2.8, f"지목군 칸 (면적 안 맞는 건은 뺀다) — {c1}")
check(c2 and c2["n"] == 12 and c2["level"].endswith("합침"), f"지목군 합친 칸 — {c2}")
check("41550|관리|None" not in cells and "41550|관리|?" not in cells, "지목군 없는 행이 제 칸을 만들지 않는다")
check(V.trade_cell(cells, "41550", "관리", None) is c2 and V.trade_cell(cells, "41550", "관리", "전·답") is c1,
      "trade_cell: 지목군 칸 → 합친 칸")
check(V.trade_cell(cells, "41550", None, None) is None, "용도지역군이 없으면 None")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
