# 회원 등급 — admin · A · B · C (뼈대, 2026-09-11)

지시: "'현재 가치'와 '미래 가치'는 프리미엄 서비스입니다. 회원 등급 구분부터
해서 등급별로 접근 영역을 설정합니다." 결제 방식·문구는 **아직 확정이 아니다**.

## 1. 등급

| 등급 | 뜻 | 프리미엄(현재 가치·미래 가치) | 등급 변경 |
|---|---|---|---|
| admin | 모든 권한 | 본다 | **할 수 있다** (남의 등급) |
| A | 제한 없음 — 결제 없이 열어 주는 계정 | 본다 | 못 한다 |
| B | 유료 프리미엄. `grade_until` 이 있으면 그날까지 | 기간 안에서 본다 | 못 한다 |
| C | 무료 회원 (가입 기본값) | 못 본다 — 누르면 안내 | 못 한다 |

승인(status: pending/approved/rejected)과 역할(role: user/broker/admin)은 그대로다.
등급은 **승인된 사람 안에서** 무엇을 더 볼 수 있는가다. 승인 전이면 A 여도 못 본다.

## 2. 어디에 무엇이 있나

| 층 | 파일 | 하는 일 |
|---|---|---|
| 데이터베이스 (**자물쇠**) | `supabase/migrations/0003_grade.sql` | `profile.grade/grade_until/grade_note` · `grade_log` · 트리거 `profile_guard`(본인은 등급·역할·상태를 못 고침) · `set_grade()`(관리자만, 기록) · `premium_ok()`(서버용 판정) · `is_admin()` 이 grade=admin 도 봄 |
| 판단 한 곳 | `public/lib/access.js` | `accessOf(profile)` → `{grade, label, premium, expired, admin}`. 지도·계정 화면이 같이 쓴다 |
| 관문 | `public/app/gate.js` | 승인 확인 뒤 `window.ME = me` 를 두고 앱을 붙인다 |
| 지도 | `public/app/app.js` `myAccess`·`valueButtons`·`premiumNotice` | C·기간 만료면 단추에 '프리미엄' 꼬리표, 누르면 산출 대신 안내 |
| 계정 | `public/account/account.js` | 내 등급·기한 표시. 관리자에게는 **회원 등급 목록**(승인된 회원 · 등급 선택 · B 만료일 · 저장 → `set_grade`) |

이미 적용: 이주 SQL 은 2026-09-11 Supabase 에 넣었다 (`grade_admin_a_b_c`). 기존
관리자 계정(role=admin)은 admin 등급이 됐고, 나머지는 C 다.

## 3. 무엇이 자물쇠이고 무엇이 편의인가

- **자물쇠**: 본인이 REST 로 자기 `grade`·`status` 를 못 바꾼다(트리거). 등급 변경은
  관리자만, 기록이 남는다. 서버 코드는 `select premium_ok()` 하나로 판정한다.
- **편의**: 지도의 가림. 현재 가치의 숫자 원천(`/app/data/valuation.json`, 표준지 조각
  `stdland-*.json`)은 아직 **정적 파일**이라 주소를 알면 받을 수 있다. 화면 코드도
  공개 저장소에 있다. 그래서 지금 뼈대는 '보이는 것을 정리한 것' 이지 유료 자료를
  잠근 것이 아니다.

## 4. 다음 — 진짜 자물쇠

1. 격차율 표(`valuation.json`)와 표준지 조각을 `public/` 밖으로 옮기고, Vercel 함수
   (`api/premium.js`)가 브라우저의 Supabase 토큰을 받아 `premium_ok()` 로 확인한 뒤
   내어 준다. 앱은 그 주소로 바꾼다. 표준지 조각은 시군구별 최대 1.7MB 라 함수로
   내보내도 된다.
2. 결제: 확정되면 `grade_log` 에 결제 건을 잇고, 결제 웹훅이 `set_grade(B, until)` 을
   부른다. 안내 문구(`premiumNotice`)를 그때 확정 문구로 바꾼다.
3. 미래 가치 산출이 붙으면 같은 문에서 걸린다 — `VALUE_SERVICES` 두 단추가 한
   `wireValueButtons` 를 지나므로 따로 할 일은 없다.

## 5. 관리자가 하는 법 (휴대폰)

내 계정(/account) → 아래 '회원 등급' 목록 → 사람 옆 등급을 고르고, B 면 만료일을
적고 → 저장. 승인 대기 목록과 같은 자리다. 바꾼 내역은 `grade_log` 에 남는다.

검사: `scripts/test_access.py`(판단·SQL·배선), `scripts/test_map.js`(C 잠김 · 기간 만료 · B 열림).
