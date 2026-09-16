-- 0012 — 유입 경로(UTM)를 가입에 붙인다 (2026-09-16 지시 "UTM, GA 준비")
--
-- GA 로는 '방문이 몇 건인가' 는 보이지만 '누가 회원이 됐나' 는 안 보인다.
-- 광고를 한 건 돌렸을 때 알고 싶은 것은 뒤쪽이므로, 그 답은 우리 자료에
-- 있어야 한다.
--
-- ## 첫 접점을 쓴다
--
-- 광고를 보고 들어왔다가 며칠 뒤 검색으로 다시 와서 가입하는 일이 흔하다.
-- 마지막 접점만 보면 그 가입이 '자연 검색' 이 되고 광고비를 쓴 쪽이 공을
-- 못 받는다. 화면(public/lib/track.js)이 **처음 온 경로를 덮어쓰지 않고**
-- 들고 있다가, 로그인해서 /account 에 들어온 순간 비어 있는 칸만 채운다.
--
-- ## 개인을 식별하지 않는다
--
-- 담기는 것은 광고 꼬리표와 어디서 눌러 왔는지의 **도메인**뿐이다.
-- referrer 의 경로·질의는 화면에서 이미 버린다 — 거기에 검색어나 남의
-- 사이트의 개인정보가 붙어 오는 일이 있다.
--
-- 실행: Supabase 대시보드 → SQL Editor → 붙여넣기 → Run

alter table public.profile add column if not exists utm_source   text;
alter table public.profile add column if not exists utm_medium   text;
alter table public.profile add column if not exists utm_campaign text;
alter table public.profile add column if not exists utm_term     text;
alter table public.profile add column if not exists utm_content  text;
alter table public.profile add column if not exists landing_ref  text;
alter table public.profile add column if not exists landing_path text;
alter table public.profile add column if not exists landing_at   timestamptz;

-- ⚠ profile_public 뷰(0002)는 건드리지 않는다. 그 뷰가 id·nickname 두 칸만
--   내보내는 것이 RLS 를 우회해도 안전한 유일한 근거다.

-- 자기 행만 쓸 수 있다는 정책(0001 profile_self_write)이 이미 있으므로
-- 새 정책은 필요 없다. 남의 유입 경로는 못 쓴다.

-- ── 관리자 대쉬보드가 읽을 집계 ──────────────────────────────────
--
-- profile 에는 전화번호와 권한이 같이 들어 있다. 그것을 열지 않고 **셈한
-- 결과만** 돌려준다 (0008 과 같은 방식). 함수 안에서 관리자인지 다시 본다.
-- ⚠ 이 아래 집계는 2026-09-16 에 고쳤다. `group by 1` 이 묶을 칸이 아니라
-- jsonb_build_object(...) 전체를 가리켜 부를 때 죽었다. 사연은 0014 에 있다.
create or replace function public.admin_utm_stats()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  out jsonb;
begin
  if not public.is_admin() then
    raise exception '관리자만 볼 수 있습니다';
  end if;

  select jsonb_build_object(
    'generated_at', now(),
    'members', (select count(*) from profile),
    -- 꼬리표가 붙은 가입. 나머지는 '직접 들어옴' 이다 — 0 이 아니라
    -- '경로를 모른다' 이므로 따로 센다.
    'tagged',  (select count(*) from profile where utm_source is not null),
    'since',   (select min(created_at) from profile where utm_source is not null),
    'by_source', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'source', g.src, 'medium', g.med, 'n', g.n, 'last', g.last_at)
               order by g.n desc), '[]'::jsonb)
      from (
        select coalesce(utm_source, '(직접 들어옴)') as src,
               coalesce(utm_medium, '—') as med,
               count(*) as n, max(created_at) as last_at
        from profile group by 1, 2 order by count(*) desc limit 30
      ) g
    ),
    'by_campaign', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'campaign', g.camp, 'source', g.src, 'n', g.n) order by g.n desc), '[]'::jsonb)
      from (
        select utm_campaign as camp, coalesce(utm_source, '—') as src, count(*) as n
        from profile where utm_campaign is not null
        group by 1, 2 order by count(*) desc limit 30
      ) g
    ),
    'by_ref', (
      select coalesce(jsonb_agg(jsonb_build_object('ref', g.ref, 'n', g.n)
               order by g.n desc), '[]'::jsonb)
      from (
        select landing_ref as ref, count(*) as n
        from profile where landing_ref is not null
        group by 1 order by count(*) desc limit 20
      ) g
    ),
    -- 최근 14일 가입 추이. 광고를 켠 날과 견주려면 날짜가 있어야 한다.
    'by_day', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'day', g.day, 'n', g.n, 'tagged', g.tagged) order by g.day), '[]'::jsonb)
      from (
        select to_char(created_at at time zone 'Asia/Seoul', 'MM-DD') as day,
               count(*) as n,
               count(*) filter (where utm_source is not null) as tagged
        from profile where created_at > now() - interval '14 days'
        group by 1
      ) g
    )
  ) into out;
  return out;
end;
$$;

revoke all on function public.admin_utm_stats() from public, anon;
grant execute on function public.admin_utm_stats() to authenticated;
