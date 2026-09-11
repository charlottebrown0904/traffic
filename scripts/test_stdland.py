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
cols2 = ["pnu", "ld_code", "stdr_year", "pblntf_pclnd", "lndcgr_code_nm", "lndpcl_ar",
         "prpos_area_1_nm", "lad_use_sittn_nm", "road_side_code_nm", "tpgrph_hg_code_nm",
         "tpgrph_frm_code_nm"]
m2, un2 = S.map_columns(cols2)
check(m2.get("stdr_year") == "year" and m2.get("pblntf_pclnd") == "price"
      and m2.get("tpgrph_frm_code_nm") == "shape", "stdr_year→year · pblntf_pclnd→price · tpgrph_frm→shape")
check(not un2, f"전부 맞는다 — 못 맞춘 것 {un2}")

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
