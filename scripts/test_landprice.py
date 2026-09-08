"""행정구역별 땅값 — 최근 실거래 기준 — 자료가 화면까지 오는가.

사장님 지시(2026-09-08): "행정 구역별 계획관리 땅값 실거래가 연 평균제공"

땅박사가 파는 '토지잠재력' 과 호갱노노의 '분위지도' 를 보고 오신 지시다.
우리가 가진 것으로 곧바로 되는 것이 이것이다 — 실거래 1,179만 건에
용도지역과 시군구와 연도가 다 붙어 있다.

**중앙값과 평균을 둘 다 낸다.** 땅값은 한쪽으로 길게 늘어진 분포라
평균이 큰 거래 몇 건에 끌려간다. 그 둘이 크게 다르면 그 자체가
'큰 거래가 섞였다' 는 신호다.
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


rows = []
# 안성시 계획관리 2024년: 100 / 200 / 300 / 3,000 (원/㎡)
# 중앙값 250, 평균 900 — **평균이 큰 거래 한 건에 끌려간다.**
for i, price in enumerate([100.0, 200.0, 300.0, 3000.0]):
    rows.append(dict(trade_id=f"A{i}", kind="land", sigungu_cd="41550",
                     sigungu="안성시", umd="공도읍", jibun=str(i),
                     land_use="계획관리지역", deal_year=2024,
                     lat=37.0, lon=127.2, price_per_m2=price,
                     area_m2=1000.0, is_cancelled=False))
# 같은 시군구 다른 해
rows.append(dict(trade_id="A9", kind="land", sigungu_cd="41550",
                 sigungu="안성시", umd="공도읍", jibun="9",
                 land_use="계획관리지역", deal_year=2025,
                 lat=37.0, lon=127.2, price_per_m2=500.0,
                 area_m2=1000.0, is_cancelled=False))
# 다른 용도지역
rows.append(dict(trade_id="B0", kind="land", sigungu_cd="41550",
                 sigungu="안성시", umd="공도읍", jibun="10",
                 land_use="농림지역", deal_year=2024,
                 lat=37.0, lon=127.2, price_per_m2=50.0,
                 area_m2=1000.0, is_cancelled=False))
# 묶음에 없는 용도지역 — 실려도 안 되고 죽여도 안 된다
rows.append(dict(trade_id="C0", kind="land", sigungu_cd="41550",
                 sigungu="안성시", umd="공도읍", jibun="11",
                 land_use="제2종일반주거지역", deal_year=2024,
                 lat=37.0, lon=127.2, price_per_m2=9999.0,
                 area_m2=1000.0, is_cancelled=False))
# **해제된 거래는 빠져야 한다.** 이것이 섞이면 값이 통째로 틀어진다.
rows.append(dict(trade_id="X0", kind="land", sigungu_cd="41550",
                 sigungu="안성시", umd="공도읍", jibun="12",
                 land_use="계획관리지역", deal_year=2024,
                 lat=37.0, lon=127.2, price_per_m2=888888.0,
                 area_m2=1000.0, is_cancelled=True))
# 공장 거래도 빠져야 한다 (땅값이 아니다)
rows.append(dict(trade_id="F0", kind="factory", sigungu_cd="41550",
                 sigungu="안성시", umd="공도읍", jibun="13",
                 land_use="계획관리지역", deal_year=2024,
                 lat=37.0, lon=127.2, price_per_m2=777777.0,
                 area_m2=1000.0, is_cancelled=False))
# **다섯 건 미만인 읍면동.** 두 건으로 만든 중앙값을 지도에 값으로
# 찍으면 그것은 자료가 아니라 우연이다.
for i, price in enumerate([1000.0, 2000.0]):
    rows.append(dict(trade_id=f"T{i}", kind="land", sigungu_cd="41500",
                     sigungu="이천시", umd="얇은리", jibun=str(i),
                     land_use="계획관리지역", deal_year=2025,
                     lat=37.1, lon=127.3, price_per_m2=price,
                     area_m2=1000.0, is_cancelled=False))
with db.connect() as con:
    db.upsert(con, "trade", pd.DataFrame(rows))


latest = wx._latest_trade_year()
check(latest == 2025, f"자료의 마지막 해를 찾는다 — {latest}")

got = wx._land_price_by_region(latest)
print()
check(got.get("default_group") == "계획관리",
      f"기본 용도지역은 계획관리 — {got.get('default_group')}")
check([w["key"] for w in got.get("windows", [])]
      == ["y1", "y3", "y5", "c20", "c50"],
      "기간 기준 셋과 건수 기준 둘을 낸다")
g = got.get("groups", {})
check(set(g) == {"계획관리", "농림"},
      f"자료가 있는 용도지역만 실린다 — {sorted(g)}")
check(sorted(g["계획관리"]) == ["41500", "41550"],
      f"시군구가 둘 다 실린다 — {sorted(g['계획관리'])}")

cell = g.get("계획관리", {}).get("41550")
check(cell is not None, "시군구 코드로 찾을 수 있다")
if cell:
    # 최근 1년(2025)은 500 한 건뿐이다. 2024년의 치우친 값이 안 섞인다.
    check(cell["y1"] == [1, 500, 500, 2025], f"최근 1년 — {cell['y1']}")
    # 최근 3년(2023~2025)은 다섯 건 전부. 100·200·300·500·3000
    #   중앙값 300 · 평균 820 — **평균이 큰 거래 한 건에 끌려간다.**
    check(cell["y3"] == [5, 300, 820, 2024], f"최근 3년 — {cell['y3']}")
    check(cell["y3"][1] < cell["y3"][2],
          "치우친 표본은 중앙값 < 평균 (화면이 이것을 보여줘야 한다)")
    # 건수 기준은 몇 년치를 긁어왔는지 같이 낸다. 어떤 군의 '최근 20건' 은
    # 십수 년치다 — 그것을 안 보여주면 '최근' 이라는 말이 거짓이 된다.
    check(cell["c20"] == [5, 300, 820, 2024],
          f"최근 20건은 있는 것 다섯 건 — {cell['c20']}")
    check(cell["c20"][3] == 2024, "몇 년부터 긁어온 값인지 같이 싣는다")

check("제2종일반주거" not in json.dumps(got, ensure_ascii=False),
      "묶음에 없는 용도지역은 안 싣는다")
_dump = json.dumps(got, ensure_ascii=False)
check("888888" not in _dump and "777777" not in _dump,
      "해제된 거래와 공장 거래는 안 들어간다")

# **거래가 없는 창은 아예 안 싣는다.** 0 이나 null 을 실으면 파일만
# 무거워지고 화면은 어차피 못 그린다.
nong = g.get("농림", {}).get("41550", {})
check("y1" not in nong, f"2025년 농림 거래가 없으니 최근 1년 칸이 없다 — {sorted(nong)}")
check(nong.get("y3") == [1, 50, 50, 2024], f"최근 3년에는 있다 — {nong.get('y3')}")

print()
print("2. 읍면동 — 용도지역마다, 그리고 시·도마다 파일을 따로 낸다")
# 통짜로 내면 안 된다. 실측(run 48)에서 계획관리 읍면동이 13,472칸,
# 3.0MB(gzip 753KB)였는데 화면에는 90개까지만 놓는다 — 받은 것의 99%를
# 그리지도 않는다. 용도지역으로 한 번, 시도로 한 번 더 나눈다.
umd = wx._land_price_by_umd(latest)
check(set(umd) == {"계획관리", "생산관리", "자연녹지", "농림", "보전관리"},
      f"다섯 용도지역을 늘 낸다 (빈 것도) — {sorted(umd)}")
check(sorted(umd["계획관리"]) == ["41"],
      f"시도 두 자리로 조각을 나눈다 — {sorted(umd['계획관리'])}")
gd = {c["nm"]: c for c in umd["계획관리"]["41"]["cells"]}
check("공도읍" in gd, f"읍면동 이름으로 온다 — {sorted(gd)}")
if "공도읍" in gd:
    c = gd["공도읍"]
    check(c["sg"] == "41550" and c["sgnm"] == "안성시",
          f"어느 시군구인지 같이 온다 — {c['sg']} {c['sgnm']}")
    check(abs(c["lat"] - 37.0) < 0.01 and abs(c["lon"] - 127.2) < 0.01,
          f"좌표는 그 읍면동 거래의 평균 — {c['lat']}, {c['lon']}")
    check(c["w"]["y3"] == [5, 300, 820, 2024],
          f"창 값은 시군구와 같은 셈 — {c['w']['y3']}")
# 다섯 건 미만인 읍면동은 뺀다. 두 건으로 만든 중앙값은 자료가 아니라 우연이다.
check("얇은리" not in gd, "거래 다섯 건 미만인 읍면동은 안 싣는다")
check(not umd["농림"], "농림은 한 건뿐이라 조각 자체가 안 생긴다")
# 경계상자가 없으면 화면이 무엇을 받을지 모른다 — 나눈 뜻이 없어진다.
bbox = wx._umd_bbox(umd["계획관리"]["41"]["cells"])
check(bbox == [37.0, 127.2, 37.0, 127.2], f"조각의 경계상자를 낸다 — {bbox}")
check(json.dumps(umd, ensure_ascii=False), "브라우저가 읽을 수 있는 JSON 이다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
