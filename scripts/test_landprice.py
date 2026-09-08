"""행정구역별·연도별 땅값 — 자료가 화면까지 오는가.

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
with db.connect() as con:
    db.upsert(con, "trade", pd.DataFrame(rows))

got = wx._land_price_by_region()
print()
check("years" in got and got["years"] == [2024, 2025],
      f"연도가 오름차순으로 온다 — {got.get('years')}")
g = got.get("groups", {})
check(set(g) == {"계획관리", "농림"},
      f"자료가 있는 용도지역만 실린다 — {sorted(g)}")

cell = g.get("계획관리", {}).get("41550")
check(cell is not None, "시군구 코드로 찾을 수 있다")
if cell:
    check(cell["n"] == [4, 1], f"거래 건수 — {cell['n']}")
    check(cell["p50"] == [250, 500], f"중앙값 — {cell['p50']}")
    # 평균 900 vs 중앙값 250. 이 둘을 나란히 두는 이유가 여기 있다.
    check(cell["avg"] == [900, 500], f"평균은 큰 거래에 끌려간다 — {cell['avg']}")
    check(cell["p50"][0] < cell["avg"][0],
          "치우친 해는 중앙값 < 평균 (화면이 이것을 보여줘야 한다)")

check("제2종일반주거" not in json.dumps(got, ensure_ascii=False),
      "묶음에 없는 용도지역은 안 싣는다")
check(g.get("농림", {}).get("41550", {}).get("n") == [1, 0],
      f"거래가 없는 해는 0 — {g.get('농림', {}).get('41550', {}).get('n')}")
# 해제·공장이 섞였으면 값이 튄다. 위 중앙값·평균이 그것을 이미 잡는다.
check(888888 not in cell["avg"] and 777777 not in cell["avg"],
      "해제된 거래와 공장 거래는 안 들어간다")
check(json.dumps(got, ensure_ascii=False), "브라우저가 읽을 수 있는 JSON 이다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
