-- 0018 — 공개 화면에서 걷어낸 서술형 주석을 관리자만 보는 자리로 (2026-09-17 지시)
--
-- 지시: "서비스 페이지에서 F12 누르면 우리의 대화와 지시 판단들이 들어
--        있습니다 … 간단한 단어들은 그냥 두고 서술형 대화들은 주석 번호를
--        부여하고 별도의 비밀 공간에 페이지 추가하여 주석 번호로 매칭하여
--        보는 형태로 관리해 주세요."
--
-- 화면의 주석은 이제 /* N0123 */ 같은 번호뿐이고, 그 번호가 가리키는 글이
-- 여기 있다. 읽기·쓰기 모두 관리자만이다 — anon 은 select 권한 자체가 없다.
--
-- **왜 파일이 아니라 표인가.** 저장소가 공개라 파일로 두면 옮긴 뜻이 없다.
-- 비공개 버킷도 생각했지만, 번호로 찾아보려면 검색이 필요하고 그것은 표가
-- 할 일이다.
create table if not exists public.code_note (
  n          int primary key,            -- 화면의 N0123 의 123
  path       text not null,              -- 어느 파일에서 걷어냈나
  line       int,                        -- 걷어낼 때의 줄 번호 (참고용 — 코드가 바뀌면 흔들린다)
  kind       text,                       -- line / block / html
  body       text not null,              -- 원문
  updated_at timestamptz not null default now()
);

alter table public.code_note enable row level security;

drop policy if exists code_note_admin_read on public.code_note;
create policy code_note_admin_read on public.code_note
  for select using (public.is_admin());
drop policy if exists code_note_admin_write on public.code_note;
create policy code_note_admin_write on public.code_note
  for all using (public.is_admin()) with check (public.is_admin());

-- anon 에게는 권한 자체를 주지 않는다. 정책은 그다음 관문이다.
revoke all on public.code_note from anon;
grant select on public.code_note to authenticated;

-- 번호가 아니라 글로도 찾을 수 있게 (관리자가 '그 얘기 어디 적었더라' 를 한다).
create index if not exists code_note_body_idx on public.code_note using gin (to_tsvector('simple', body));
