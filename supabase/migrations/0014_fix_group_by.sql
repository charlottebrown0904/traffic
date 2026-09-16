-- 0014 — 집계 함수 둘이 부를 때 터졌다 (2026-09-16)
--
-- 증상
--   어드민 대쉬보드가 "aggregate functions are not allowed in GROUP BY" 를
--   받고 '아직 장부를 못 받습니다' 를 띄웠다. 유입 경로 칸(0012)과 링크
--   칸(0013) **둘 다**.
--
-- 원인
--   `group by 1` 을 썼는데, 그 1번이 가리키는 것이 묶을 칸이 아니라
--   **select 의 첫 출력식 = jsonb_build_object(...) 전체**였다. 그 안에
--   count(*) 가 들어 있으니 "집계를 GROUP BY 에 둘 수 없다" 가 맞는 말이다.
--
--       select jsonb_build_object('host', referer_host, 'n', count(*)) as x
--       from link_click group by 1        -- ← 1 = jsonb_build_object(...)
--
-- 왜 안 걸렸나
--   **plpgsql 은 함수 안의 SQL 을 부를 때 컴파일한다.** CREATE FUNCTION 은
--   성공하고, 처음 호출될 때 터진다. 그래서 '적용 성공' 을 보고 됐다고
--   믿었다. 검사도 마이그레이션의 **글자**만 정규식으로 봤지 돌려 보지
--   않았다. scripts/test_links.js 에 그 꼴을 잡는 검사를 더한다.
--
-- 고침
--   먼저 평범한 칸으로 묶어 센 뒤, 그 결과를 jsonb 로 감싼다.
--   덤으로 정렬도 고쳤다 — `order by x->>'n' desc` 는 **글자**로 견주어
--   '9' 가 '10' 보다 크다. 숫자 칸으로 정렬한다.
--
-- 이 파일은 0012·0013 의 두 함수를 **최종 모양으로** 다시 만든다.
-- (기간 인자 p_days 도 여기 들어 있다 — 0013 판에는 없었다.)

create or replace function public.admin_utm_stats()
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
    'members', (select count(*) from profile),
    -- 꼬리표가 붙은 가입. 나머지는 '직접 들어옴' 이다 — 0 이 아니라 '모른다'.
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
end $$;
revoke all on function public.admin_utm_stats() from public, anon;
grant execute on function public.admin_utm_stats() to authenticated;


-- 기간을 골라 볼 수 있다. p_days 가 null 이면 전체.
-- 클릭에는 시각(link_click.at)이 있어 기간이 먹는다. 가입은 그 링크로 들어온
-- 시각이 따로 없어 profile.created_at 을 같은 기간으로 자른다.
create or replace function public.admin_link_stats(p_days int default null)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare out jsonb; since timestamptz;
begin
  if not public.is_admin() then
    raise exception '관리자만 볼 수 있습니다';
  end if;
  since := case when p_days is null then '-infinity'::timestamptz
                else now() - make_interval(days => greatest(p_days, 0)) end;

  select jsonb_build_object(
    'generated_at', now(),
    'days', p_days,
    'channels', (
      select coalesce(jsonb_agg(to_jsonb(c) order by c.sort, c.code), '[]'::jsonb)
      from public.utm_channel c
    ),
    'links', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'id', l.id, 'label', l.label, 'short_code', l.short_code,
               'source', l.source, 'medium', l.medium, 'campaign', l.campaign,
               'content', l.content, 'term', l.term, 'url', l.url,
               'clicks_all', l.clicks,
               'clicks', (select count(*) from public.link_click c
                           where c.link_id = l.id and c.at >= since),
               'last_clicked_at', l.last_clicked_at,
               'archived', l.archived, 'created_at', l.created_at,
               -- 이 조합으로 들어와 **회원이 된** 사람 수
               'signups', (
                 select count(*) from public.profile p
                 where p.utm_source = l.source
                   and coalesce(p.utm_medium,'')   = coalesce(l.medium,'')
                   and coalesce(p.utm_campaign,'') = coalesce(l.campaign,'')
                   and coalesce(p.utm_content,'')  = coalesce(l.content,'')
                   and coalesce(p.utm_term,'')     = coalesce(l.term,'')
                   and p.created_at >= since))
               order by l.created_at desc), '[]'::jsonb)
      from public.utm_link l
    ),
    'by_source', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'source', g.source, 'medium', g.medium, 'links', g.links,
               'clicks', g.clicks,
               'signups', (select count(*) from public.profile p
                            where p.utm_source = g.source
                              and coalesce(p.utm_medium,'') = coalesce(g.medium,'')
                              and p.created_at >= since))
               order by g.clicks desc), '[]'::jsonb)
      from (
        select l.source, l.medium, count(*) as links,
               coalesce(sum((select count(*) from public.link_click c
                              where c.link_id = l.id and c.at >= since)), 0) as clicks
        from public.utm_link l where not l.archived
        group by l.source, l.medium
      ) g
    ),
    'by_day', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'day', g.day, 'n', g.n, 'mobile', g.mobile) order by g.day), '[]'::jsonb)
      from (
        select to_char(at at time zone 'Asia/Seoul', 'MM-DD') as day,
               count(*) as n,
               count(*) filter (where device = 'mobile') as mobile
        from public.link_click
        where at >= greatest(since, now() - interval '30 days')
        group by 1
      ) g
    ),
    'by_referer', (
      select coalesce(jsonb_agg(jsonb_build_object('host', g.host, 'n', g.n)
               order by g.n desc), '[]'::jsonb)
      from (
        select referer_host as host, count(*) as n
        from public.link_click
        where referer_host is not null and at >= since
        group by 1 order by count(*) desc limit 20
      ) g
    )
  ) into out;
  return out;
end $$;
revoke all on function public.admin_link_stats(int) from public, anon;
grant execute on function public.admin_link_stats(int) to authenticated;
-- 인자 없는 옛 판은 치운다 (둘이 남으면 어느 쪽이 불릴지 헷갈린다)
drop function if exists public.admin_link_stats();
