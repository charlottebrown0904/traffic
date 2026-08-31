-- 사도 토지 — 회원·매물·게시판 스키마
--
-- SQLite 판(src/redt/server/store.py)을 옮기되 두 가지가 달라진다.
--   1. 비밀번호를 우리가 보관하지 않는다. 로그인은 Supabase Auth(구글·애플·카카오)가
--      맡고, 우리 테이블은 auth.users 를 참조만 한다. 유출될 비밀번호가 없다.
--   2. 접근 제어를 애플리케이션 코드가 아니라 RLS 로 건다. 코드에 구멍이 나도
--      데이터베이스가 막는다.
--
-- 실행: Supabase 대시보드 → SQL Editor → 붙여넣기 → Run

-- ─────────────────────────────────────────────────────────────
-- 프로필 — auth.users 1:1
-- ─────────────────────────────────────────────────────────────
create table if not exists public.profile (
  id          uuid primary key references auth.users(id) on delete cascade,
  role        text not null default 'user'      -- user / broker / admin
              check (role in ('user','broker','admin')),
  nickname    text,
  phone       text,
  created_at  timestamptz not null default now()
);

-- 가입하면 프로필이 자동으로 생기게 한다. 앱이 만들도록 두면
-- 소셜 로그인 도중 이탈했을 때 유령 계정이 남는다.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profile (id, nickname)
  values (new.id, coalesce(new.raw_user_meta_data->>'name', split_part(new.email, '@', 1)))
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ─────────────────────────────────────────────────────────────
-- 중개사 — 공인중개사법 제18조의2 표시·광고 명시사항
-- ─────────────────────────────────────────────────────────────
create table if not exists public.broker (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null unique references auth.users(id) on delete cascade,
  office_name    text not null,        -- 중개사무소 명칭
  office_address text not null,        -- 소재지
  license_no     text not null,        -- 등록번호
  agent_name     text not null,        -- 개업공인중개사 성명
  phone          text not null,
  license_file   text,                 -- 등록증 이미지 (Storage 경로)
  status         text not null default 'pending'
                 check (status in ('pending','verified','suspended')),
  created_at     timestamptz not null default now()
);
create index if not exists idx_broker_status on public.broker(status);

-- ─────────────────────────────────────────────────────────────
-- 매물
-- ─────────────────────────────────────────────────────────────
create table if not exists public.listing (
  id            uuid primary key default gen_random_uuid(),
  broker_id     uuid not null references public.broker(id) on delete cascade,
  kind          text not null check (kind in ('land','factory','house','commercial')),
  deal_type     text not null check (deal_type in ('sale','lease')),
  address       text not null,
  lat           double precision,
  lon           double precision,
  area_m2       double precision not null check (area_m2 > 0),
  price_manwon  bigint not null check (price_manwon > 0),
  jimok         text,
  land_use      text,
  memo          text,
  contact_phone text not null,
  status        text not null default 'draft'
                check (status in ('draft','pending_review','published','expired','hidden')),
  paid_until    timestamptz,
  -- 등록 시점에 계산해 굳혀둔다. 영업소 좌표가 갱신돼도 매물 표시가 흔들리지 않게.
  nearest_tollgate_id text,
  nearest_name        text,
  nearest_km          double precision,
  band                text,
  view_count    integer not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists idx_listing_status   on public.listing(status);
create index if not exists idx_listing_broker   on public.listing(broker_id);
create index if not exists idx_listing_tollgate on public.listing(nearest_tollgate_id);
create index if not exists idx_listing_kind     on public.listing(kind, deal_type);

-- ─────────────────────────────────────────────────────────────
-- 관심 매물 · 문의 · 신고
-- ─────────────────────────────────────────────────────────────
create table if not exists public.favorite (
  user_id    uuid not null references auth.users(id) on delete cascade,
  listing_id uuid not null references public.listing(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, listing_id)
);

create table if not exists public.inquiry (
  id         uuid primary key default gen_random_uuid(),
  listing_id uuid not null references public.listing(id) on delete cascade,
  user_id    uuid references auth.users(id) on delete set null,
  message    text not null,
  phone      text,
  created_at timestamptz not null default now()
);
create index if not exists idx_inquiry_listing on public.inquiry(listing_id);

create table if not exists public.report (
  id         uuid primary key default gen_random_uuid(),
  listing_id uuid not null references public.listing(id) on delete cascade,
  user_id    uuid references auth.users(id) on delete set null,
  reason     text not null,
  detail     text,
  status     text not null default 'open' check (status in ('open','resolved','rejected')),
  created_at timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────
-- 게시판
-- ─────────────────────────────────────────────────────────────
create table if not exists public.post (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  category   text not null default 'free'
             check (category in ('free','question','notice')),
  title      text not null check (char_length(title) between 1 and 200),
  body       text not null,
  is_deleted boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_post_created on public.post(created_at desc);

create table if not exists public.comment (
  id         uuid primary key default gen_random_uuid(),
  post_id    uuid not null references public.post(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  body       text not null,
  is_deleted boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists idx_comment_post on public.comment(post_id, created_at);

-- ─────────────────────────────────────────────────────────────
-- 접근 제어 (RLS)
--
-- 모든 테이블을 잠근 뒤 필요한 것만 연다. 정책을 빠뜨리면 막히는 쪽으로
-- 실패하므로, 실수의 결과가 '유출'이 아니라 '안 보임'이 된다.
-- ─────────────────────────────────────────────────────────────
alter table public.profile  enable row level security;
alter table public.broker   enable row level security;
alter table public.listing  enable row level security;
alter table public.favorite enable row level security;
alter table public.inquiry  enable row level security;
alter table public.report   enable row level security;
alter table public.post     enable row level security;
alter table public.comment  enable row level security;

create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.profile where id = auth.uid() and role = 'admin');
$$;

-- 프로필: 본인 것만
drop policy if exists profile_self_read on public.profile;
create policy profile_self_read on public.profile
  for select using (id = auth.uid() or public.is_admin());
drop policy if exists profile_self_write on public.profile;
create policy profile_self_write on public.profile
  for update using (id = auth.uid()) with check (id = auth.uid());

-- 중개사: 본인 것만 읽고 쓴다. 승인은 관리자만.
drop policy if exists broker_self_read on public.broker;
create policy broker_self_read on public.broker
  for select using (user_id = auth.uid() or public.is_admin());
drop policy if exists broker_self_insert on public.broker;
create policy broker_self_insert on public.broker
  for insert with check (user_id = auth.uid());
drop policy if exists broker_self_update on public.broker;
create policy broker_self_update on public.broker
  for update using (user_id = auth.uid() or public.is_admin())
  -- 본인이 스스로를 verified 로 바꾸지 못하게 막는다.
  with check (public.is_admin() or status = 'pending');

-- 매물: 게시된 것은 누구나. 그 외에는 올린 중개사와 관리자만.
drop policy if exists listing_public_read on public.listing;
create policy listing_public_read on public.listing
  for select using (
    status = 'published'
    or public.is_admin()
    or broker_id in (select id from public.broker where user_id = auth.uid())
  );
drop policy if exists listing_owner_write on public.listing;
create policy listing_owner_write on public.listing
  for all using (
    broker_id in (select id from public.broker where user_id = auth.uid()) or public.is_admin()
  ) with check (
    broker_id in (
      -- 승인된 중개사만 매물을 올릴 수 있다.
      select id from public.broker where user_id = auth.uid() and status = 'verified'
    ) or public.is_admin()
  );

-- 관심 매물: 본인 것만
drop policy if exists favorite_self on public.favorite;
create policy favorite_self on public.favorite
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- 문의: 남기는 것은 로그인한 사람, 읽는 것은 보낸 사람과 해당 매물의 중개사
drop policy if exists inquiry_insert on public.inquiry;
create policy inquiry_insert on public.inquiry
  for insert with check (auth.uid() is not null);
drop policy if exists inquiry_read on public.inquiry;
create policy inquiry_read on public.inquiry
  for select using (
    user_id = auth.uid()
    or public.is_admin()
    or listing_id in (
      select l.id from public.listing l
      join public.broker b on b.id = l.broker_id
      where b.user_id = auth.uid()
    )
  );

-- 신고: 누구나 넣고, 읽는 것은 관리자와 신고한 본인
drop policy if exists report_insert on public.report;
create policy report_insert on public.report
  for insert with check (auth.uid() is not null);
drop policy if exists report_read on public.report;
create policy report_read on public.report
  for select using (user_id = auth.uid() or public.is_admin());

-- 게시판: 삭제되지 않은 글은 누구나 읽고, 쓰기는 본인 글만
drop policy if exists post_read on public.post;
create policy post_read on public.post
  for select using (is_deleted = false or user_id = auth.uid() or public.is_admin());
drop policy if exists post_insert on public.post;
create policy post_insert on public.post
  for insert with check (
    user_id = auth.uid()
    -- 공지는 관리자만
    and (category <> 'notice' or public.is_admin())
  );
drop policy if exists post_update on public.post;
create policy post_update on public.post
  for update using (user_id = auth.uid() or public.is_admin())
  with check (user_id = auth.uid() or public.is_admin());

drop policy if exists comment_read on public.comment;
create policy comment_read on public.comment
  for select using (is_deleted = false or user_id = auth.uid() or public.is_admin());
drop policy if exists comment_write on public.comment;
create policy comment_write on public.comment
  for all using (user_id = auth.uid() or public.is_admin())
  with check (user_id = auth.uid());

-- updated_at 자동 갱신
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

drop trigger if exists listing_touch on public.listing;
create trigger listing_touch before update on public.listing
  for each row execute function public.touch_updated_at();
drop trigger if exists post_touch on public.post;
create trigger post_touch before update on public.post
  for each row execute function public.touch_updated_at();
