"""관청 좌표 — 어느 것을 고르고, 어디까지 화면에 흘러가는가.

사장님 지시(2026-09-07): "인구 표시 원의 중심은 도청/시청/구청/군청
소재지가 중심이 되도록 수정해 주세요."

탐침(run 39)이 브이월드 장소검색으로 9곳 중 9곳을 찾았다. 그런데
**찾는 것과 맞게 고르는 것은 다른 문제다.** 두 가지가 실제로 왔다.

  1위: 수원시-장안구청종합구민회관보건소
       분류 기초화학물질제조업 > … > 산업용가스제조업

동구·서구·남구는 전국에 흩어져 있어 이름만으로는 못 가른다. 둘 다
대표점으로 푸는데, 그 고르는 규칙이 조용히 틀리면 원이 옆 도(道)에
가서 찍히고 아무 데서도 안 죽는다.
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
from redt.collect import office as of               # noqa: E402
from redt import webexport as wx                    # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


print("1. 관청 이름을 어떻게 묻는가")
# '수원시 장안구' 를 그대로 물으면 1위가 엉뚱한 것이 온다. 실제 간판인
# '장안구청' 으로 묻는다 — 어느 장안구인지는 대표점이 가른다.
check(of.office_name("수원시 장안구") == "장안구청", "구는 마지막 마디로 묻는다")
check(of.office_name("안성시") == "안성시청", "시는 그대로")
check(of.office_name("무안군") == "무안군청", "군도 그대로")
check(of.office_name("경기도") == "경기도청", "도청도 같은 규칙")

print("\n2. 분류가 잘못 붙은 1위를 집지 않는다")
# run 39 가 실제로 만난 것. 1위는 분류가 '산업용가스제조업' 이었고
# 2위가 '장안구청' 이었다. 좌표는 둘이 같았다.
CANDS = [
    {"name": "수원시-장안구청종합구민회관보건소",
     "category": "기초화학물질제조업 > 기초무기화학물질제조업 > 산업용가스제조업",
     "road_addr": "경기도 수원시 장안구 송원로 101",
     "lat": 37.30397, "lon": 127.01012},
    {"name": "장안구청", "category": "지방행정기관 > 구청",
     "road_addr": "경기도 수원시 장안구 송원로 101",
     "lat": 37.30390, "lon": 127.01020},
]
got = of.pick(CANDS, (37.304, 127.011))
check(got and got["name"] == "장안구청", f"지방행정기관을 먼저 본다 — {got and got['name']}")

# 분류가 붙은 것이 하나도 없으면 전체에서 다시 고른다. 안 그러면
# 분류가 잘못 붙은 관청은 영영 못 찾는다.
only_bad = [CANDS[0]]
got2 = of.pick(only_bad, (37.304, 127.011))
check(got2 and got2["name"].startswith("수원시-장안구청"),
      "분류가 다 이상하면 그래도 가장 가까운 것을 집는다")

print("\n3. 같은 이름의 구는 대표점이 가른다")
# 동구는 전국에 흩어져 있다. 이름만으로는 못 가른다.
DONGGU = [
    {"name": "대구광역시동구청", "category": "지방행정기관 > 구청",
     "road_addr": "대구광역시 동구 아양로 207", "lat": 35.8866, "lon": 128.6353},
    {"name": "광주광역시동구청", "category": "지방행정기관 > 구청",
     "road_addr": "전남광주통합특별시 동구 서남로 1", "lat": 35.1459, "lon": 126.9230},
    {"name": "부산광역시동구청", "category": "지방행정기관 > 구청",
     "road_addr": "부산광역시 동구 초량중로 62", "lat": 35.1294, "lon": 129.0453},
]
gw = of.pick(DONGGU, (35.14, 126.91))       # 광주 동구 대표점 근처
check(gw and gw["name"] == "광주광역시동구청",
      f"광주 대표점이면 광주 동구청 — {gw and gw['name']}")
dg = of.pick(DONGGU, (35.89, 128.63))       # 대구 동구 대표점 근처
check(dg and dg["name"] == "대구광역시동구청",
      f"대구 대표점이면 대구 동구청 — {dg and dg['name']}")

# **너무 멀면 아예 안 집는다.** 조용히 틀린 좌표를 쓰는 것보다 빈 것이
# 낫다 — 빈 것은 화면이 '대표점에 찍었다' 고 말하지만 틀린 좌표는
# 아무 말도 안 한다.
far = of.pick(DONGGU, (37.60, 127.00))      # 서울 어딘가
check(far is None, f"{of.MAX_KM:g}km 넘게 떨어지면 집지 않는다 — {far}")

print("\n4. 시도 이름은 관청 주소에서 온다")
# 실거래 API 응답에 시도가 없어서 trade.sido 는 늘 빈 값이다
# (collect/rtms.py 가 그렇게 적어 두었다). 관청 주소가 유일한 출처다.
check(of.sido_of("경기도 안성시 봉산동 31-3") == "경기도", "첫 마디가 시도 이름이다")
check(of.sido_of("전남광주통합특별시 동구 서남로 1") == "전남광주통합특별시",
      "통합 시도 이름도 그대로 받는다")
check(of.sido_of("") == "", "주소가 없으면 빈 값")

print("\n5. 화면 자료까지 흘러가는가")
trades = pd.DataFrame([
    dict(trade_id=f"T{i}", kind="land", sigungu_cd=cd, sigungu=nm, umd=umd,
         lat=lat, lon=lon, deal_year=2025, price_per_m2=100000.0,
         area_m2=1000.0, is_cancelled=False)
    for i, (cd, nm, umd, lat, lon) in enumerate([
        ("41111", "수원시 장안구", "정자동", 37.304, 127.011),
        ("41113", "수원시 권선구", "권선동", 37.241, 126.971),
        ("47940", "울릉군", "울릉읍", 37.484, 130.905),
    ])
])
offices = pd.DataFrame([
    dict(level="gu", key="41111", label="수원시 장안구", name="장안구청",
         category="지방행정기관 > 구청", sido="경기도",
         road_addr="경기도 수원시 장안구 송원로 101",
         lat=37.3040, lon=127.0101, dist_km=0.4,
         source="vworld:search", fetched_at=of.now()),
    dict(level="si", key="수원시", label="수원시", name="수원시청",
         category="지방행정기관", sido="경기도",
         road_addr="경기도 수원시 팔달구 효원로 241",
         lat=37.2634, lon=127.0287, dist_km=3.1,
         source="vworld:search", fetched_at=of.now()),
    dict(level="sido", key="경기도", label="경기도", name="경기도청",
         category="지방행정기관", sido="경기도",
         road_addr="경기도 수원시 팔달구 효원로 1",
         lat=37.2750, lon=127.0092, dist_km=8.0,
         source="vworld:search", fetched_at=of.now()),
])
years = pd.DataFrame([
    dict(sigungu_cd=cd, year=2025, metric="population", value=v, source="t")
    for cd, v in [("41111", 280000), ("41113", 370000), ("47940", 10000)]
])
with db.connect() as con:
    db.upsert(con, "trade", trades)
    db.upsert(con, "office", offices)
    db.upsert(con, "region_year", years)

regions = wx._regions()
by_name = {r["name"]: r for r in regions}
check(len(regions) == 3, f"세 시군구가 다 나온다 ({len(regions)})")
check(by_name["수원시 장안구"].get("office_lat") == 37.304,
      "구청 좌표가 붙는다")
# **못 받은 곳도 빠지면 안 된다.** 관청이 없다고 시군구가 사라지면
# 지도에서 인구 원이 통째로 없어진다.
check("울릉군" in by_name and "office_lat" not in by_name["울릉군"],
      "관청을 못 받은 시군구도 남고, 빈 칸은 안 싣는다")
# 시도 이름은 여기서만 온다 — trade.sido 는 늘 비어 있다.
check(by_name["수원시 장안구"]["sido"] == "경기도", "시도 이름이 관청에서 온다")
check(by_name["울릉군"]["sido"] == "", "관청이 없으면 시도 이름도 빈 값")
check(by_name["수원시 장안구"]["parent"] == "수원시", "시 아래 구는 parent 를 갖는다")

ro = wx._region_offices()
check(ro.get("sido", {}).get("경기도") == [37.275, 127.0092],
      f"도청이 meta 로 나간다 — {ro.get('sido')}")
check(ro.get("si", {}).get("수원시") == [37.2634, 127.0287],
      f"시청도 나간다 — {ro.get('si')}")
# 구 단위는 regions.json 의 각 행이 들고 있으므로 여기 실으면 두 번이다.
check("gu" not in ro, "구 단위는 여기 안 싣는다 (행이 이미 들고 있다)")
check(json.dumps(ro, ensure_ascii=False), "브라우저가 읽을 수 있는 JSON 이다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
