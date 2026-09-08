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
# 한 건뿐인 용도지역. 이제 제2종일반주거도 묶음에 **있지만**, 다섯 건
# 문턱을 못 넘으므로 실리면 안 된다 (사장님 지시로 용도지역을 전부
# 담게 된 뒤에도 문턱은 그대로다).
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
# **최근 1년이 다섯 건을 넘는 시군구 하나.** 이것이 없으면 y1 이 늘
# 비어서, '창이 제대로 채워지는가' 를 아예 못 본다.
for i, price in enumerate([100.0, 200.0, 300.0, 400.0, 500.0, 600.0]):
    rows.append(dict(trade_id=f"K{i}", kind="land", sigungu_cd="41570",
                     sigungu="김포시", umd="통진읍", jibun=str(i),
                     land_use="계획관리지역", deal_year=2025,
                     lat=37.6, lon=126.6, price_per_m2=price,
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
check(set(g) == {"계획관리"},
      f"다섯 건을 넘긴 용도지역만 실린다 — {sorted(g)}")

check(sorted(g["계획관리"]) == ["41550", "41570"],
      f"다섯 건을 넘긴 시군구만 실린다 — {sorted(g['계획관리'])}")

cell = g.get("계획관리", {}).get("41550")
check(cell is not None, "시군구 코드로 찾을 수 있다")
if cell:
    # 안성은 최근 1년(2025)이 한 건뿐이다 — 창째로 빠진다.
    check("y1" not in cell, f"다섯 건이 안 되는 창은 안 싣는다 — {sorted(cell)}")
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

# 김포는 2025년에 여섯 건 — 최근 1년이 제대로 채워진다.
kim = g["계획관리"].get("41570", {})
check(kim.get("y1") == [6, 350, 350, 2025], f"최근 1년이 채워진다 — {kim.get('y1')}")

# 시군구 칸에도 추이가 붙는다. 안성 계획관리는 2024년 4건(중앙값 250).
# 2025년은 한 건뿐이라 빠진다 — 한 건짜리 해를 이어 그리면 그것은
# 추세가 아니라 잡음이다.
check(cell.get("s") == [[2024, 4, 250]], f"시군구에도 추이가 붙는다 — {cell.get('s')}")
check(kim.get("s") == [[2025, 6, 350]], f"김포는 2025년 여섯 건 — {kim.get('s')}")

check("제2종일반주거" not in json.dumps(got, ensure_ascii=False),
      "한 건뿐인 용도지역은 묶음에 있어도 안 싣는다")
_dump = json.dumps(got, ensure_ascii=False)
check("888888" not in _dump and "777777" not in _dump,
      "해제된 거래와 공장 거래는 안 들어간다")

# **거래가 없는 창은 아예 안 싣는다.** 0 이나 null 을 실으면 파일만
# 무거워지고 화면은 어차피 못 그린다.
nong = g.get("농림", {}).get("41550", {})
check("y1" not in nong, f"2025년 농림 거래가 없으니 최근 1년 칸이 없다 — {sorted(nong)}")
# **거래가 다섯 건도 안 되면 창째로 비운다.** run 49 배포본에서 계획관리
# 최근 3년 1위가 거래 2건짜리 부천시 원미구(평당 2,199만원)였다. 지도에서
# 가장 짙은 파랑으로 뜨는데 그것은 자료가 아니라 우연이다.
check(nong == {}, f"한 건뿐인 농림은 어느 창에도 안 실린다 — {sorted(nong)}")
check("농림" not in g or "41550" not in g.get("농림", {}),
      "창이 하나도 안 남으면 칸 자체가 없다")
# 그리고 얇은 시군구도 같은 규칙으로 빠진다 (41500 은 두 건).
check("41500" not in g["계획관리"],
      f"두 건짜리 시군구는 안 실린다 — {sorted(g['계획관리'])}")

print()
print("2. 읍면동 — 용도지역마다, 그리고 시·도마다 파일을 따로 낸다")
# 통짜로 내면 안 된다. 실측(run 48)에서 계획관리 읍면동이 13,472칸,
# 3.0MB(gzip 753KB)였는데 화면에는 90개까지만 놓는다 — 받은 것의 99%를
# 그리지도 않는다. 용도지역으로 한 번, 시도로 한 번 더 나눈다.
umd = wx._land_price_by_umd(latest)
# **정의한 것을 늘 낸다 — 빈 것도.** 빈 칸을 빼면 화면이 '이 용도지역은
# 없다' 와 '이번에 안 왔다' 를 구별하지 못한다. 갯수를 못 박지 않는다 —
# 용도지역이 늘 때마다 이 줄이 깨지면 검사가 잔소리가 된다.
check(set(umd) == {n for n, _, _ in wx.LANDPRICE_GROUPS},
      f"정의한 용도지역을 늘 낸다 (빈 것도) — {len(umd)}개")
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
    # 말풍선에 그릴 최근 추이. 값 하나만 보면 오르는 중인지 내리는
    # 중인지 알 수 없다 (사장님 지시 2026-09-08: "마우스 오버랩시
    # 정보와 실거래가격 트랜드 표시").
    check(c["w"].get("s") == [[2024, 4, 250], [2025, 1, 500]][:1],
          f"추이는 세 건 이상인 해만 — {c['w'].get('s')}")
# 다섯 건 미만인 읍면동은 뺀다. 두 건으로 만든 중앙값은 자료가 아니라 우연이다.
check("얇은리" not in gd, "거래 다섯 건 미만인 읍면동은 안 싣는다")
check(not umd["농림"], "농림은 한 건뿐이라 조각 자체가 안 생긴다")
# 경계상자가 없으면 화면이 무엇을 받을지 모른다 — 나눈 뜻이 없어진다.
bbox = wx._umd_bbox(umd["계획관리"]["41"]["cells"])
check(bbox == [37.0, 126.6, 37.6, 127.2], f"조각의 경계상자를 낸다 — {bbox}")
check(json.dumps(umd, ensure_ascii=False), "브라우저가 읽을 수 있는 JSON 이다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print()
print("용도지역을 전부 담는가 — CASE 사슬의 순서까지")
# 사장님 지시(2026-09-08): "전체 용도지역이 아직 안나오네요. 전부 반영하고
# 체크하면 가격이 반영될 수 있도록 해주세요."
#
# 순서가 뜻을 정한다. CASE 는 먼저 맞는 것이 이기므로, 좁은 것이 넓은 것
# 위에 있어야 한다. 틀리면 거래가 사라지는 것이 아니라 **엉뚱한 칸으로
# 들어가서** 화면에 그럴듯한 숫자가 뜬다 — 눈으로는 못 잡는다.
_REAL = [
    "계획관리지역", "생산관리지역", "보전관리지역", "농림지역",
    "자연환경보전", "관리지역",
    "자연녹지지역", "생산녹지지역", "보전녹지지역",
    "제1종전용주거지역", "제2종전용주거지역", "전용주거지역",
    "제1종일반주거지역", "제2종일반주거지역", "제3종일반주거지역",
    "일반주거지역", "준주거지역",
    "중심상업지역", "일반상업지역", "근린상업지역", "유통상업지역",
    "전용공업지역", "일반공업지역", "준공업지역",
    "개발제한구역",
]
# CASE 를 그대로 흉내 낸다 — 먼저 맞는 것이 이긴다.
_hit = {lu: next((n for n, like, _ in wx.LANDPRICE_GROUPS if like in lu), None)
        for lu in _REAL}
check(all(_hit.values()),
      f"실제 용도지역이 하나도 안 빠진다 (빠진 것 "
      f"{[k for k, v in _hit.items() if not v]})")
# 미세분이 세분을 삼키면 안 된다.
check(_hit["계획관리지역"] == "계획관리" and _hit["관리지역"] == "관리(미세분)",
      f"'관리지역' 이 계획관리를 안 삼킨다 ({_hit['관리지역']})")
check(_hit["제2종일반주거지역"] == "제2종일반주거"
      and _hit["일반주거지역"] == "일반주거(미세분)",
      f"'일반주거지역' 이 제2종을 안 삼킨다 ({_hit['일반주거지역']})")
check(_hit["제1종전용주거지역"] == "제1종전용주거"
      and _hit["전용주거지역"] == "전용주거(미세분)",
      f"'전용주거지역' 이 제1종을 안 삼킨다 ({_hit['전용주거지역']})")
# 화면이 갈래로 묶어 보여주므로 갈래가 빠지면 그 칸이 어디에도 안 붙는다.
_nokind = [n for n, _, _ in wx.LANDPRICE_GROUPS
           if n not in wx.LANDPRICE_ZONE_KIND]
check(not _nokind, f"갈래(도시/비도시/용도구역)가 빠진 것이 없다 ({_nokind})")
# 파일 이름이 겹치면 나중 것이 앞의 것을 덮어쓴다 — 조용히 자료가 사라진다.
_keys = [k for _, _, k in wx.LANDPRICE_GROUPS]
check(len(set(_keys)) == len(_keys), "파일 이름 열쇠가 서로 안 겹친다")

print("모두 통과")
