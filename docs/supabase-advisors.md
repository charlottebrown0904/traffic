# Supabase 어드바이저 — 무엇을 고쳤고 무엇이 남는가 (2026-09-11)

Supabase 대시보드 → Advisors 가 든 것을 `supabase/migrations/0005_advisors.sql` 로
정리했다 (적용 완료). 이 문서는 **남는 경고를 왜 남기는지** 적어 두는 자리다 —
다음에 열어 보고 "왜 안 고쳤지" 하지 않게.

## 고친 것

| 어드바이저 | 무엇 | 어떻게 |
|---|---|---|
| ERROR security_definer_view | `profile_public` 뷰 | 뷰 → **표** (id·nickname) + `profile_public_sync` 트리거. RLS 와 select 정책이 걸린 평범한 표 |
| WARN anon 이 SECURITY DEFINER 함수 실행 | `handle_new_user` · `is_admin` · `is_approved` | 가입 트리거는 `supabase_auth_admin` 만. 둘은 `authenticated` 만. 정책마다 역할을 못 박고(`to authenticated`), anon 에게는 `listing_anon_read` (status='published', 함수 호출 없음) 하나만 |
| WARN function_search_path_mutable | `touch_updated_at` | `set search_path = public`, 앱 역할 실행 회수 |
| WARN auth_rls_initplan (17) | 정책의 `auth.uid()` | 전부 `(select auth.uid())` · `(select is_admin())` |
| WARN multiple_permissive_policies (15) | `comment_write ALL`, `listing_owner_write ALL`, `profile_admin_write` | ALL 을 insert/update/delete 로 쪼갬. `profile_admin_write` 는 `profile_write` 가 품고 있어 삭제 |
| INFO unindexed_foreign_keys (8) | comment·favorite·grade_log·inquiry·post·report | 인덱스 8개 |
| (덤) | `profile` 에 `profile_guard` 트리거가 둘 | `profile_guard_trg` 삭제 |

확인 (적용 직후, SQL 로): authenticated 로 post·profile 을 update 하면 트리거가 돈다
(실행 권한을 거둬도 트리거는 만든 사람 권한으로 돈다). anon 은 post·comment·listing
0행, profile_public 4행, 오류 없음.

## 남는 것 — 의도한 것

| 어드바이저 | 왜 남기나 |
|---|---|
| WARN authenticated 가 SECURITY DEFINER 실행 (`is_admin` `is_approved` `premium_ok` `set_grade` `bump_place_view`) | 정책과 화면이 쓰는 함수다. 넷은 **호출자 자신**에 대해서만 답하고, `set_grade` 는 안에서 `is_admin` 을 다시 본다. RLS 정책이 부르는 함수는 그 역할이 실행할 수 있어야 한다 |
| INFO rls_enabled_no_policy (`appraisal_case` `appraisal_factor`) | 비공개 원장. service key 로만 읽는다 — 정책이 없는 것이 자물쇠다 |
| INFO unused_index | 아직 자료가 적어 인덱스가 안 쓰였을 뿐이다. 외래키 인덱스는 지우지 않는다 |
| WARN auth_leaked_password_protection | **대시보드 설정** — Authentication → Providers → Email → Leaked password protection 켜기. 계정 주인이 한 번 |

## 다음에 스키마를 바꾸면

정책을 새로 쓸 때 세 가지: `to authenticated` (또는 `to anon`) 를 적는다,
`auth.uid()` 는 `(select auth.uid())` 로, anon 정책에서는 SECURITY DEFINER 함수를
부르지 않는다. 그리고 Advisors 를 한 번 다시 연다.
