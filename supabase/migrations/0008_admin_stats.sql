-- 0008 — 관리자 화면이 읽을 원장 집계 (2026-09-12 지시 "Admin 탭")
--
-- appraisal_case·appraisal_factor 는 RLS 만 켜고 정책이 없다 — service key
-- 로만 읽는 비공개 원장이다 (0005 에 그렇게 적어 두었다). 그것을 바꾸지
-- 않는다. 대신 **집계만** 돌려주는 함수를 두고, 함수 안에서 관리자인지
-- 다시 본다. 원본 행은 여전히 아무도 못 읽는다.
--
-- 왜 이렇게 하나. 관리자 화면(/admin)의 HTML·JS 는 누구나 받아 볼 수 있다
-- (자물쇠는 화면이 아니라 자료다). 그래서 숫자를 화면 파일에 박으면 그것이
-- 곧 공개다. 숫자는 로그인한 관리자만 부를 수 있는 이 함수에서 온다.
create or replace function public.appraisal_admin_stats()
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

  with c as (
    select *,
      case when land_use like '%관리%' then '관리'
           when land_use like '%녹지%' then '녹지'
           when land_use like '%농림%' or land_use like '%자연환경%' then '농림'
           when land_use like '%주거%' or land_use like '%일주%' then '주거'
           when land_use like '%상업%' then '상업'
           when land_use like '%공업%' then '공업' end as zg,
      case when coalesce(std_jimok, jimok) like '%임야%' then '임야'
           when coalesce(std_jimok, jimok) similar to '%(전|답|과수|묵|목장)%' then '전·답'
           when coalesce(std_jimok, jimok) = '대' then '대'
           when coalesce(std_jimok, jimok) similar to '%(공장|도로|잡종|창고|주차)%' then '공장·도로' end as ug,
      case when std_price is not null and f_time is not null and f_region is not null
                and f_indiv is not null and f_other is not null and unit_calc > 0
           then abs(std_price * f_time * f_region * f_indiv * f_other / unit_calc - 1)
           else null end as chk
    from appraisal_case
  )
  select jsonb_build_object(
    'generated_at', now(),
    'total', (select count(*) from c),
    'by_batch', (select coalesce(jsonb_agg(x order by x->>'batch'), '[]'::jsonb) from (
        select jsonb_build_object('batch', coalesce(batch, 1), 'n', count(*)) x
        from c group by coalesce(batch, 1)) t),
    -- 검산: 다섯 마디의 곱이 평가서의 산출단가와 0.5% 안인가
    'check', (select jsonb_build_object(
        'checkable', count(chk), 'pass', count(*) filter (where chk <= 0.005),
        'worst', round(max(chk)::numeric, 4)) from c),
    'readable', (select coalesce(jsonb_agg(jsonb_build_object('kind', coalesce(readable, '?'), 'n', n)
                                           order by n desc), '[]'::jsonb)
                 from (select readable, count(*) n from c group by readable) t),
    'by_sido', (select coalesce(jsonb_agg(jsonb_build_object(
        'sido', sido, 'n', n, 'n_other', n_other, 'other', other_med, 'ratio', ratio_med)
        order by n desc), '[]'::jsonb) from (
        select coalesce(sido, '?') sido, count(*) n, count(f_other) n_other,
               round(percentile_cont(0.5) within group (order by f_other)::numeric, 2) other_med,
               round(percentile_cont(0.5) within group (order by ratio_official)::numeric, 2) ratio_med
        from c group by coalesce(sido, '?')) t),
    'by_cell', (select coalesce(jsonb_agg(jsonb_build_object(
        'zg', zg, 'ug', ug, 'n', n, 'med', med, 'q1', q1, 'q3', q3)
        order by n desc), '[]'::jsonb) from (
        select zg, ug, count(*) n,
               round(percentile_cont(0.5) within group (order by f_other)::numeric, 2) med,
               round(percentile_cont(0.25) within group (order by f_other)::numeric, 2) q1,
               round(percentile_cont(0.75) within group (order by f_other)::numeric, 2) q3
        from c where zg is not null and ug is not null and f_other is not null
        group by zg, ug) t),
    -- 시군구 칸이 몇 개나 최소 표본(3건)을 넘는가 — 지역을 좁게 볼 수 있는 한계
    'sgg_cells', (select jsonb_build_object(
        'all', count(*), 'ready', count(*) filter (where n >= 3),
        'covered', coalesce(sum(n) filter (where n >= 3), 0)) from (
        select sigungu, zg, ug, count(*) n from c
        where zg is not null and ug is not null and f_other is not null
        group by sigungu, zg, ug) t),
    'sgg_top', (select coalesce(jsonb_agg(jsonb_build_object(
        'sigungu', sigungu, 'zg', zg, 'ug', ug, 'n', n, 'med', med) order by med desc), '[]'::jsonb)
        from (select sigungu, zg, ug, count(*) n,
                     round(percentile_cont(0.5) within group (order by f_other)::numeric, 2) med
              from c where zg is not null and ug is not null and f_other is not null
              group by sigungu, zg, ug having count(*) >= 3) t),
    -- 비어 있는 칸 — 다음에 무엇을 더 모아야 하는지
    'gaps', (select jsonb_build_object(
        'no_other', count(*) filter (where f_other is null),
        'no_official', count(*) filter (where official_price is null),
        'no_std', count(*) filter (where std_price is null),
        'image', count(*) filter (where readable in ('image', 'error'))) from c),
    'factors', (select jsonb_build_object('rows', (select count(*) from appraisal_factor),
        'by_group', (select coalesce(jsonb_agg(jsonb_build_object(
            'g', group_nm, 'n', n, 'med', med, 'lo', lo, 'hi', hi, 'eq1', eq1) order by n desc), '[]'::jsonb)
            from (select coalesce(group_nm, '?') group_nm, count(*) n,
                         round(percentile_cont(0.5) within group (order by ratio)::numeric, 3) med,
                         count(*) filter (where ratio < 1) lo, count(*) filter (where ratio > 1) hi,
                         count(*) filter (where ratio = 1) eq1
                  from appraisal_factor where ratio is not null group by coalesce(group_nm, '?')) t)))
  ) into out;
  return out;
end;
$$;

revoke all on function public.appraisal_admin_stats() from public, anon;
grant execute on function public.appraisal_admin_stats() to authenticated, service_role;
