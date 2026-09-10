"""필지 특성(도로접·형상·지세)이 화면 자료까지 흘러가는지 검사한다.

요구사항(2026-09-07): "실거래 내용에 도로접하거나 토지의 모양등을
알 수 있는 지도 확인해 주세요." · "도로를 접하는 가가 제일 중요합니다."

실거래 API 는 그 셋을 하나도 주지 않는다. 브이월드 토지특성에서 따로
받아 parcel 에 담고 trade_parcel 로 이어 놓았는데, **거기까지 오는 것과
화면에 뜨는 것은 다른 문제다.** 조인 한 줄이 빠져도 아무 데서도 안 죽고
말풍선만 조용히 비어 있게 된다. 그 침묵을 여기서 깬다.
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
from redt import webexport as wx                    # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


# ── 자료 ──
# 세 건을 넣는다. 필지가 붙은 것 둘(차 진입 되는 것 · 맹지), 안 붙은
# 것 하나. 마지막이 중요하다 — 아직 전국을 다 안 훑었으므로 화면에
# 실제로 가장 많이 오는 모양이 그것이다.
trades = pd.DataFrame([
    dict(trade_id="A", kind="land", lat=37.1, lon=127.2, deal_year=2023,
         deal_month=4, price_per_m2=300000.0, price_krw=3.0e8, area_m2=1000.0,
         sido="경기도", sigungu="안성시", umd="공도읍", jibun="123-4",
         jimok="답", land_use="계획관리", geocode_level="parcel",
         is_cancelled=False),
    dict(trade_id="B", kind="land", lat=37.2, lon=127.3, deal_year=2023,
         deal_month=6, price_per_m2=100000.0, price_krw=1.0e8, area_m2=1000.0,
         sido="경기도", sigungu="안성시", umd="공도읍", jibun="55",
         jimok="전", land_use="생산관리", geocode_level="parcel",
         is_cancelled=False),
    dict(trade_id="C", kind="land", lat=37.3, lon=127.4, deal_year=2023,
         deal_month=9, price_per_m2=200000.0, price_krw=2.0e8, area_m2=1000.0,
         sido="경기도", sigungu="이천시", umd="마장면", jibun="9",
         jimok="임야", land_use="자연녹지", geocode_level="parcel",
         is_cancelled=False),
])
parcels = pd.DataFrame([
    dict(pnu="4155025300100230004", sigungu_cd="41550", jimok="답",
         land_use="계획관리", use_situation="전", area_m2=1000.0,
         road_side="세로한면(가)", shape="부정형", slope="평지",
         official_price=120000.0, stdr_year=2023),
    dict(pnu="4155025300100550000", sigungu_cd="41550", jimok="전",
         land_use="생산관리", use_situation="전", area_m2=1000.0,
         road_side="맹지", shape="사다리형", slope="완경사",
         official_price=40000.0, stdr_year=2023),
])
links = pd.DataFrame([
    dict(trade_id="A", pnu="4155025300100230004"),
    dict(trade_id="B", pnu="4155025300100550000"),
])

with db.connect() as con:
    db.upsert(con, "trade", trades)
    db.upsert(con, "parcel", parcels)
    db.upsert(con, "trade_parcel", links)

print("1. 표본을 뽑은 뒤에 필지를 붙인다")
with db.connect(read_only=True) as con:
    got = con.execute(wx._trade_query(wx.TRADE_WHERE, 100)).fetchdf()
check(len(got) == 3, f"세 건이 다 남는다 — 조인이 건수를 줄이지 않는다 ({len(got)}건)")
by_id = {r.trade_id: r for r in got.itertuples(index=False)}
check(by_id["A"].road_side == "세로한면(가)", "도로접면이 붙는다")
check(by_id["A"].parcel_shape == "부정형", "형상이 붙는다")
check(by_id["A"].parcel_slope == "평지", "지세가 붙는다")
check(float(by_id["A"].official_price) == 120000.0, "공시지가가 붙는다")
# **안 붙은 거래도 남아야 한다.** LEFT JOIN 이 아니면 아직 안 훑은
# 지역의 거래가 지도에서 통째로 사라진다 — 그것이 지금은 대부분이다.
check(by_id["C"].road_side == "", "필지가 없는 거래는 빈 값으로 남는다")

print("\n2. 도로 진입 여부는 파이썬에서 한 번만 판정한다")
# 화면이 '세로한면(가)' 와 '세로한면(불)' 을 문자열로 다시 가르게 두면
# 규칙이 두 군데로 갈라진다. 한 글자 차이다.
withu = wx._with_usage(got)
byu = {r.trade_id: r for r in withu.itertuples(index=False)}
check(byu["A"].car_ok == "Y", "세로한면(가)는 차가 들어간다")
check(byu["B"].car_ok == "N", "맹지는 못 들어간다")
check(byu["C"].car_ok == "", "안 훑은 것은 'N' 이 아니라 빈 값이다")

print("\n3. 화면 자료에 실려 나간다")
recs = {r["jibun"]: r for r in wx._trade_records(withu)}
check(recs["123-4"].get("road_side") == "세로한면(가)", "말풍선이 도로접면을 받는다")
check(recs["123-4"].get("parcel_shape") == "부정형", "말풍선이 형상을 받는다")
check(recs["123-4"].get("official_price") == 120000, "공시지가는 정수로 줄인다")
# 빈 칸은 아예 안 싣는다. 아직 대부분의 거래가 그 상태라, 여기서
# null 을 또박또박 적으면 연도 파일이 통째로 무거워진다.
check("road_side" not in recs["9"], "안 훑은 거래는 빈 칸을 싣지 않는다")
check("car_ok" not in recs["9"], "car_ok 도 마찬가지다")
check(json.dumps(list(recs.values())), "브라우저가 읽을 수 있는 JSON 이다")

print("\n4. meta 가 '조사 안 됨' 을 감추지 않는다")
# 이것을 안 세면 화면이 '맹지가 1건뿐' 이라고 말하게 된다.
# 사실은 '2건만 조사됐다' 다.
from redt.usage import road_car_ok                  # noqa: E402
with db.connect(read_only=True) as con:
    rows = con.execute(f"""
        SELECT coalesce(pc.road_side, '') AS road_side, count(*) AS n
        FROM trade t
        LEFT JOIN trade_parcel tp ON tp.trade_id = t.trade_id
        LEFT JOIN parcel pc ON pc.pnu = tp.pnu
        WHERE t.kind = 'land' AND {wx._trade_where('t')}
        GROUP BY 1
    """).fetchdf()
mix = {wx.ROAD_OK: 0, wx.ROAD_NO: 0, wx.ROAD_UNKNOWN: 0}
for r in rows.itertuples(index=False):
    c = road_car_ok(r.road_side)
    mix[wx.ROAD_UNKNOWN if c is None else wx.ROAD_OK if c else wx.ROAD_NO] += int(r.n)
check(mix == {wx.ROAD_OK: 1, wx.ROAD_NO: 1, wx.ROAD_UNKNOWN: 1},
      f"세 칸이 1건씩이다 — {mix}")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
