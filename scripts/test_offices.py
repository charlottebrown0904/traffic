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
check(far is None, f"{of.MAX_KM['gu']:g}km 넘게 떨어지면 집지 않는다 — {far}")

# **단위마다 자를 자리가 다르다.** 도청은 인구중심에서 멀리 있는 일이
# 흔하다 — 경북도청 안동, 충남도청 홍성, 전남도청 무안. 구를 가르려고
# 잡은 40km 를 시도에 그대로 쓰면 그런 도청이 통째로 걸러진다.
GYEONGBUK = [{"name": "경상북도청", "category": "지방행정기관",
              "road_addr": "경상북도 안동시 풍천면 도청대로 455",
              "lat": 36.5760, "lon": 128.5056}]
check(of.pick(GYEONGBUK, (37.4845, 130.9057), of.MAX_KM["gu"]) is None,
      "구 기준(40km)이면 울릉군 앵커에서 경북도청이 걸러진다")
check(of.pick(GYEONGBUK, (37.4845, 130.9057), of.MAX_KM["sido"]) is not None,
      "시도 기준이면 잡힌다 (도청은 인구중심에서 멀다)")

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
# **이웃이 아는 이름을 빌린다.** 관청을 못 찾은 시군구는 시도 이름도
# 비는데, 그대로 두면 멀리서 볼 때 그 시군구가 자기 이름으로 홀로
# 원을 그린다 — 강화군·옹진군이 인천에서 떨어져 나오는 식이다.
# 코드 앞 두 자리가 같으면 같은 시도이므로 다수결로 채운다.
check(by_name["울릉군"]["sido"] == "",
      "빌릴 이웃이 없으면 그대로 빈 값 (47 접두사에 울릉군뿐이다)")
_nb = [r for r in regions if r["sigungu_cd"] == "41113"]
check(_nb and _nb[0]["sido"] == "경기도",
      f"관청이 없어도 같은 접두사의 이름을 빌린다 — {_nb and _nb[0]['sido']!r}")
check(by_name["수원시 장안구"]["parent"] == "수원시", "시 아래 구는 parent 를 갖는다")

ro = wx._region_offices()
check(ro.get("sido", {}).get("경기도") == [37.275, 127.0092],
      f"도청이 meta 로 나간다 — {ro.get('sido')}")
check(ro.get("si", {}).get("수원시") == [37.2634, 127.0287],
      f"시청도 나간다 — {ro.get('si')}")
# 구 단위는 regions.json 의 각 행이 들고 있으므로 여기 실으면 두 번이다.
check("gu" not in ro, "구 단위는 여기 안 싣는다 (행이 이미 들고 있다)")
check(json.dumps(ro, ensure_ascii=False), "브라우저가 읽을 수 있는 JSON 이다")

print("\n6. 문자열 안에 줄바꿈이 든 응답도 읽는다")
# **run 40 이 여기서 죽었다.** 브이월드 장소검색이 문자열 안에 제어문자를
# 그대로 넣어 보냈고, 파이썬 기본 파서가 거부했다.
#
#   json.decoder.JSONDecodeError: Invalid control character at:
#       line 1 column 1001 (char 1000)
#
# 첫 시군구에서 그대로 죽어서 관청을 한 곳도 못 받았는데, 단계가
# continue-on-error 라 초록으로 지나갔다. 규격을 어긴 것은 저쪽이지만
# 우리가 못 읽을 이유는 없다.
import types                                        # noqa: E402
from redt.collect import http as rhttp              # noqa: E402

BAD_BODY = ('{"response":{"status":"OK","result":{"items":[{"title":"어떤'
            '\n관청","point":{"x":"127.0","y":"37.0"}}]}}}')


class FakeResp:
    status_code = 200
    text = BAD_BODY

    def json(self):
        return json.loads(self.text)          # 기본 파서 — 여기서 죽는다


_real_get = rhttp.get
rhttp.get = lambda url, params, timeout=30: FakeResp()
try:
    body = rhttp.get_json("https://example.invalid", {})
    got_title = body["response"]["result"]["items"][0]["title"]
finally:
    rhttp.get = _real_get
check(got_title.startswith("어떤"),
      f"제어문자가 든 응답도 읽는다 — {got_title!r}")

print("\n7. 수집기가 실제로 끝까지 도는가")
# 워크플로 단계가 continue-on-error 라, 여기서 죽으면 **조용히 건너뛴다.**
# SQL 한 줄이나 칸 순서가 틀려도 화면은 어제 그대로고 아무 말이 없다.
# 그래서 검색만 흉내내고 나머지는 진짜로 돌린다.
FAKE = {
    "장안구청": (37.3040, 127.0101, "경기도 수원시 장안구 송원로 101"),
    "권선구청": (37.2578, 126.9727, "경기도 수원시 권선구 권선로 1010"),
    "울릉군청": (37.4845, 130.9057, "경상북도 울릉군 울릉읍 울릉순환로 326"),
    "수원시청": (37.2634, 127.0287, "경기도 수원시 팔달구 효원로 241"),
    "경기도청": (37.2750, 127.0092, "경기도 수원시 팔달구 효원로 1"),
    "경상북도청": (36.5760, 128.5056, "경상북도 안동시 풍천면 도청대로 455"),
}


def fake_search(query, size=10):
    hit = FAKE.get(query)
    if not hit:
        return []
    lat, lon, addr = hit
    return [{"name": query, "category": "지방행정기관",
             "road_addr": addr, "lat": lat, "lon": lon}]


of.search_place = fake_search

with db.connect() as con:
    con.execute("DELETE FROM office")

import argparse                                     # noqa: E402
from redt import cli                                # noqa: E402
cli.cmd_offices(argparse.Namespace(refresh=True))

with db.connect(read_only=True) as con:
    rows = con.execute(
        "SELECT level, key, label, name, sido, lat, lon FROM office"
        " ORDER BY level, key").fetchdf()
got = {(r.level, r.key): r for r in rows.itertuples(index=False)}
check(("gu", "41111") in got, f"구 관청이 담긴다 — {sorted(got)}")
check(("si", "수원시") in got, "묶은 시의 시청도 담긴다")
check(("sido", "경기도") in got, "시도의 도청도 담긴다")
# 경상북도는 울릉군 하나뿐이지만 시도 단위는 서야 한다 — 멀리서 볼 때
# 그 도가 통째로 사라지면 안 된다.
check(("sido", "경상북도") in got, "시군구가 하나뿐인 도도 선다")
check(got[("gu", "41111")].sido == "경기도", "시도 이름이 주소에서 채워진다")
check(got[("gu", "47940")].sido == "경상북도",
      f"코드 앞 두 자리가 다르면 다른 시도 — {got[('gu', '47940')].sido}")
# 다시 돌려도 늘어나지 않는다. 이미 담은 것은 건너뛴다.
before = len(rows)
cli.cmd_offices(argparse.Namespace(refresh=False))
with db.connect(read_only=True) as con:
    after = con.execute("SELECT count(*) FROM office").fetchone()[0]
check(after == before, f"다시 돌려도 안 늘어난다 ({before} → {after})")

# **한 곳이 죽어도 나머지는 받는다.** 440번을 부르는 고리라 어느 하나가
# 예외를 던지면 그 뒤가 통째로 안 돌고, 워크플로 단계가 continue-on-error
# 라 초록으로 지나간다. 그러면 화면은 어제 그대로인데 아무도 이유를 모른다.
calls = {"n": 0}


def flaky_search(query, size=10):
    calls["n"] += 1
    if calls["n"] == 1:
        raise RuntimeError("중계기가 403 을 줬습니다")
    return fake_search(query, size)


of.search_place = flaky_search
with db.connect() as con:
    con.execute("DELETE FROM office")
cli.cmd_offices(argparse.Namespace(refresh=True))
with db.connect(read_only=True) as con:
    n = con.execute("SELECT count(*) FROM office").fetchone()[0]
# 첫 곳이 죽었지만 나머지는 담겼어야 한다.
check(n >= 4, f"첫 호출이 죽어도 나머지를 받는다 ({n}곳)")

# **못 찾은 것은 시도 이름을 붙여 다시 찾는다.**
# '북구청' 만으로는 전국에 흩어진 북구가 다 걸리고, 우리 대표점에서
# 40km 안에 하나도 안 들어오면 빈손으로 끝난다. run 41 에서 북구·동구·
# 서구·강화군·옹진군·고성군이 그렇게 빠졌다. 시도 이름을 앞에 붙이면
# 후보가 하나로 좁혀진다.
#
# 1차를 다 돌기 전에는 시도 이름을 모르므로 두 번째 바퀴여야 한다.
asked = []


def two_round_search(query, size=10):
    asked.append(query)
    if query == "권선구청":
        return []                      # 1차에서는 못 찾는다
    if query == "경기도권선구청":
        return [{"name": "권선구청", "category": "지방행정기관 > 구청",
                 "road_addr": "경기도 수원시 권선구 권선로 1010",
                 "lat": 37.2578, "lon": 126.9727}]
    return fake_search(query, size)


of.search_place = two_round_search
with db.connect() as con:
    con.execute("DELETE FROM office")
cli.cmd_offices(argparse.Namespace(refresh=True))
with db.connect(read_only=True) as con:
    got2 = con.execute(
        "SELECT sido, source FROM office WHERE level='gu' AND key='41113'"
    ).fetchall()
check("경기도권선구청" in asked, "시도 이름을 붙여 다시 묻는다")
check(len(got2) == 1, f"1차에서 못 찾은 곳을 2차가 담는다 ({len(got2)}곳)")
if got2:
    check(got2[0][1] == "vworld:search+sido",
          f"어느 바퀴에서 왔는지 남긴다 — {got2[0][1]}")

# **시도 이름이 하나도 없는 접두사는 다시 묻지 않는다.** 붙일 이름이
# 없으므로 같은 질의를 한 번 더 하는 헛수고가 된다.
check(asked.count("울릉군청") == 1,
      f"빌릴 이름이 없으면 다시 묻지 않는다 ({asked.count('울릉군청')}회)")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
