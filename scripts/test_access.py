"""회원 등급 뼈대 (2026-09-11 지시) — admin / A / B / C.

  1. 화면 판단(public/lib/access.js): A·admin 은 늘 열림, B 는 기간 안에서만,
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
# 어드바이저 정리 (0005, 2026-09-11)
sql5 = (ROOT / "supabase" / "migrations" / "0005_advisors.sql").read_text(encoding="utf-8")
check("revoke all on function public.handle_new_user() from public, anon, authenticated" in sql5
      and "revoke all on function public.is_admin() from public, anon" in sql5,
      "가입 트리거·is_admin 을 anon 이 못 부른다")
check("create policy listing_anon_read on public.listing for select to anon" in sql5
      and "to anon" not in sql5.replace("for select to anon\n  using (status = 'published')", "")
                                 .replace("to anon, authenticated", ""),
      "anon 정책은 매물 공개 읽기 하나뿐 — 함수 호출 없이")
check("drop view if exists public.profile_public" in sql5
      and "create table if not exists public.profile_public" in sql5
      and "id       uuid primary key references public.profile (id) on delete cascade,\n  nickname text\n)" in sql5,
      "profile_public 은 두 컬럼짜리 표 (SECURITY DEFINER 뷰 아님)")
check("auth.uid())" not in sql5.replace("(select auth.uid())", ""),
      "정책의 auth.uid() 는 전부 (select …) 로")
check("for all to authenticated" in sql5 and sql5.count("for all") == 1,
      "ALL 정책은 favorite 하나만 (나머지는 insert/update/delete 로 쪼갬)")

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
_notice = app[app.index("function premiumNotice("):app.index("function valuePanel(")]
check("등급은 관리자가 올려 드립니다" in _notice and "결제" not in _notice,
      "등급 안내는 관리자 문의로 보낸다 (결제 문구를 지어내지 않는다)")
check("acc.guest" in app and "무료 회원 가입" in app and "next=%2Fapp" in app,
      "로그인 안 한 사람(손님)에게는 가입을 권한다")
check("const tag = '회원 전용'" in app, "가치 단추 꼬리표는 '회원 전용'")
check('rpc("set_grade"' in acct and "renderMembers" in acct and "if (acc.admin) renderMembers" in acct,
      "계정 화면: 관리자에게만 회원 목록 (등급 변경 포함)")
check("approved_at" in acct and "메일 복사" in acct and "CSV" in acct and "data-sort" in acct,
      "회원 목록: 신청일·가입일 · 메일 복사 · CSV · 정렬·필터")
access_js = (ROOT / "public" / "lib" / "access.js").read_text(encoding="utf-8")
check("A: 'VIP', B: '일반', C: '손님'" in access_js and "VIP" in acct,
      "등급 이름: A→VIP · B→일반 · C→손님")
check("label: guest ? '손님'" in app,
      "로그인 없이 들어온 사람은 이름도 손님")
sql6 = (ROOT / "supabase" / "migrations" / "0006_views_24h_approved_at.sql").read_text(encoding="utf-8")
check("add column if not exists approved_at" in sql6 and "create trigger profile_stamp" in sql6,
      "가입(승인)일은 트리거가 찍는다")
check("hour < now() - interval '24 hours'" in sql6 and "n24 bigint" in sql6,
      "조회수는 시간 칸 24시간 굴림 · 옛 칸은 지운다")
check("/lib/access.js" in acct_html, "계정 화면도 같은 판단을 쓴다")

print()
print("5. Admin 전용 탭 (2026-09-12 지시) — 관리자만, 숫자는 화면 파일에 없다")
adm = (ROOT / "public" / "admin" / "admin.js").read_text(encoding="utf-8")
adm_html = (ROOT / "public" / "admin" / "index.html").read_text(encoding="utf-8")
nav = (ROOT / "public" / "lib" / "adminnav.js").read_text(encoding="utf-8")
sql8 = (ROOT / "supabase" / "migrations" / "0008_admin_stats.sql").read_text(encoding="utf-8")

check("window.accessOf" in adm and "acc.admin" in adm and "deny(" in adm,
      "화면이 관리자인지 보고, 아니면 안내만 낸다")
check("appraisal_admin_stats" in adm and "premium" in adm,
      "숫자는 관리자 전용 집계와 비공개 버킷에서 받는다")
# 이 화면 파일은 누구나 받아 볼 수 있다. 숫자를 적으면 그것이 곧 공개다.
# 격차율·배율처럼 소수점 둘 이상인 숫자가 코드에 박혀 있으면 잡는다
# (버전 꼬리표·연도는 뺀다).
import re as _re
# 1.00 · 1.000 은 '차이 없음' 이라는 중립값이라 비밀이 아니다. 그 밖의
# 소수점 둘 이상 숫자가 코드에 박혀 있으면 격차율·배율일 수 있으므로 잡는다.
_lits = [x for x in _re.findall(r"(?<![\w.])[0-9]+\.[0-9]{2,}", adm)
         if x not in ("1.00", "1.000")]
check(not _lits, f"화면 파일에 배율 같은 숫자를 박아 두지 않았다 ({_lits[:5]})")
for _k in ("road_index", "shape_index", "slope_index", "area_rules",
           "use_mismatch", "special"):
    check(f"v.{_k}" in adm, f"  {_k} 는 비공개 자료에서 읽어 그린다")
check("is_admin()" in sql8 and "security definer" in sql8,
      "집계 함수가 안에서 관리자인지 다시 본다")
check("create policy" not in sql8.lower(),
      "원장 두 표에는 여전히 정책을 만들지 않는다 (원본 행은 아무도 못 읽는다)")
check("revoke all on function public.appraisal_admin_stats() from public, anon" in sql8,
      "anon 은 집계 함수를 못 부른다")
check('data-admin-link hidden' in adm_html or 'aria-current="page"' in adm_html,
      "Admin 화면 머리띠에 Admin 자리가 있다")
for _p in ("app/index.html", "guide/index.html", "guide/law.html", "board/index.html",
           "account/index.html"):
    _t = (ROOT / "public" / _p).read_text(encoding="utf-8")
    check('href="/admin" data-admin-link hidden' in _t and "/lib/adminnav.js" in _t,
          f"  {_p} 의 Admin 링크는 기본이 숨김")
check("localStorage" in nav and "hidden" in nav and "SB" not in nav,
      "링크를 보이는 것뿐 — 로그인 연결을 부르지 않는다 (자물쇠가 아니다)")
check("tojiAdminNav" in (ROOT / "public" / "app" / "app.js").read_text(encoding="utf-8")
      and "tojiAdminNav" in acct,
      "지도·계정 화면이 로그인 상태를 알 때 링크 힌트를 갱신한다")

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
