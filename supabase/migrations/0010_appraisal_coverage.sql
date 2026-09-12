-- 0010 — 원장에 무엇이 부족한가 (2026-09-12 지시 "부족한 용도지역·지목",
--        "Admin 탭에 붙여 주세요")
--
-- 문서(docs/appraisal-coverage.md)로 한 번 센 것은 다음 적재에 곧 낡는다.
-- 관리자 화면이 직접 세도록 함수를 둔다. 0008 과 같은 틀이다 — 원장 두 표는
-- 여전히 아무도 못 읽고, **집계만** 관리자에게 나간다.
--
-- 그리고 칸 열쇠를 **한 곳에** 둔다. 0008 이 제 규칙을 따로 적고 있어서
-- src/redt/valuation.py 의 zone_group·use_group 과 조금 어긋났다
-- ('전주'=전용주거 누락, 지목은 부분일치라 '전'이 엉뚱한 것에 걸릴 여지).
-- 이제 두 함수가 같은 열쇠를 부른다.

-- ── 용도지역군 — valuation.py ZONE_GROUPS 와 같은 순서 ──────────────
create or replace function public.appr_zone_group(land_use text)
returns text language sql immutable as $$
  select case
    when land_use is null then null
    when land_use like '%관리%' then '관리'
    when land_use like '%녹지%' then '녹지'
    when land_use like '%농림%' or land_use like '%자연환경%' then '농림'
    when land_use like '%주거%' or land_use like '%일주%' or land_use like '%전주%' then '주거'
    when land_use like '%상업%' then '상업'
    when land_use like '%공업%' then '공업'
  end;
$$;

-- ── 지목군 — 지목 **정확히 일치**를 먼저, 없으면 이용상황 부분일치 ────
-- valuation.py use_group() 과 같은 순서다. '전' 은 '전용주거' 에도 들어
-- 있어서 지목을 먼저 보고, 부분일치는 이용상황에만 쓴다.
create or replace function public.appr_use_group(jimok text, use_situation text)
returns text language sql immutable as $$
  select case
    when btrim(coalesce(jimok, '')) = '임야' then '임야'
    when btrim(coalesce(jimok, '')) in ('전', '답', '과수원', '목장용지') then '전·답'
    when btrim(coalesce(jimok, '')) = '대' then '대'
    when btrim(coalesce(jimok, '')) in ('공장용지', '도로', '잡종지', '창고용지', '주차장')
      then '공장·도로'
    when use_situation like '%임야%' or use_situation like '%자연림%' then '임야'
    when use_situation similar to '%(전|답|과수|묵|농|목장)%' then '전·답'
    when use_situation similar to '%(대|주거|주택|나지|상업)%' then '대'
    when use_situation similar to '%(공장|공업|도로|잡종|창고|주차)%' then '공장·도로'
    when jimok like '%임야%' then '임야'
    when jimok similar to '%(과수|묵|목장)%' then '전·답'
    when jimok similar to '%(공장|도로|잡종|창고|주차)%' then '공장·도로'
  end;
$$;

-- ── 부족한 칸 집계 ──────────────────────────────────────────────────
create or replace function public.appraisal_coverage()
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  out jsonb;
  min_cell int := 3;   -- src/redt/valuation.py MIN_CELL
begin
  if not public.is_admin() then
    raise exception '관리자만 볼 수 있습니다';
  end if;

  with c as (
    select sido, sigungu, f_other, land_use, jimok, std_jimok, std_land_use,
           public.appr_zone_group(land_use) as zg,
           -- 그 밖의 요인은 **비교표준지** 기준 배율이다. 표준지 지목이
           -- 있으면 그것으로, 없으면 대상 필지 것으로 물러난다 (0007 주석).
           public.appr_use_group(coalesce(nullif(btrim(std_jimok), ''), jimok),
                                 coalesce(std_use_situation, use_situation)) as ug
    from appraisal_case
  ),
  o as (select * from c where f_other is not null),
  grid as (
    select z.zg, u.ug from
      (select unnest(array['관리','녹지','농림','주거','상업','공업']) zg) z
      cross join (select unnest(array['임야','전·답','대','공장·도로']) ug) u
  ),
  n_cell as (select zg, ug, count(*) n from o where zg is not null and ug is not null group by 1,2),
  sido_ok as (select zg, ug, count(*) c from (
      select zg, ug, sido from o where zg is not null and ug is not null
      group by 1,2,3 having count(*) >= min_cell) x group by 1,2),
  sgg_ok as (select zg, ug, count(*) c from (
      select zg, ug, sigungu from o where zg is not null and ug is not null
      group by 1,2,3 having count(*) >= min_cell) x group by 1,2)
  select jsonb_build_object(
    'generated_at', now(),
    'min_cell', min_cell,
    'total', (select count(*) from c),
    'with_other', (select count(*) from o),
    -- 24칸 전부. 없는 칸도 n=0 으로 나온다 — 없는 것이 안 보이면 못 채운다.
    'grid', (select jsonb_agg(jsonb_build_object(
        'zg', g.zg, 'ug', g.ug, 'n', coalesce(k.n, 0),
        'ready', coalesce(k.n, 0) >= min_cell,
        'sido_ready', coalesce(s.c, 0), 'sgg_ready', coalesce(q.c, 0))
        order by g.zg, g.ug)
      from grid g
      left join n_cell k on k.zg = g.zg and k.ug = g.ug
      left join sido_ok s on s.zg = g.zg and s.ug = g.ug
      left join sgg_ok q on q.zg = g.zg and q.ug = g.ug),
    'cells_ready', (select count(*) from n_cell where n >= min_cell),
    -- 원문 이름 분포. 어떤 용도지역·지목을 더 구할지는 이쪽을 봐야 안다.
    'land_use', (select coalesce(jsonb_agg(jsonb_build_object('v', v, 'n', n, 'f', f)
                                           order by n desc), '[]'::jsonb) from (
        select coalesce(nullif(btrim(land_use), ''), '(빈칸)') v, count(*) n, count(f_other) f
        from c group by 1) t),
    'jimok', (select coalesce(jsonb_agg(jsonb_build_object('v', v, 'n', n, 'f', f)
                                        order by n desc), '[]'::jsonb) from (
        select coalesce(nullif(btrim(jimok), ''), '(빈칸)') v, count(*) n, count(f_other) f
        from c group by 1) t),
    'std_jimok', (select coalesce(jsonb_agg(jsonb_build_object('v', v, 'n', n)
                                            order by n desc), '[]'::jsonb) from (
        select coalesce(nullif(btrim(std_jimok), ''), '(빈칸)') v, count(*) n
        from c group by 1) t),
    -- 숫자보다 급한 곳: 표준지 칸이 빈 행. 그 행은 칸 열쇠가 대상 필지
    -- 지목으로 물러나 있어서, 대상이 임야·표준지가 전인 평가서가 임야
    -- 칸에 섞여 들어간다. 1차 판독분을 다시 읽어야 하는 근거다.
    'std_blank', (select jsonb_build_object(
        'jimok', count(*) filter (where coalesce(btrim(std_jimok), '') = ''),
        'jimok_with_other', count(*) filter (
            where coalesce(btrim(std_jimok), '') = '' and f_other is not null),
        'land_use', count(*) filter (where coalesce(btrim(std_land_use), '') = ''),
        'no_other', count(*) filter (where f_other is null)) from c),
    'by_sido', (select coalesce(jsonb_agg(jsonb_build_object(
        'sido', v, 'n', n, 'sgg', sgg) order by n desc), '[]'::jsonb) from (
        select coalesce(nullif(btrim(sido), ''), '(빈칸)') v, count(*) n,
               count(distinct sigungu) sgg
        from c group by 1) t)
  ) into out;
  return out;
end;
$$;

revoke all on function public.appraisal_coverage() from public, anon;
grant execute on function public.appraisal_coverage() to authenticated, service_role;

-- 0008 의 함수도 같은 열쇠를 쓰게 바꾼다 (규칙이 두 곳에 있으면 어긋난다).
create or replace function public.appraisal_admin_stats()
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  out jsonb;
begin
  if not public.is_admin() then
    raise exception '관리자만 볼 수 있습니다';
  end if;

  with c as (
    select *,
      public.appr_zone_group(land_use) as zg,
      public.appr_use_group(coalesce(nullif(btrim(std_jimok), ''), jimok),
                            coalesce(std_use_situation, use_situation)) as ug,
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
