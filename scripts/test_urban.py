"""여섯째 축 '주변 이용' — 지표 계산과 검증 게이트.

docs/six-axes-method.md §5-2. 지켜야 할 것 둘:

  1. 도시용지 비율은 **법정동리(PNU 앞 10자리)** 단위이고 면적 가중이다
     (토지적성평가의 정의).
  2. 검증을 통과하지 않은 축은 화면으로 **못 나간다** — adopted 가
     거짓이면 for_web 을 부르지 않는다.

  실행: python scripts/test_urban.py   (make test 에 포함)
"""
import json
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("VWORLD_KEY", "test-key")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

tmp = pathlib.Path(tempfile.mkdtemp())
from redt import config as cfg                      # noqa: E402
cfg.DB_PATH = tmp / "test.duckdb"
cfg.PROCESSED = tmp
from redt import db                                 # noqa: E402
db.DB_PATH = tmp / "test.duckdb"
import pandas as pd                                 # noqa: E402
from redt.analyze import urban                      # noqa: E402
urban.PROCESSED = tmp
urban.RESULT = tmp / "urban_check.json"

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


print("1. 법정동리 도시용지 비율 — 면적 가중")
# 동리 A (4155025021): 주거 3필지 각 100㎡ + 임야 1필지 700㎡ → 면적 30%, 수 75%
# 동리 B (4155025022): 전 40필지 → 0%
parcels = []
for i in range(3):
    parcels.append(dict(pnu=f"4155025021100{i:06d}", sigungu_cd="41550", jimok="대",
                        land_use="계획관리지역", use_situation="단독", area_m2=100.0,
                        road_side="소로한면", shape="정방형", slope="평지",
                        official_price=300000.0, stdr_year=2026))
parcels.append(dict(pnu="4155025021100000099", sigungu_cd="41550", jimok="임야",
                    land_use="계획관리지역", use_situation="자연림", area_m2=700.0,
                    road_side="맹지", shape="부정형", slope="급경사",
                    official_price=20000.0, stdr_year=2026))
# 분모에 안 드는 것 — 도로. 넣으면 비율이 흔들린다.
parcels.append(dict(pnu="4155025021100000098", sigungu_cd="41550", jimok="도로",
                    land_use="계획관리지역", use_situation="도로", area_m2=5000.0,
                    road_side=None, shape=None, slope=None, official_price=None, stdr_year=2026))
# 스무 필지 문턱을 넘기려고 동리 A 에 임야 소필지를 더한다 (면적 0.1㎡ 씩).
for i in range(20):
    parcels.append(dict(pnu=f"4155025021200{i:06d}", sigungu_cd="41550", jimok="임야",
                        land_use="계획관리지역", use_situation="자연림", area_m2=0.1,
                        road_side="맹지", shape="부정형", slope="급경사",
                        official_price=1000.0, stdr_year=2026))
for i in range(40):
    parcels.append(dict(pnu=f"4155025022100{i:06d}", sigungu_cd="41550", jimok="전",
                        land_use="계획관리지역", use_situation="전", area_m2=1000.0,
                        road_side="세로한면(가)", shape="부정형", slope="평지",
                        official_price=50000.0, stdr_year=2026))
with db.connect() as con:
    db.upsert(con, "parcel", pd.DataFrame(parcels))
    share = urban.umd_share(con)
    web = urban.for_web(con)

a = share[share["umd"] == "4155025021"].iloc[0]
b = share[share["umd"] == "4155025022"].iloc[0]
check(abs(a["urban_area"] - 300 / (300 + 700 + 2)) < 0.01,
      f"동리 A 면적 비율 ≈ 30% (도로 5,000㎡ 는 분모에서 뺀다) — {a['urban_area']:.3f}")
check(abs(a["urban_cnt"] - 3 / 24) < 0.01, f"동리 A 필지 수 비율 = 3/24 — {a['urban_cnt']:.3f}")
check(b["urban_area"] == 0.0, "동리 B 는 0")
check("4155025021" in web["umd"] and "4155025022" in web["umd"], "화면용에 두 동리가 다 있다")
check("41550" not in web["q"], "동리가 다섯 미만인 시군구는 분위를 안 만든다 (시도로 물러난다)")
check("41" in web["q_sido"] and len(web["q_sido"]["41"]) == 11, "시·도 분위 11개")

print()
print("2. 검증 게이트 — 통과 전에는 화면에 못 나간다")
check(urban.load() is None and not urban.adopted(), "결과 파일이 없으면 채택 아님")
urban.save({"adopted": False, "reason": "검사"})
check(not urban.adopted(), "보류로 저장하면 채택 아님")
urban.save({"adopted": True, "reason": "검사"})
check(urban.adopted(), "채택으로 저장하면 채택")
check(json.loads(urban.RESULT.read_text(encoding="utf-8"))["adopted"] is True, "JSON 으로 남는다")

print()
print("3. 표본이 얇으면 채택하지 않는다")
with db.connect() as con:
    r = urban.check(con)
check(r["adopted"] is False and ("표본" in r["reason"]), f"거래가 없으면 보류 — {r['reason']}")

print()
print("4. 요약 글")
txt = urban.report({"adopted": True, "reason": "채택", "national": {"n": 12000, "effect_pct": 4.1,
                    "se": 0.002, "p": 0.001, "r2": 0.4}, "raw_corr": 0.3, "umd_with_share": 300,
                    "since_year": 2021, "by_sido": {"41": {"n": 8000, "effect_pct": 3.9, "p": 0.01}},
                    "sido_agree": 1.0})
check("+4.10%" in txt and "시도 41" in txt, "전국·시도 줄이 있다")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
