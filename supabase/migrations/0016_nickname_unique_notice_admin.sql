-- 0016 — 표시 이름 중복 금지 · 공지는 관리자만 (2026-09-17 지시)
--
-- 지시 둘:
--   · "개인 프로필 중 이름 수정 시 중복 검사 항목 추가"
--   · "공지는 admin만 가능하도록 수정"
--
-- 둘 다 **화면에서 막는 것으로는 부족하다.** 화면은 편의고, 실제 차단은
-- 여기서 일어난다 — 누구든 공개 anon 키로 REST 를 직접 부를 수 있다.

-- ─────────────────────────────────────────────────────────────
-- ① 표시 이름은 겹치지 않는다
-- ─────────────────────────────────────────────────────────────
-- 게시판이 이름만으로 사람을 가리킨다(작성자·댓글쓴이). 같은 이름이 둘이면
-- 누가 쓴 글인지 화면에서 가를 수가 없다.
--
-- **대소문자와 앞뒤 공백을 무시하고** 센다. '토지랩' 과 '토지랩 ' 과
-- 'TojiLab' / 'tojilab' 이 서로 다른 사람처럼 보이면 막는 뜻이 없다.
-- 비어 있는 이름은 여럿이어도 된다 — 아직 안 정한 것은 겹친 것이 아니다.
create unique index if not exists profile_nickname_uniq
  on public.profile (lower(btrim(nickname)))
  where nickname is not null and btrim(nickname) <> '';

-- **가입이 이 잠금에 걸려 죽으면 안 된다.**
-- handle_new_user 는 메일 주소 앞부분을 기본 이름으로 넣는다. 도메인만 다른
-- 같은 아이디(a@x.com · a@y.com)가 둘 오면 두 번째 가입이 통째로 실패한다 —
-- 트리거 안에서 터진 예외는 auth.users 삽입까지 되돌리기 때문이다.
-- 그래서 비어 있는 이름을 찾을 때까지 꼬리를 붙인다.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
declare
  base text;
  want text;
  i    int := 0;
begin
  base := btrim(coalesce(new.raw_user_meta_data->>'name',
                         split_part(new.email, '@', 1)));
  if base = '' then base := '이용자'; end if;
  want := base;
  -- 스무 번이면 충분하다. 그래도 못 찾으면 uuid 앞 여덟 자를 붙인다.
  while exists (select 1 from public.profile
                 where lower(btrim(nickname)) = lower(want)) loop
    i := i + 1;
    exit when i > 20;
    want := base || i::text;
  end loop;
  if exists (select 1 from public.profile
              where lower(btrim(nickname)) = lower(want)) then
    want := base || '-' || substr(new.id::text, 1, 8);
  end if;

  insert into public.profile (id, nickname, email)
  values (new.id, want, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

-- 화면이 저장을 누르기 **전에** 물어볼 자리.
--
-- profile 은 본인 행만 읽히므로 화면에서 직접 셀 수가 없다. profile_public
-- 뷰로 세는 길도 있지만, 그러면 대소문자·공백 규칙이 화면과 색인 두 곳에
-- 따로 적히고 언젠가 갈라진다. 규칙을 **여기 한 곳**에 둔다.
--
-- 내 이름은 내가 쓸 수 있다 — 안 바꾸고 저장하는 것도 흔한 일이다.
create or replace function public.nickname_taken(p_nick text)
returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.profile
     where lower(btrim(nickname)) = lower(btrim(p_nick))
       and id <> coalesce(auth.uid(), '00000000-0000-0000-0000-000000000000'::uuid)
  );
$$;
revoke all on function public.nickname_taken(text) from public, anon;
grant execute on function public.nickname_taken(text) to authenticated;

-- ─────────────────────────────────────────────────────────────
-- ② 공지는 관리자만 — 넣을 때뿐 아니라 **고칠 때도**
-- ─────────────────────────────────────────────────────────────
-- post_insert 는 처음부터 공지를 막고 있었다. post_update 가 안 막고 있었다.
--
--   자유로 글을 쓴다  →  그 글의 category 를 notice 로 바꾼다  →  공지가 된다
--
-- 글쓴이는 제 글을 고칠 수 있으니 정책이 통과시킨다. 화면에 수정 칸이 없어
-- 눈에 안 띄었을 뿐, 공개 키로 REST 를 직접 부르면 되는 일이었다.
-- 관리자가 남의 글을 공지로 올리는 것은 그대로 둔다 — 신고 처리와 같은 권한이다.
drop policy if exists post_update on public.post;
create policy post_update on public.post
  for update using (user_id = auth.uid() or public.is_admin())
  with check (
    (user_id = auth.uid() or public.is_admin())
    and (category <> 'notice' or public.is_admin())
  );
