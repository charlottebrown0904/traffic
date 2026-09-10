"""행정구역별 땅값 — 최근 실거래 기준 — 자료가 화면까지 오는가.

요구사항(2026-09-08): "행정 구역별 계획관리 땅값 실거래가 연 평균제공"

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
# 문턱을 못 넘으므로 실리면 안 된다 (요구사항으로 용도지역을 전부
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
# **값이 서는 것과 이름이 서는 것은 다른 일이다** (요구사항
# 2026-09-09: "거래가 5건 미만이라 표시가 안되는 곳은 표시를 하면서
# -만/평 으로"). 얇은 칸도 few 만 들고 실린다 — 값은 여전히 없다.
def _has_value(cell):
    return any(k != "few" for k in cell)

vals = {name: sorted(cd for cd, cell in cells.items() if _has_value(cell))
        for name, cells in g.items()}
check([name for name, cds in vals.items() if cds] == ["계획관리"],
      f"값이 실리는 용도지역은 계획관리뿐 — { {k: v for k, v in vals.items() if v} }")

check(vals["계획관리"] == ["41550", "41570"],
      f"다섯 건을 넘긴 시군구만 값이 실린다 — {vals['계획관리']}")

cell = g.get("계획관리", {}).get("41550")
check(cell is not None, "시군구 코드로 찾을 수 있다")
if cell:
    # 안성은 최근 1년(2025)이 한 건뿐이다 — 창째로 빠진다.
    check("y1" not in cell, f"다섯 건이 안 되는 창은 값을 안 싣는다 — {sorted(cell)}")
    # 대신 **건수만** 따로 싣는다. 화면이 '0건' 과 '세 건뿐' 을 구별해야
    # 한다 — 둘 다 0 으로 적으면 있던 거래를 없다고 말하는 것이 된다.
    check(cell.get("few", {}).get("y1") == 1,
          f"버린 창의 건수는 few 에 남는다 — {cell.get('few')}")
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

check(not any(_has_value(c) for c in g.get("제2종일반주거", {}).values()),
      "한 건뿐인 용도지역은 묶음에 있어도 값을 안 싣는다"
      f" — {g.get('제2종일반주거')}")
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
check(not _has_value(nong), f"한 건뿐인 농림은 어느 창에도 값이 없다 — {sorted(nong)}")
check(nong.get("few"), f"그래도 거래가 있었다는 것은 남는다 — {nong.get('few')}")
# 그리고 얇은 시군구도 같은 규칙이다 (41500 은 두 건).
check("41500" not in vals["계획관리"],
      f"두 건짜리 시군구는 값이 안 실린다 — {vals['계획관리']}")
check(g["계획관리"].get("41500", {}).get("few"),
      "그래도 이름을 그릴 수 있게 건수는 남는다"
      f" — {g['계획관리'].get('41500')}")

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
    # 중인지 알 수 없다 (요구사항 2026-09-08: "마우스 오버랩시
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
print("읍·면·동 인구 — 행정동 이름으로 잇되, 안 맞으면 비운다")
# 요구사항(2026-09-09): 읍면동 인구도 적용.
#
# KOSIS 는 **행정동**(1111051500 청운효자동)이고 우리 거래는 **법정동**
# 이름이다. 1:1 이 아니다 — 읍·면은 거의 맞고 도시의 동은 자주 어긋난다.
# 안 맞는 것을 시군구 인구로 채우면 리 하나가 20만이 된다.
with db.connect() as con:
    db.upsert(con, "umd_pop", pd.DataFrame([
        # 공도읍은 맞는다 (읍·면은 행정동 이름이 법정동과 같은 일이 흔하다)
        dict(adm_cd="4155025300", sigungu_cd="41550", umd="공도읍",
             year=2025, pop=64000),
        # 통진읍도 맞는다
        dict(adm_cd="4157025900", sigungu_cd="41570", umd="통진읍",
             year=2025, pop=31000),
        # 이건 우리 자료에 없는 행정동 이름 — 아무 데도 안 붙어야 한다
        dict(adm_cd="4155099900", sigungu_cd="41550", umd="없는동",
             year=2025, pop=999999),
        # 지난해 값. 최근 해만 써야 한다 (둘을 더하면 두 배가 된다)
        dict(adm_cd="4155025300", sigungu_cd="41550", umd="공도읍",
             year=2024, pop=63000),
    ]))

_pop = wx._umd_pop_latest()
check(_pop.get(("41550", "공도읍")) == 64000,
      f"가장 최근 해만 쓴다 (2024+2025 를 더하지 않는다) — {_pop.get(('41550', '공도읍'))}")

_umd2 = wx._land_price_by_umd(latest)
_cells = {c["nm"]: c for c in _umd2["계획관리"]["41"]["cells"]}
check(_cells.get("공도읍", {}).get("pop") == 64000,
      f"이름이 맞으면 인구가 붙는다 — {_cells.get('공도읍', {}).get('pop')}")

# **'면 + 리' 두 마디를 리 이름으로 물으면 안 맞는다.** run 71 실측
# 매칭률이 2.6%(461/17,430)였던 것이 그것이다 — 원인을 '행정동이라
# 법정동과 안 맞는다' 로 짚었는데, 첫째 원인은 우리 umd 칸이
# '미양면 계륵리' 두 마디라는 것이었다.
check(wx._umd_head("미양면 계륵리") == "미양면"
      and wx._umd_head("공도읍") == "공도읍",
      "면·동 이름은 첫 마디다")
# 면 인구는 조각이 따로 싣는다 — 리 값을 합친 것이 아니다.
_hp = _umd2["계획관리"]["41"].get("head_pop", {})
check(_hp.get("41550|공도읍") == 64000,
      f"면·동 인구를 조각에 따로 싣는다 — {_hp}")
check("pop" not in _cells.get("통진읍", {}) or _cells["통진읍"]["pop"] == 31000,
      "다른 시군구의 같은 이름과 안 섞인다")
# 우리 자료에 없는 행정동은 칸 자체가 없어야 한다 — 거래가 없으므로.
check("없는동" not in _cells, "우리 거래에 없는 행정동은 칸을 안 만든다")

# **안 맞는 이름은 비운다.** 얇은리는 거래가 두 건이라 칸이 없지만,
# 칸이 있더라도 인구를 억지로 채우면 안 된다.
_no = [c for c in _umd2["계획관리"]["41"]["cells"] if "pop" not in c]
check(all(("41550", c["nm"]) not in _pop and ("41570", c["nm"]) not in _pop
          for c in _no),
      "인구가 안 붙은 칸은 정말로 대조표에 없는 이름이다")

print()
print("용도지역을 전부 담는가 — CASE 사슬의 순서까지")
# 요구사항(2026-09-08): "전체 용도지역이 아직 안나오네요. 전부 반영하고
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
check(_hit["계획관리지역"] == "계획관리" and _hit["관리지역"] == "관리(세분 없음)",
      f"'관리지역' 이 계획관리를 안 삼킨다 ({_hit['관리지역']})")
check(_hit["제2종일반주거지역"] == "제2종일반주거"
      and _hit["일반주거지역"] == "일반주거(세분 없음)",
      f"'일반주거지역' 이 제2종을 안 삼킨다 ({_hit['일반주거지역']})")
check(_hit["제1종전용주거지역"] == "제1종전용주거"
      and _hit["전용주거지역"] == "전용주거(세분 없음)",
      f"'전용주거지역' 이 제1종을 안 삼킨다 ({_hit['전용주거지역']})")

# ── 법령 구조와 맞는가 (요구사항 2026-09-09) ─────────────────────
#
# 국토계획법 §36① 은 네 칸이다: 도시지역·관리지역·농림지역·자연환경
# 보전지역. 시행령 §30① 은 도시지역을 주거·상업·공업·녹지로 세분한다.
# 같은 법 §38 의 개발제한구역은 **용도지역이 아니라 용도구역**이다.
#
# '비도시지역' 은 법에 없는 말이다. 편해서 쓰다가 법의 칸을 흐렸다.
_majors = [m for m, _mid, _ns in wx.LANDPRICE_ZONE_TREE]
check(_majors[:4] == ["도시지역", "도시지역", "도시지역", "도시지역"],
      f"도시지역이 먼저다 (법 §36①1) — {_majors[:4]}")
check("비도시지역" not in _majors,
      f"법에 없는 '비도시지역' 을 안 쓴다 — {sorted(set(_majors))}")
for _need in ("도시지역", "관리지역", "농림지역", "자연환경보전지역"):
    check(_need in _majors, f"법 §36① 의 '{_need}' 칸이 있다")
_mid = [m for maj, m, _ns in wx.LANDPRICE_ZONE_TREE if maj == "도시지역"]
check(_mid == ["주거지역", "상업지역", "공업지역", "녹지지역"],
      f"시행령 §30① 의 세분 순서 그대로 — {_mid}")
check(wx.LANDPRICE_ZONE_KIND["개발제한구역"].startswith("용도구역"),
      "개발제한구역은 용도지역이 아니라 용도구역이다 "
      f"({wx.LANDPRICE_ZONE_KIND['개발제한구역']})")

# **못 넣는 것은 기타로 하되 사유를 적는다** (요구사항).
_etc = [n for maj, _m, ns in wx.LANDPRICE_ZONE_TREE if maj == "기타"
        for n in ns]
check(set(_etc) == {"용도 미지정", "용도 미상", "기타"},
      f"기타 칸 — {_etc}")
check(all(wx.LANDPRICE_ZONE_NOTE.get(n) for n in _etc),
      "기타에 든 것마다 사유가 적혀 있다")
check(all(wx.LANDPRICE_ZONE_NOTE.get(n) for n in
          ("개발제한구역", "관리(세분 없음)", "일반주거(세분 없음)")),
      "용도구역과 '세분 없음' 에도 사유가 적혀 있다")

# 나무와 묶음이 어긋나면 어느 칸에도 안 붙는 용도지역이 생긴다.
_tree_names = [n for _maj, _m, ns in wx.LANDPRICE_ZONE_TREE for n in ns]
_names = [n for n, _, _ in wx.LANDPRICE_GROUPS]
check(sorted(_tree_names) == sorted(_names),
      f"나무와 묶음이 정확히 같다 ({len(_tree_names)} vs {len(_names)})")
# 파일 이름이 겹치면 나중 것이 앞의 것을 덮어쓴다 — 조용히 자료가 사라진다.
_keys = [k for _, _, k in wx.LANDPRICE_GROUPS]
check(len(set(_keys)) == len(_keys), "파일 이름 열쇠가 서로 안 겹친다")

print()
print("행정구역이 통합돼 코드가 바뀐 시군구 — 이름으로 다시 잇는가")
# run 72 실측: 읍·면 매칭률 82.4% 인데 못 맞춘 것이 **한 시도에 통째로**
# 몰려 있었다. 전남과 광주가 합쳐지면서 시군구 코드가 새로 매겨져,
# 우리 거래는 12130(여수시)인데 KOSIS 인구는 아직 46130 이었다.
#
# 대조표를 외워 적지 않는다 — 읍·면 이름이 몇 개나 겹치는지로 찾는다.
_merged = []
for i, nm in enumerate(["돌산읍", "소라면", "율촌면", "화양면"]):
    for j in range(5):                       # 칸이 서려면 다섯 건이 필요하다
        _merged.append(dict(
            trade_id=f"M{i}{j}", kind="land", sigungu_cd="12130",
            sigungu="여수시", umd=f"{nm} 어딘가리", jibun=str(j),
            land_use="계획관리지역", deal_year=2025,
            lat=34.76, lon=127.66, price_per_m2=300.0,
            area_m2=1000.0, is_cancelled=False))
with db.connect() as con:
    db.upsert(con, "trade", pd.DataFrame(_merged))
    db.upsert(con, "umd_pop", pd.DataFrame([
        # KOSIS 쪽은 아직 **옛 코드**다.
        # adm_cd 가 열쇠다 — 넷을 같은 값으로 두면 한 줄로 뭉개진다.
        dict(adm_cd=f"461302{i}000", sigungu_cd="46130", umd=nm,
             year=2025, pop=pop)
        for i, (nm, pop) in enumerate([("돌산읍", 20000), ("소라면", 12000),
                                       ("율촌면", 9000), ("화양면", 7000)])
    ]))

_pop2 = wx._umd_pop_latest()
check(_pop2.get(("12130", "돌산읍")) == 20000,
      f"옛 코드의 인구를 새 코드로 옮겨 담는다 — {_pop2.get(('12130', '돌산읍'))}")
check(_pop2.get(("46130", "돌산읍")) == 20000,
      "옛 코드 칸은 지우지 않는다 (다른 표가 옛 코드로 물어볼 수 있다)")
# **이미 코드가 맞는 시군구는 건드리지 않는다.** 41550(안성시)의 공도읍이
# 엉뚱한 곳으로 끌려가면 화면에 남의 동네 인구가 뜬다.
check(_pop2.get(("41550", "공도읍")) == 64000,
      f"코드가 이미 맞는 곳은 그대로다 — {_pop2.get(('41550', '공도읍'))}")

# 이름이 하나도 안 겹치면 **잇지 않는다.** 억지로 이으면 없는 것보다
# 나쁜 값이 화면에 뜬다.
_alias = wx._umd_pop_alias({"99999": {"전혀", "다른", "이름들"}})
check(_alias == {}, f"이름이 안 겹치면 잇지 않는다 — {_alias}")

# 그리고 실제로 면 인구가 칸까지 온다.
_umd3 = wx._land_price_by_umd(2025)
_hp3 = _umd3["계획관리"].get("12", {}).get("head_pop", {})
check(_hp3.get("12130|돌산읍") == 20000,
      f"통합 시군구의 면 인구가 화면 조각까지 온다 — {_hp3}")

# **끝에서 한 번 더 센다.** 중간에 sys.exit 이 한 번 있을 뿐이라,
# 그 뒤에 실패한 것은 여태 '모두 통과' 로 찍히고 종료 코드도 0이었다 —
# 이 파일의 뒷부분은 사실상 검사가 아니었다.
if fail:
    print()
    print(f"실패 {len(fail)}건")
    for f in fail:
        print(f"  · {f}")
    sys.exit(1)
print("모두 통과")
