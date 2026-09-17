-- 0017 — 가입은 이름이 겹쳐도 된다. 고치는 것은 게시판에서 (2026-09-17 지시)
--
-- 지시: "혹시 가입할 때 이름이 중복된다고 막으면 안됩니다. 가입은 되고
--        게시판 들어와 작성 시 수정유도할 수 있도록 해주세요."
--
-- 0016 이 유일 색인을 걸면서 두 가지를 같이 했다.
--   ① 이름 고치기에서 겹침을 막는다        ← 지시대로였고 그대로 둔다
--   ② 가입에서도 겹칠 수 없게 된다         ← 이번 지시가 뒤집는 것
--
-- ② 를 그때는 **꼬리를 붙여** 피했다(홍길동 → 홍길동1). 가입이 죽지는
-- 않았지만, 사람이 적은 적 없는 이름이 조용히 붙는다 — 가입한 사람은
-- 자기 이름이 바뀐 줄 모르고, 게시판에서 '홍길동1' 로 불린다.
--
-- 그래서 색인을 걷고 **겹친 채로 들어오게 둔다.** 겹친다는 사실은 글을
-- 쓰러 왔을 때 화면이 말한다(public/board/board.js). 가입 문턱에서 막는
-- 것과, 쓰기 전에 알려 주는 것은 사람이 겪는 일이 다르다.
--
-- 이름 **고치기**의 중복 검사는 그대로다 — nickname_taken() 도 그대로
-- 남는다. 다만 이제 그것이 유일한 방어선이라, 묻고 저장하기까지의 틈에
-- 같은 이름이 둘 생길 수 있다. 그것도 게시판이 잡는다.
drop index if exists public.profile_nickname_uniq;

-- 꼬리 붙이기를 뺀다. 메일 앞부분을 그대로 이름으로 쓴다 — 0016 이전과 같다.
-- 색인이 없으므로 겹쳐도 가입은 그냥 된다.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
declare
  base text;
begin
  base := btrim(coalesce(new.raw_user_meta_data->>'name',
                         split_part(new.email, '@', 1)));
  if base = '' then base := '이용자'; end if;
  insert into public.profile (id, nickname, email)
  values (new.id, base, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;
