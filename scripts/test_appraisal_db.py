"""감정평가 인자 DB 읽기 — 비공개 원천이 없을 때 조용히 비고, 있을 때 같은 꼴로 오는가.

Supabase 는 여기서 못 부른다 (키가 없고, 있어도 검사에서 부르지 않는다).
그래서 본다:
  1. 환경변수도 손 사본도 없으면 빈 목록 — 예외도, 지어낸 값도 없다.
  2. 손 사본(tsv)이 있으면 그것을 읽는다.
  3. REST 가 주는 None 을 '' 로 맞춘다 (valuation 이 문자열 메서드를 바로 쓴다).
  4. 조건별 집계는 개별 건을 내보내지 않는다 (n·중앙·사분위·사유만).
  5. 저장소에 원장 파일이 없다 — 2026-09-11 지시 "외부에서 볼 수 없게".

  실행: python scripts/test_appraisal_db.py   (make test 에 포함)
"""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_KEY", None)

from redt import appraisal_db as A                  # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


tmp = pathlib.Path(tempfile.mkdtemp())

print("1. 원천이 없으면 빈 목록")
A.PRIVATE_LEDGER = tmp / "none.tsv"
A.clear_cache()
check(not A.configured(), "환경변수 없음 → configured() 거짓")
check(A.load_cases() == [] and A.load_factors() == [], "cases·factors 둘 다 []")
check(A.source() == "none", f"source() = {A.source()}")

print()
print("1-1. 시크릿에 키를 넣는 실수를 견딘다")
os.environ["SUPABASE_URL"] = "sb_publishable_abc"
check(A.base_url() == A.DEFAULT_URL, "주소 자리에 키가 오면 프로젝트 기본 주소")
os.environ["SUPABASE_URL"] = "caykbxvnebpifcduqjre.supabase.co"
check(A.base_url() == "https://caykbxvnebpifcduqjre.supabase.co", "스킴이 없으면 https 를 붙인다")
os.environ.pop("SUPABASE_URL", None)
check(A.base_url() == A.DEFAULT_URL, "비어 있으면 기본 주소")
os.environ["SUPABASE_SERVICE_KEY"] = "sb_publishable_abc"
check(A.key_kind() == "publishable", "publishable 키를 알아본다")
try:
    A._rest("appraisal_case")
    check(False, "publishable 키로는 읽지 않는다")
except RuntimeError as e:
    check("publishable" in str(e), "publishable 키면 이유를 말하고 멈춘다")
os.environ.pop("SUPABASE_SERVICE_KEY", None)
A.clear_cache()

print()
print("2. 손 사본이 있으면 읽는다")
(tmp / "ledger.tsv").write_text("file_id\tsido\tsigungu\tf_other\n"
                                "abc\t경기\t안성시\t2.3\n", encoding="utf-8")
A.PRIVATE_LEDGER = tmp / "ledger.tsv"
A.clear_cache()
rows = A.load_cases()
check(len(rows) == 1 and rows[0]["sigungu"] == "안성시" and rows[0]["f_other"] == "2.3",
      "tsv 한 행 → dict")
check(A.source() == "private-file", "source() = private-file")

print()
print("3. None → ''")
n = A.normalize([{"a": None, "b": 1.5, "c": "x"}])
check(n == [{"a": "", "b": 1.5, "c": "x"}], "None 만 '' 로, 숫자는 그대로")

print()
print("4. 조건별 집계 — 개별 건은 안 나간다")
fs = A.factor_summary([
    {"file_id": "f1", "group_nm": "가로조건", "ratio": 1.2, "why": None},
    {"file_id": "f2", "group_nm": "가로조건", "ratio": 0.95, "why": "농로"},
    {"file_id": "f3", "group_nm": "가로조건", "ratio": 1.1, "why": ""},
    {"file_id": "f4", "group_nm": "획지조건", "ratio": 0.35, "why": "현황 도로"},
    {"file_id": "f5", "group_nm": "", "ratio": 1.0, "why": ""},
])
g = fs.get("가로조건")
check(g and g["n"] == 3 and g["median"] == 1.1 and g["below_1"] == 1 and g["above_1"] == 2,
      f"가로조건 n=3 중앙 1.1 ↓1 ↑2 — {g}")
check("file_id" not in str(fs) and "f1" not in str(fs), "file_id 가 집계에 없다")
check("" not in fs, "조건 이름이 빈 행은 버린다")

print()
print("5. 저장소에 원장 파일이 없다")
tracked = subprocess.run(["git", "ls-files", "data/appraisal", "data/private"], cwd=ROOT,
                         capture_output=True, text=True).stdout.split()
check(not tracked, f"data/appraisal · data/private 에 추적 파일 없음 — {tracked}")
check("data/private/" in (ROOT / ".gitignore").read_text(encoding="utf-8"), ".gitignore 에 data/private/")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
