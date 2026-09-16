-- 0013 — UTM 링크 장부 · 자체 단축 링크 · 감사 로그 (2026-09-16)
--
-- 왜 이것이 필요한가. 0012 로 "회원이 어디서 왔나"(분자)는 세게 됐지만
-- **"몇 명이 눌렀나"(분모)를 못 센다.** 분모가 없으면 전환율이 안 나오고,
-- 전환율이 없으면 광고 두 개 중 어느 쪽이 나은지 끝내 모른다.
--
-- 그리고 손으로 물음표를 붙이면 오타 하나에 그 캠페인이 통째로 딴 줄로
-- 샌다. 링크를 장부에 두고 화면에서 만들면 그 일이 안 생긴다.

-- ─────────────────────────────────────────────────────────────
-- 채널 — 어디에 붙이는 링크인가
-- ─────────────────────────────────────────────────────────────
create table if not exists public.utm_channel (
  id             uuid primary key default gen_random_uuid(),
  code           text not null unique,   -- 단축 코드의 앞머리가 된다
  name           text not null,
  source         text not null,
  medium         text not null,
  -- 소재 코드를 어떻게 매기나: 안 씀 / 순번(ep01) / 날짜(0916) / 자유
  content_mode   text not null default 'none'
                 check (content_mode in ('none','serial','date','free')),
  content_prefix text,
  note           text,
  sort           integer not null default 100,
  active         boolean not null default true,
  created_at     timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────
-- 링크 — 실제로 뿌린 주소 하나하나
-- ─────────────────────────────────────────────────────────────
create table if not exists public.utm_link (
  id              uuid primary key default gen_random_uuid(),
  channel_id      uuid references public.utm_channel(id) on delete set null,
  source          text not null,
  medium          text not null,
  campaign        text not null,
  content         text,
  term            text,
  url             text not null,          -- 완성된 목적지. 리다이렉트는 이 칸만 본다
  short_code      text unique,
  label           text,
  clicks          integer not null default 0,
  last_clicked_at timestamptz,
  archived        boolean not null default false,
  created_by      uuid references auth.users(id) on delete set null,
  created_at      timestamptz not null default now(),
  -- 값이 소문자·허용문자로만 들어오게 DB 에서도 막는다. 화면이 정규화하지만
  -- 화면은 자물쇠가 아니다 — 'Naver' 와 'naver' 가 따로 세지는 사고를 막는 마지막 문.
  constraint utm_link_lower check (
    source = lower(source) and medium = lower(medium) and campaign = lower(campaign)
    and (content is null or content = lower(content))
    and (term is null or term = lower(term))
    and (short_code is null or short_code = lower(short_code))
  ),
  -- 목적지는 우리 사이트여야 한다. 오픈 리다이렉트를 DB 에서 먼저 막는다.
  constraint utm_link_own_site check (url like 'https://toji.fyi%')
);
create index if not exists idx_utm_link_channel on public.utm_link(channel_id);
create index if not exists idx_utm_link_live    on public.utm_link(archived, created_at desc);

-- ─────────────────────────────────────────────────────────────
-- 클릭 한 건 — 합계만으로는 '언제·어디서' 를 못 본다
-- 사람을 가리키는 값(IP·UA 원문)은 담지 않는다. 기기 갈래와 추천인
-- **도메인**뿐이다.
-- ─────────────────────────────────────────────────────────────
create table if not exists public.link_click (
  id           bigserial primary key,
  link_id      uuid not null references public.utm_link(id) on delete cascade,
  device       text not null default 'other' check (device in ('mobile','desktop','other')),
  referer_host text,
  at           timestamptz not null default now()
);
create index if not exists idx_link_click_link on public.link_click(link_id, at desc);

-- ─────────────────────────────────────────────────────────────
-- 감사 로그 — 어드민에 쓰기가 있으면 기록이 있어야 한다
-- 승인·등급 변경은 사람의 권한을 바꾸는 일이다. 누가 언제 했는지 남지
-- 않으면 나중에 되짚을 방법이 없다.
-- ─────────────────────────────────────────────────────────────
create table if not exists public.admin_audit (
  id         bigserial primary key,
  actor      uuid references auth.users(id) on delete set null,
  action     text not null,
  target     text not null,
  target_id  text,
  detail     jsonb,
  at         timestamptz not null default now()
);
create index if not exists idx_admin_audit_at on public.admin_audit(at desc);

-- ─────────────────────────────────────────────────────────────
-- 접근 제어 — 만드는 SQL 과 같은 파일에서 잠근다
-- ─────────────────────────────────────────────────────────────
alter table public.utm_channel enable row level security;
alter table public.utm_link    enable row level security;
alter table public.link_click  enable row level security;
alter table public.admin_audit enable row level security;

drop policy if exists utm_channel_admin on public.utm_channel;
create policy utm_channel_admin on public.utm_channel
  for all using (public.is_admin()) with check (public.is_admin());

drop policy if exists utm_link_admin on public.utm_link;
create policy utm_link_admin on public.utm_link
  for all using (public.is_admin()) with check (public.is_admin());

-- link_click 과 admin_audit 는 **정책을 두지 않는다.** 읽기는 아래 집계
-- 함수로만, 쓰기는 정의자 함수·트리거로만 한다. 정책이 없으면 RLS 가
-- 전부 막으므로 실수의 결과가 '유출' 이 아니라 '안 보임' 이 된다.

revoke all on public.utm_channel, public.utm_link,
              public.link_click, public.admin_audit from anon;

-- ─────────────────────────────────────────────────────────────
-- 단축 링크 한 번 누름 — 합계 +1 과 기록 insert 를 **한 번에**
-- 두 쿼리로 나누면 동시에 눌렸을 때 어긋난다.
-- ─────────────────────────────────────────────────────────────
create or replace function public.hit_link(
  p_code text, p_device text default 'other', p_referer text default null)
returns text
language plpgsql security definer set search_path = public
as $$
declare v_url text; v_id uuid;
begin
  update public.utm_link
     set clicks = clicks + 1, last_clicked_at = now()
   where short_code = lower(p_code) and archived = false
   returning url, id into v_url, v_id;

  if v_id is not null then
    insert into public.link_click (link_id, device, referer_host)
    values (v_id,
            case when p_device in ('mobile','desktop') then p_device else 'other' end,
            left(p_referer, 200));
  end if;
  return v_url;   -- 모르는 코드면 null. 부르는 쪽이 랜딩으로 보낸다.
end $$;

-- 리다이렉트는 로그인 없이 도는 함수(api/l.js)가 공개 키로 부른다.
-- 이 함수가 하는 일은 '코드 하나를 주소로 바꾸고 1 을 더하는 것' 뿐이라
-- 공개돼도 새는 것이 없다 — 짧은 주소를 직접 누르는 것과 같은 노출이다.
revoke all on function public.hit_link(text, text, text) from public;
grant execute on function public.hit_link(text, text, text) to anon, authenticated;

-- ─────────────────────────────────────────────────────────────
-- 어드민이 읽을 집계 — 링크마다 클릭·가입·전환율
-- profile 에는 전화번호와 권한이 같이 있다. 열지 않고 **센 결과만** 준다.
-- ─────────────────────────────────────────────────────────────
create or replace function public.admin_link_stats()
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then
    raise exception '관리자만 볼 수 있습니다';
  end if;

  select jsonb_build_object(
    'generated_at', now(),
    'channels', (
      select coalesce(jsonb_agg(to_jsonb(c) order by c.sort, c.code), '[]'::jsonb)
      from public.utm_channel c
    ),
    'links', (
      select coalesce(jsonb_agg(x order by (x->>'created_at') desc), '[]'::jsonb) from (
        select jsonb_build_object(
                 'id', l.id, 'label', l.label, 'short_code', l.short_code,
                 'source', l.source, 'medium', l.medium, 'campaign', l.campaign,
                 'content', l.content, 'term', l.term, 'url', l.url,
                 'clicks', l.clicks, 'last_clicked_at', l.last_clicked_at,
                 'archived', l.archived, 'created_at', l.created_at,
                 -- 이 조합으로 들어와 **회원이 된** 사람 수
                 'signups', (
                   select count(*) from public.profile p
                   where p.utm_source = l.source
                     and coalesce(p.utm_medium,'')   = coalesce(l.medium,'')
                     and coalesce(p.utm_campaign,'') = coalesce(l.campaign,'')
                     and coalesce(p.utm_content,'')  = coalesce(l.content,'')
                     and coalesce(p.utm_term,'')     = coalesce(l.term,'')
                 )) as x
        from public.utm_link l limit 200
      ) t
    ),
    -- 최근 14일 클릭 추이. 광고 켠 날과 견주려면 날짜가 있어야 한다.
    'clicks_by_day', (
      select coalesce(jsonb_agg(x order by x->>'day'), '[]'::jsonb) from (
        select jsonb_build_object(
                 'day', to_char(at at time zone 'Asia/Seoul', 'MM-DD'),
                 'n', count(*),
                 'mobile', count(*) filter (where device = 'mobile')) as x
        from public.link_click
        where at > now() - interval '14 days'
        group by 1 order by 1
      ) t
    ),
    'by_referer', (
      select coalesce(jsonb_agg(x order by x->>'n' desc), '[]'::jsonb) from (
        select jsonb_build_object('host', referer_host, 'n', count(*)) as x
        from public.link_click where referer_host is not null
        group by 1 order by count(*) desc limit 20
      ) t
    )
  ) into out;
  return out;
end $$;
revoke all on function public.admin_link_stats() from public, anon;
grant execute on function public.admin_link_stats() to authenticated;

-- ─────────────────────────────────────────────────────────────
-- 감사 로그 — 권한을 바꾸는 쓰기를 자동으로 남긴다
-- 화면 코드가 남기게 하면 화면을 안 거친 변경이 빠진다. 트리거는 안 빠진다.
-- ─────────────────────────────────────────────────────────────
create or replace function public.audit_profile_change()
returns trigger language plpgsql security definer set search_path = public as $$
declare d jsonb := '{}'::jsonb;
begin
  if new.role   is distinct from old.role   then d := d || jsonb_build_object('role',   jsonb_build_array(old.role, new.role)); end if;
  if new.status is distinct from old.status then d := d || jsonb_build_object('status', jsonb_build_array(old.status, new.status)); end if;
  if new.grade  is distinct from old.grade  then d := d || jsonb_build_object('grade',  jsonb_build_array(old.grade, new.grade)); end if;
  if d <> '{}'::jsonb then
    insert into public.admin_audit (actor, action, target, target_id, detail)
    values (auth.uid(), 'profile_update', 'profile', new.id::text, d);
  end if;
  return new;
end $$;

drop trigger if exists profile_audit on public.profile;
create trigger profile_audit after update on public.profile
  for each row execute function public.audit_profile_change();

create or replace function public.admin_audit_recent(p_limit int default 100)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then
    raise exception '관리자만 볼 수 있습니다';
  end if;
  select coalesce(jsonb_agg(to_jsonb(a) order by a.at desc), '[]'::jsonb) into out
  from (select * from public.admin_audit order by at desc limit least(greatest(p_limit,1), 500)) a;
  return out;
end $$;
revoke all on function public.admin_audit_recent(int) from public, anon;
grant execute on function public.admin_audit_recent(int) to authenticated;
