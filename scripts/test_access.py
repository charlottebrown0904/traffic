"""회원 등급 뼈대 (2026-09-11 지시) — admin / A / B / C.

  1. 화면 판단(public/lib/access.js): A·admin 은 늘 프리미엄, B 는 기간 안에서만,
     C 는 아니다. 승인 전이면 등급이 높아도 아니다.
  2. 자물쇠는 데이터베이스: 이주 SQL 에 본인이 등급·상태를 못 고치는 트리거,
     관리자만 부르는 set_grade, 서버용 premium_ok 가 있다.
  3. 관문이 프로필을 앱에 넘기고(window.ME), 앱은 그것으로 가린다.

  실행: python scripts/test_access.py   (make test 에 포함)
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
fail = []


def check(ok, label, extra=""):
    print(f"  {'✓' if ok else '✗'} {label}" + (f" — {extra}" if extra and not ok else ""))
    if not ok:
        fail.append(label)


print("1. 등급 → 프리미엄 판단 (access.js 를 node 로 돌린다)")
cases = {
    "admin": {"status": "approved", "grade": "admin"},
    "A": {"status": "approved", "grade": "A"},
    "B": {"status": "approved", "grade": "B"},
    "B_live": {"status": "approved", "grade": "B", "grade_until": "2999-01-01T00:00:00Z"},
    "B_expired": {"status": "approved", "grade": "B", "grade_until": "2020-01-01T00:00:00Z"},
    "C": {"status": "approved", "grade": "C"},
    "none": {"status": "approved"},
    "A_pending": {"status": "pending", "grade": "A"},
    "role_admin": {"status": "approved", "grade": "C", "role": "admin"},
}
js = f"""
const window = {{}}; globalThis.window = window;
{(ROOT / 'public' / 'lib' / 'access.js').read_text(encoding='utf-8')}
const cases = {json.dumps(cases)};
const out = {{}};
for (const [k, p] of Object.entries(cases)) {{ const a = window.accessOf(p); out[k] = {{ premium: a.premium, expired: a.expired, admin: a.admin, grade: a.grade }}; }}
console.log(JSON.stringify(out));
"""
res = subprocess.run(["node", "-e", js], capture_output=True, text=True)
out = json.loads(res.stdout.strip() or "{}")
check(out["admin"]["premium"] and out["A"]["premium"] and out["B"]["premium"] and out["B_live"]["premium"],
      "admin·A·B(기한 없음·기한 안) 은 프리미엄", res.stderr[:200])
check(not out["B_expired"]["premium"] and out["B_expired"]["expired"], "B 기한 지나면 아니다 · expired 표시")
check(not out["C"]["premium"] and not out["none"]["premium"] and out["none"]["grade"] == "C", "C 와 등급 없음은 아니다 (기본 C)")
check(not out["A_pending"]["premium"], "승인 전이면 등급이 높아도 아니다")
check(out["admin"]["admin"] and out["role_admin"]["admin"] and not out["A"]["admin"], "admin 판정은 grade 나 role 로")

print()
print("2. 자물쇠는 데이터베이스 — 이주 SQL")
sql = (ROOT / "supabase" / "migrations" / "0003_grade.sql").read_text(encoding="utf-8")
check("check (grade in ('admin', 'A', 'B', 'C'))" in sql, "grade 열은 네 값만")
check("create trigger profile_guard before update on public.profile" in sql
      and "new.status is distinct from old.status" in sql and "not public.is_admin()" in sql,
      "본인이 등급·역할·상태를 못 고치는 트리거")
check("function public.set_grade(" in sql and "insert into public.grade_log" in sql
      and "revoke all on function public.set_grade" in sql, "set_grade 는 관리자만 · 기록 남김 · anon 못 부름")
check("function public.premium_ok()" in sql and "grade_until is null or grade_until > now()" in sql,
      "서버용 premium_ok — B 는 기한 안에서만")
check("or grade = 'admin'" in sql, "is_admin 이 grade=admin 도 본다")

print()
print("3. 관문 → 앱 → 계정 화면")
gate = (ROOT / "public" / "app" / "gate.js").read_text(encoding="utf-8")
app = (ROOT / "public" / "app" / "app.js").read_text(encoding="utf-8")
html = (ROOT / "public" / "app" / "index.html").read_text(encoding="utf-8")
acct = (ROOT / "public" / "account" / "account.js").read_text(encoding="utf-8")
acct_html = (ROOT / "public" / "account" / "index.html").read_text(encoding="utf-8")
check("window.ME = me;" in gate and gate.index("window.ME = me;") < gate.index("enter();\n    } catch"),
      "관문이 승인 뒤 프로필을 window.ME 에 두고 앱을 붙인다")
check(html.index("/lib/access.js") < html.index("/app/gate.js"), "access.js 가 관문보다 먼저 실린다")
check("if (!acc.premium) {\n      box.innerHTML = premiumNotice(key, acc);\n      return;\n    }" in app,
      "프리미엄이 아니면 산출 대신 안내")
check("준비 중입니다" in app and "결제" in app, "결제 안내는 '준비 중' 이라 적는다 (문구 미확정)")
check('rpc("set_grade"' in acct and "renderGrades" in acct and "acc.admin" in acct, "계정 화면: 관리자만 등급 변경 목록")
check("/lib/access.js" in acct_html, "계정 화면도 같은 판단을 쓴다")

print()
print("4. 진짜 자물쇠 — 숫자 원천은 비공개 버킷에서만")
sql4 = (ROOT / "supabase" / "migrations" / "0004_premium_storage.sql").read_text(encoding="utf-8")
check("values ('premium', 'premium', false" in sql4 and "bucket_id = 'premium' and public.premium_ok()" in sql4
      and "to authenticated" in sql4, "버킷은 비공개 · 읽기 정책은 로그인 + premium_ok")
check("sb.storage.from('premium').download(name)" in app and "premiumFetch('valuation.json')" in app
      and "premiumFetch(`stdland-${code}.json`)" in app, "앱은 격차율 표·표준지 조각을 버킷에서 받는다")
wx = (ROOT / "src" / "redt" / "webexport.py").read_text(encoding="utf-8")
check('_write("valuation.json"' not in wx and '_pwrite("valuation.json"' in wx and "PS.sync()" in wx,
      "내보내기는 public/ 에 안 쓰고 버킷에 올린다")
cfg = (ROOT / "public" / "app" / "config.js").read_text(encoding="utf-8")
check("stdlandBase" not in cfg and "jsdelivr" not in cfg, "공개 CDN 주소가 없다")
ps = (ROOT / "src" / "redt" / "premium_store.py").read_text(encoding="utf-8")
check('os.environ["SUPABASE_SERVICE_KEY"]' in ps and "x-upsert" in ps, "올리기는 service key 로만 · 덮어쓰기")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
