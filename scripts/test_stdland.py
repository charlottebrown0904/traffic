"""표준지공시지가 적재 — 열 이름을 뜻으로 맞추고 std_land 에 넣는가.

원천 셋의 열 이름을 미리 모른다. 그래서 검사는 '한글 머리글' 과
'브이월드식 snake' 둘 다 넣어 보고, 못 맞춘 열이 조용히 사라지지 않고
이름으로 돌아오는지를 본다.

  실행: python scripts/test_stdland.py   (make test 에 포함)
"""
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
from redt import db                                 # noqa: E402
db.DB_PATH = tmp / "test.duckdb"
import pandas as pd                                 # noqa: E402
from redt.collect import stdland as S               # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


print("1. 한글 머리글 (파일·odcloud)")
cols = ["고유번호", "법정동코드", "법정동명", "특수지구분명", "지번", "표준지일련번호",
        "기준연도", "공시지가", "지목", "면적", "용도지역1", "용도지역2", "이용상황",
        "주위환경", "도로접면", "지형높이", "지형형상", "공시일자", "알 수 없는 열"]
m, un = S.map_columns(cols)
check(m.get("고유번호") == "pnu" and m.get("공시지가") == "price" and m.get("지형높이") == "slope",
      "고유번호→pnu · 공시지가→price · 지형높이→slope")
check(m.get("용도지역1") == "land_use" and m.get("용도지역2") == "land_use2", "용도지역 둘을 가른다")
check(un == ["알 수 없는 열"], f"못 맞춘 열을 이름으로 돌려준다 — {un}")

print()
print("2. 브이월드식 이름")
# 2026-09-11 탐침이 실제로 돌려준 이름들 — 코드 열과 이름 열이 나란히 온다.
cols2 = ["tpgrphHgCodeNm", "stdrYear", "lndcgrCodeNm", "roadSideCodeNm", "pblntfPclnd",
         "tpgrphHgCode", "ladUseSittnNm", "ladUseSittn", "tpgrphFrmCode", "lastUpdtDt",
         "regstrSeCodeNm", "stdLandSn", "prposDstrcNm2", "prposDstrcNm1", "regstrSeCode",
         "roadDstncCode", "lndpclAr", "tpgrphFrmCodeNm", "ldCode", "ldCodeNm", "prposArea1",
         "prposAreaNm2", "prposArea2", "prposAreaNm1", "mnnmSlno", "lndcgrCode",
         "roadDstncCodeNm", "pnu", "prposDstrc2", "cnflcRt", "prposDstrc1", "roadSideCode"]
m2, un2 = S.map_columns(cols2)
check(m2.get("stdrYear") == "year" and m2.get("pblntfPclnd") == "price", "stdrYear→year · pblntfPclnd→price")
check(m2.get("tpgrphFrmCodeNm") == "shape" and m2.get("tpgrphFrmCode") == "shape_code",
      "형상은 이름 열(…Nm)이 shape, 코드 열은 shape_code")
check(m2.get("ldCode") == "ld_code" and m2.get("ldCodeNm") == "ld_name", "ldCode 와 ldCodeNm 을 가른다")
check(m2.get("prposAreaNm1") == "land_use" and m2.get("prposAreaNm2") == "land_use2"
      and m2.get("prposArea1") == "land_use_code", "용도지역은 이름 열이 land_use, 코드 열은 land_use_code")
check(m2.get("roadDstncCodeNm") == "road_dist" and m2.get("prposDstrcNm1") == "district"
      and m2.get("cnflcRt") == "cnflc_rt" and m2.get("mnnmSlno") == "jibun"
      and m2.get("stdLandSn") == "std_no", "도로거리·용도지구·저촉률·지번·일련번호")

print()
print("3. CSV → std_land (cp949, 숫자에 쉼표)")
csv = tmp / "std.csv"
df = pd.DataFrame({
    "고유번호": ["4159025329106740000", "4159025329106750000"],
    "법정동코드": ["4159025329", "4159025329"],
    "지번": ["674", "675"],
    "기준연도": ["2026", "2026"],
    "공시지가": ["272,000", "180,000"],
    "지목": ["공장용지", "전"],
    "면적": ["3,840", "1,200"],
    "용도지역1": ["계획관리지역", "계획관리지역"],
    "이용상황": ["공업용", "전"],
    "도로접면": ["소로한면", "맹지"],
    "지형높이": ["평지", "완경사"],
    "지형형상": ["사다리형", "부정형"],
})
df.to_csv(csv, index=False, encoding="cp949")
with db.connect() as con:
    info = S.load_csv(con, str(csv), chunk=1)
    n = con.execute("SELECT count(*) FROM std_land").fetchone()[0]
    row = con.execute("SELECT pnu, price, area_m2, sigungu_cd, year, source FROM std_land ORDER BY pnu").fetchone()
check(info["encoding"] == "cp949", f"인코딩을 알아낸다 — {info['encoding']}")
check(n == 2, f"두 행 — {n}")
check(row[1] == 272000.0 and row[2] == 3840.0, f"쉼표 숫자를 푼다 — {row[1]} · {row[2]}")
check(row[3] == "41590" and row[4] == 2026 and row[5] == "file", f"시군구·연도·원천 — {row[3]} {row[4]} {row[5]}")
with db.connect() as con:
    S.load_csv(con, str(csv), chunk=1)
    n2 = con.execute("SELECT count(*) FROM std_land").fetchone()[0]
check(n2 == 2, "다시 넣어도 늘지 않는다 (std_id 열쇠)")

print()
print("3-1. 2026 파일 머리글 — 연도 열이 없고 PNU 가 빈 행이 있다 (run 13 에서 std_id 가 전부 비었다)")
cols26 = ['시군구', '읍면동리', '본번지', '부번지', '시도명', '시군구명', '소재지', '일련번호', '공시지가', '지목', '면적',
          '용도지역1', '용도지역2', '용도지구1', '이용상황', '주위환경', '도로교통', '도로거리', '지세', '형상',
          '토지대장번호(PNU)', '지번구분', '전년지가', '방위']
r1 = ['41550', '25021', '0674', '0000', '경기도', '안성시', '경기도 안성시 공도읍 양기리 674', '12', '272000', '공장용지',
      '3840', '계획관리지역', '', '', '공업용', '농촌지대', '소로한면', '', '평지', '사다리형', '4155025021106740000', '1', '250000', '']
r2 = ['41550', '25021', '12', '3', '경기도', '안성시', '경기도 안성시 공도읍 양기리 산12-3', '13', '18000', '임야',
      '9000', '계획관리지역', '', '', '자연림', '농촌지대', '맹지', '', '완경사', '부정형', '1.11101E+18', '2', '17000', '']
csv26 = tmp / "국토교통부_표준지공시지가_20260101.csv"
pd.DataFrame([dict(zip(cols26, r1)), dict(zip(cols26, r2))]).to_csv(csv26, index=False, encoding="cp949")
with db.connect() as con:
    info26 = S.load_csv(con, str(csv26), chunk=10)
    got = con.execute("SELECT pnu, ld_code, jibun, year, std_id FROM std_land WHERE sigungu_cd = '41550' ORDER BY pnu").fetchall()
check(info26["rows"] == 2 and len(got) == 2, f"두 행이 들어간다 — {info26['rows']} · {got}")
check(got and got[0][3] == 2026, "연도를 파일 이름(20260101)에서 읽는다")
check(got and got[1][0] == "4155025021200120003" and got[1][2] == "산 12-3",
      f"뭉개진 PNU(1.11101E+18)는 버리고 조각으로 만든다, 본번 '12' 도 네 자리로 — {got[1][:3] if got else None}")
check(got and got[0][2] == "674" and got[0][1] == "4155025021", f"본번만 있으면 '674' · 법정동 10자리 — {got[0][:3] if got else None}")
check(all(g[4] and "None" not in g[4] and "<NA>" not in g[4] for g in got), f"std_id 가 비지 않는다 — {[g[4] for g in got]}")

print()
print("4-0. 빈 이름을 코드표로 채운다 (같은 응답 안의 짝에서 배운다)")
S._CODEBOOK.clear()
S._codebook_path = lambda: tmp / "codes.json"
rows_v = pd.DataFrame([
    {"pnu": "4146125025100000001", "ldCode": "4146125025", "stdrYear": "2025", "pblntfPclnd": "100",
     "tpgrphHgCode": "03", "tpgrphHgCodeNm": "완경사", "tpgrphFrmCode": "05", "tpgrphFrmCodeNm": "부정형",
     "roadSideCode": "12", "roadSideCodeNm": "맹지", "prposArea1": "43", "prposAreaNm1": "자연녹지지역"},
    {"pnu": "4146125025100000002", "ldCode": "4146125025", "stdrYear": "2025", "pblntfPclnd": "200",
     "tpgrphHgCode": "03", "tpgrphHgCodeNm": "", "tpgrphFrmCode": "05", "tpgrphFrmCodeNm": "",
     "roadSideCode": "12", "roadSideCodeNm": "", "prposArea1": "43", "prposAreaNm1": ""},
    {"pnu": "4146125025100000003", "ldCode": "4146125025", "stdrYear": "2025", "pblntfPclnd": "300",
     "tpgrphHgCode": "09", "tpgrphHgCodeNm": "", "tpgrphFrmCode": "05", "tpgrphFrmCodeNm": "",
     "roadSideCode": "12", "roadSideCodeNm": "", "prposArea1": "43", "prposAreaNm1": ""},
])
nv, _ = S.normalize(rows_v)
r2 = nv[nv["pnu"] == "4146125025100000002"].iloc[0]
r3 = nv[nv["pnu"] == "4146125025100000003"].iloc[0]
check(r2["slope"] == "완경사" and r2["shape"] == "부정형" and r2["road_side"] == "맹지"
      and r2["land_use"] == "자연녹지지역", "빈 이름을 같은 코드의 이름으로 채운다")
check(r3["slope"] is None or pd.isna(r3["slope"]), "못 배운 코드(09)는 비운 채 둔다 — 추측하지 않는다")
check(S._CODEBOOK["slope_code"]["03"] == "완경사", "코드표가 남는다")

print()
print("4. 브이월드 응답 꼴에서 행을 찾는다")
rows = S._rows({"referLandPrices": {"field": [{"pnu": "1", "pblntfPclnd": "100"}]}})
check(rows and rows[0]["pnu"] == "1", "중첩된 목록을 찾는다")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
