"""필지 진단 또래 분포 — 백분위가 뜻대로 나오는가.

요구사항(2026-09-08): "해당 필지를 클릭하면 스파이더 차트를 통해
여러가지 인자들을 분석하여 어떤 방향이 좋을 지 판단할 수 있도록"
"(어떤 토지이든 나쁜 토지는 없다. 어떤 방향으로 개발할 지가 문제다)"

**점수를 만들지 않는다.** 이 검사가 지켜야 할 첫째가 그것이다 — 어딘가에
0~100 점 하나가 생기면 같은 필지가 물류창고에는 A급이고 전원주택에는
C급이라는 사실이 사라진다.
"""
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

tmp = pathlib.Path(tempfile.mkdtemp()) / "test.duckdb"
from redt import config as cfg                      # noqa: E402
cfg.DB_PATH = tmp
from redt import db                                 # noqa: E402
db.DB_PATH = tmp
import pandas as pd                                 # noqa: E402
from redt import parcelscore as ps                  # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


print("1. 사다리 — 화면과 내보내기가 같은 것을 써야 한다")
check(ps.shape_grade("가로장방형") == 4, "형상: 가로장방형 = 4")
check(ps.shape_grade("자루형") == 0, "형상: 자루형 = 0 (가장 쓰기 어렵다)")
check(ps.shape_grade("") is None, "모르는 것은 None (0 이 아니다)")
check(ps.slope_grade("평지") == 5 and ps.slope_grade("급경사") == 2, "지세")
# 국토계획법이 정해 둔 것을 순서로 옮긴 것이다. 우리가 추정한 값이 아니다.
check(ps.zone_grade("계획관리지역") == 5 > ps.zone_grade("보전관리지역"),
      "개발 여지: 계획관리 > 보전관리")
check(ps.zone_grade("농림지역") == 1, "농림 = 1")
# 형상만 있고 지세를 모르면 형상만 쓴다. 하나가 없다고 축을 통째로
# 버리면 조사가 덜 된 필지가 늘 빈 별이 된다.
check(ps.land_grade("정방형", None) == 5, "한쪽만 있으면 그것만 쓴다")
check(ps.land_grade(None, None) is None, "둘 다 없으면 None")

print()
print("2. 누적 비율 — 같은 등급은 그 칸의 한가운데")
# 등급 5 가 둘, 등급 0 이 여덟이면 등급 5 의 백분위는 (8 + 2/2)/10 = 0.9
cum = ps._cum({0: 8, 5: 2})
check(abs(cum[5] - 0.9) < 1e-9, f"등급 5 → 0.9 ({cum[5]})")
check(abs(cum[0] - 0.4) < 1e-9, f"등급 0 → 0.4 (그 칸의 한가운데, {cum[0]})")
check(len(cum) == 6, "0~5 여섯 칸을 늘 낸다")

print()
print("3. 또래 분포를 실제 자료에서 만든다")
rows = []
# 안성 계획관리 40건 — 도로접이 골고루, 공시지가가 1만~40만.
for i in range(40):
    rows.append(dict(
        trade_id=f"A{i}", kind="land", sigungu_cd="41550", sigungu="안성시",
        umd="공도읍", jibun=str(i), land_use="계획관리지역",
        deal_year=2025, lat=37.0 + i * 0.001, lon=127.2,
        price_per_m2=100000.0, area_m2=1000.0, is_cancelled=False))
# 농림 5건 — 또래로는 너무 얇다 (MIN_PEER 30 미만)
for i in range(5):
    rows.append(dict(
        trade_id=f"N{i}", kind="land", sigungu_cd="41550", sigungu="안성시",
        umd="공도읍", jibun=f"n{i}", land_use="농림지역",
        deal_year=2025, lat=37.1, lon=127.3,
        price_per_m2=50000.0, area_m2=1000.0, is_cancelled=False))

ROADS = ["맹지", "세로한면(불)", "세로한면(가)", "소로한면", "중로한면", "광대로한면"]
parcels, links = [], []
for i in range(40):
    parcels.append(dict(
        pnu=f"P{i}", sigungu_cd="41550", jimok="전", land_use="계획관리지역",
        use_situation="전", area_m2=1000.0,
        road_side=ROADS[i % len(ROADS)],
        shape="가로장방형" if i % 2 else "부정형",
        slope="평지" if i % 3 else "급경사",
        official_price=10000.0 * (i + 1), stdr_year=2025))
    links.append(dict(trade_id=f"A{i}", pnu=f"P{i}"))
for i in range(5):
    parcels.append(dict(
        pnu=f"Q{i}", sigungu_cd="41550", jimok="답", land_use="농림지역",
        use_situation="답", area_m2=1000.0, road_side="맹지",
        shape="부정형", slope="평지", official_price=5000.0, stdr_year=2025))
    links.append(dict(trade_id=f"N{i}", pnu=f"Q{i}"))

# 교통 — 영업소 하나, 화물 일평균 1만대. 앞 20건은 1km, 뒤 20건은 8km.
tolls = [dict(tollgate_id="T1", name="남이천", lat=37.0, lon=127.2)]
traffic = [dict(tollgate_id="T1", year=2025, vehicle_type=3, direction="all",
                volume=3650000, avg_daily=10000.0, source="tcs",
                unit_type="tollgate", match_km=0.0)]
tlinks = [dict(trade_id=f"A{i}", tollgate_id="T1",
               distance_km=1.0 if i < 20 else 8.0,
               band="0-1" if i < 20 else "5-10", is_nearest=True)
          for i in range(40)]

with db.connect() as con:
    db.upsert(con, "trade", pd.DataFrame(rows))
    db.upsert(con, "parcel", pd.DataFrame(parcels))
    db.upsert(con, "trade_parcel", pd.DataFrame(links))
    db.upsert(con, "tollgate", pd.DataFrame(tolls))
    db.upsert(con, "traffic", pd.DataFrame(traffic))
    db.upsert(con, "trade_tollgate_link", pd.DataFrame(tlinks))

got = ps.build([("계획관리", "계획관리"), ("농림", "농림")])

peers = got["peers"]
check("41550|계획관리" in peers, f"시군구 또래가 생긴다 — {sorted(peers)[:4]}")
check("41|계획관리" in peers and "*|계획관리" in peers,
      "시도·전국 단계도 함께 만든다 (또래가 얇을 때 물러날 곳)")
me = peers["41550|계획관리"]
check(me["n"] == 40, f"또래 수 — {me['n']}")

# 도로접: 여섯 등급이 고르게 섞였으니 광대로(5)가 위쪽에 와야 한다.
check(me["road"][5] > me["road"][0],
      f"넓은 길이 위쪽 백분위 — 광대 {me['road'][5]} vs 맹지 {me['road'][0]}")
check(0 < me["road"][0] < 1 and 0 < me["road"][5] < 1,
      "백분위는 0~1 사이")

# 공시지가 1만~40만이 고르므로 중앙(50%)이 20만 언저리여야 한다.
check(len(me["price"]) == 11, f"분위 경계 11개 — {len(me['price'])}")
check(190000 <= me["price"][5] <= 215000,
      f"공시지가 중앙값이 자료와 맞는다 — {me['price'][5]:,.0f}")

# 교통: 1km 짜리(중력 1만/1²=10,000)와 8km 짜리(1만/64≈156)가 갈려야 한다.
check(me["traffic"][0] < me["traffic"][-1] / 10,
      f"가까운 IC 와 먼 IC 가 갈린다 — {me['traffic'][0]:,.0f} ~ {me['traffic'][-1]:,.0f}")

# **얇은 또래는 시군구 단계에 안 남긴다.** 다섯 건으로 만든 백분위는
# 자료가 아니라 우연이다.
check(peers.get("41550|농림", {}).get("n", 0) < ps.MIN_PEER
      or "41550|농림" not in peers,
      "다섯 건짜리 또래는 신뢰할 수 없다고 표시되거나 빠진다")

# 개발 여지 — 시군구 안에서 계획관리가 농림보다 위여야 한다.
zp = got["zone_pct"]["41550"]
check(zp[5] > zp[1], f"계획관리(5)가 농림(1)보다 위 — {zp[5]} vs {zp[1]}")

print()
print("4. 점수를 만들지 않는다")
blob = json.dumps(got, ensure_ascii=False)
# 축이 다섯이고, 어디에도 '총점'·'등급' 같은 단일 값이 없어야 한다.
check(len(got["axes"]) == 5, f"축이 다섯 — {[a['key'] for a in got['axes']]}")
check(not any(k in got for k in ("score", "total", "grade", "rank")),
      "합산 점수를 안 낸다 (있으면 땅박사가 되고 우리는 환경 자료가 없다)")
check(all("desc" in a and len(a["desc"]) > 10 for a in got["axes"]),
      "축마다 무엇을 잰 것인지 적는다")
check(got["traffic"]["radius_km"] == ps.TRAFFIC_RADIUS_KM,
      "화면이 같은 반경으로 계산하도록 내보낸다")
check(json.loads(blob) == got, "브라우저가 읽을 수 있는 JSON 이다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
