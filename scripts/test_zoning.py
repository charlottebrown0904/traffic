"""개발 한도 표 (C1) — 시행령 상한 + 조례 값을 시군구 코드에 붙이는가.

  1. 도 아래 시·군은 그 시·군 조례, 구는 시 조례(수원시 장안구 → 수원시).
  2. 자치구는 값 없으면 광역시 조례, 값 있으면 자치구 조례. 세종·제주는 시도 조례.
  3. 시행령 범위 밖 값은 버리고 이유를 남긴다 (읽기 오류 — 완화 단서를 잡은 것).
  4. 화면용 JSON 은 조례를 한 번만 싣고 시군구는 가리키기만 한다.
  5. 실제 산출 파일이 저장소의 index.json·regions.json 과 맞는다 (안성 41550 = 40%).

  실행: python scripts/test_zoning.py   (make test 에 포함)
"""
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from redt import zoning as Z                        # noqa: E402

fail = []


def check(ok, label, extra=""):
    print(f"  {'✓' if ok else '✗'} {label}" + (f" — {extra}" if extra and not ok else ""))
    if not ok:
        fail.append(label)


def row(org, name, mst, **kw):
    r = {"org": org, "name": name, "mst": mst, "effective": "20260101"}
    for z in Z.ZONES:
        r[f"건폐율_{z}"] = kw.get("bcr", {}).get(z, "")
        r[f"용적률_{z}"] = kw.get("far", {}).get(z, "")
    r.update({"경사도_도": kw.get("slope", ""), "표고_m": kw.get("elev", ""), "입목축적_pct": kw.get("forest", "")})
    return r


ORD = [
    row("경기도 안성시", "안성시 도시계획 조례", "1", bcr={"계획관리": "40"}, far={"계획관리": "100"}, slope="25", forest="150"),
    row("경기도 수원시", "수원시 도시계획 조례", "2", bcr={"자연녹지": "20"}, far={"자연녹지": "100"}, slope="10"),
    row("서울특별시", "서울특별시 도시계획 조례", "3", bcr={"자연녹지": "20"}),
    row("서울특별시 강남구", "서울특별시 강남구 도시계획 조례", "4"),
    row("세종특별자치시", "세종특별자치시 도시계획 조례", "5", bcr={"계획관리": "40"}),
    row("제주특별자치도", "제주특별자치도 도시계획 조례", "6", bcr={"계획관리": "40"}),
    row("충청남도 태안군", "태안군 도시계획 조례", "7", bcr={"계획관리": "50", "자연녹지": "20"}, far={"계획관리": "100", "농림": "120"}),
]
REG = [
    {"sigungu_cd": "41550", "name": "안성시", "sido": "경기도", "parent": ""},
    {"sigungu_cd": "41111", "name": "수원시 장안구", "sido": "경기도", "parent": "수원시"},
    {"sigungu_cd": "11680", "name": "강남구", "sido": "서울특별시", "parent": ""},
    {"sigungu_cd": "36110", "name": "세종시", "sido": "세종특별자치시", "parent": ""},
    {"sigungu_cd": "50130", "name": "서귀포시", "sido": "제주특별자치도", "parent": ""},
    {"sigungu_cd": "44825", "name": "태안군", "sido": "충청남도", "parent": ""},
    {"sigungu_cd": "12210", "name": "동구", "sido": "전남광주통합특별시", "parent": ""},
]

print("1. 시·군 조례 · 구는 시 조례")
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "index.json").write_text(json.dumps(ORD, ensure_ascii=False), encoding="utf-8")
(tmp / "regions.json").write_text(json.dumps(REG, ensure_ascii=False), encoding="utf-8")
b = Z.build(tmp / "index.json", tmp / "regions.json")
sg = b["sigungu"]
check(sg["41550"]["org"] == "경기도 안성시" and sg["41550"]["level"] == "sigungu"
      and sg["41550"]["bcr"]["계획관리"] == 40 and sg["41550"]["slope_deg"] == 25 and sg["41550"]["forest_pct"] == 150,
      "안성시 → 안성시 조례 40% · 25° · 150%")
check(sg["41111"]["org"] == "경기도 수원시" and "계획관리" not in sg["41111"]["bcr"], "수원시 장안구 → 수원시 조례 (계획관리 값 없음)")

print()
print("2. 자치구·세종·제주")
check(sg["11680"]["org"] == "서울특별시" and sg["11680"]["level"] == "sido", "강남구 조례에 값이 없으면 서울특별시 조례")
check(sg["36110"]["org"] == "세종특별자치시" and sg["36110"]["bcr"]["계획관리"] == 40, "세종시 → 세종 조례")
check(sg["50130"]["org"] == "제주특별자치도", "서귀포시 → 제주 조례")
check(b["missing"] == ["12210 전남광주통합특별시 동구"], f"못 붙인 곳은 목록에 — {b['missing']}")

print()
print("3. 시행령 범위 밖 값은 버린다")
t = sg["44825"]
check("계획관리" not in t["bcr"] and t["bcr"]["자연녹지"] == 20, "태안 계획관리 50% 는 버리고 자연녹지 20% 는 남긴다")
check("농림" not in t["far"] and t["far"]["계획관리"] == 100, "용적률 농림 120% 는 버린다")
check(len(b["dropped"]) == 2 and all("태안군" in d for d in b["dropped"]), f"버린 이유 2줄 — {b['dropped']}")
check(all(v["bcr_max"] <= 90 and v["far_min"] <= v["far_max"] for v in Z.LAW.values()) and Z.LAW["계획관리"]["bcr_max"] == 40,
      "시행령 표 — 계획관리 40% · 범위가 뒤집히지 않음")

print()
print("4. 화면용 JSON")
w = Z.to_web(b)
check(set(w) == {"generated", "law", "law_source", "ord", "sg"}, "열쇠 다섯")
check(w["sg"]["41111"] == ["2", "sigungu"] and w["sg"]["11680"] == ["3", "sido"], "시군구는 [일련번호, 단계] 로 가리킨다")
check(w["ord"]["1"]["slope"] == 25 and "elev" not in w["ord"]["1"] and w["ord"]["1"]["url"].endswith("ordinSeq=1"),
      "조례는 한 번 · 빈 문턱은 안 싣는다 · 원문 링크")
y, j = Z.write(b, tmp / "z.yaml", tmp / "z.json")
check(y.read_text(encoding="utf-8").startswith("# 개발 한도") and json.loads(j.read_text(encoding="utf-8"))["sg"]["41550"][0] == "1",
      "yaml 머리말 · json 이 같은 내용")
check(Z.zone_key("계획관리지역") == "계획관리" and Z.zone_key("제1종일반주거지역") == "제1종일반주거" and Z.zone_key(None) == "",
      "용도지역 이름 → 표 열쇠")

print()
print("5. 저장소의 실제 산출")
real = json.loads((ROOT / "public" / "app" / "data" / "zoning-limits.json").read_text(encoding="utf-8"))
o = real["ord"][real["sg"]["41550"][0]]
check(o["org"] == "경기도 안성시" and o["bcr"]["계획관리"] == 40 and o["far"]["계획관리"] == 100 and o["slope"] == 25,
      f"안성시 41550 = 40% · 100% · 25° — {o.get('bcr')}")
check(len(real["sg"]) >= 240 and (ROOT / "config" / "zoning_limits.yaml").exists(), f"시군구 {len(real['sg'])}곳 · yaml 있음")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
