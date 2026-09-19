"""필지 단위 좌표 2,821,032건을 믿어도 되는가 — 검증.

요구사항(2026-09-19): "(가)부터하고 판단합시다."

## 왜 의심하는가

탐침(jibun_match_probe)이 이것을 찍었다.

    좌표단위          가려짐        온전    가려짐 비율
    parcel        2,820,921        111     100.0%
    umd           8,751,428      7,274      99.9%

**필지 단위로 붙었다는 것도 지번이 100% 가려져 있다.** 그런데 코드는
가려진 지번을 그대로 지오코더에 넘긴다 (cli.py cmd_geocode).

    rows = [(r.sigungu, r.umd, r.jibun) ...]      # jibun = "1**"
    parcel_coords = gc.geocode_parcel(rows, ...)   # "안성시 미양면 계륵리 1**"
    ...
    "geocode_level": "parcel"                      # 무엇이 오든 필지 단위로 기록

pnu_probe.py 가 이미 적어 둔 관찰: **"140 → 140-1 로 뭉갬"**. 지오코더는
못 찾으면 비슷한 것으로 뭉갠다. `1**` 을 어떻게 읽었는지는 모른다.

이것이 사실이면 파급이 크다. trade_parcel 의 필지 특성(도로접면·형상·
지세·공시지가)이 그 좌표 위의 점-다각형으로 붙었으니, 282만 건이 엉뚱한
필지의 특성을 달고 있다는 뜻이다. 지금 화면에 나가는 숫자다.

## 네 갈래로 따로 잰다

하나만 보면 우연일 수 있다. 서로 독립인 것 넷을 나란히 놓는다.

    1절  본번이 마스킹 범위 안에 있나   1** 이면 100~199 여야 한다
    2절  면적이 맞나                  거래 면적 vs 붙은 필지 면적
    3절  좌표가 뭉쳤나                한 법정동의 거래가 몇 점으로 모였나
    4절  한 필지에 몇 건이 몰렸나       뭉갰으면 특정 필지에 쌓인다

**2절이 가장 강하다.** 면적은 지오코딩과 아무 상관이 없는 칸이라,
링크가 맞으면 저절로 맞고 틀리면 저절로 어긋난다.

호출 0. DB 만 읽는다.

  python scripts/parcel_trust_probe.py
  python scripts/parcel_trust_probe.py 41550     # 한 시군구만
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import duckdb                                               # noqa: E402

from redt.config import DB_PATH                             # noqa: E402

# 이만큼은 맞아야 '믿을 만하다' 고 말할 수 있다. 본번은 마스킹이 정하는
# 범위라 맞추기 쉬운 편이고, 면적은 어긋나기 쉬우므로 기준을 낮게 둔다.
OK_BON = 0.80
OK_AREA = 0.50


def head(n: str) -> None:
    print()
    print(n)
    print("-" * (len(n) + 12))


def bar(x: float, w: int = 24) -> str:
    return "█" * int(round(w * max(0.0, min(1.0, x))))


def main() -> int:
    sgg = sys.argv[1] if len(sys.argv) > 1 else ""
    where_sgg = f"AND t.sigungu_cd = '{sgg}'" if sgg else ""

    print("=" * 68)
    print(" 필지 단위 좌표를 믿어도 되는가 — 검증"
          + (f" (시군구 {sgg})" if sgg else " (전국)"))
    print("=" * 68)

    if not DB_PATH.exists():
        print(f"  {DB_PATH} 가 없습니다 (러너에서 캐시 복원 뒤 도십시오)")
        return 1
    con = duckdb.connect(str(DB_PATH), read_only=True)

    n_link, n_parcel = con.execute(f"""
        SELECT count(*) FILTER (WHERE tp.trade_id IS NOT NULL),
               count(*) FILTER (WHERE t.geocode_level = 'parcel')
        FROM trade t LEFT JOIN trade_parcel tp USING (trade_id)
        WHERE 1=1 {where_sgg}""").fetchone()
    print(f"\n  필지에 붙은 거래 {n_link:,}건 · 필지 단위 좌표 {n_parcel:,}건")
    if not n_link:
        print("  붙은 거래가 없습니다. 볼 것이 없습니다.")
        return 1

    # 가려진 지번에서 본번 범위를 뽑는다. `1**` → 100~199.
    # 별이 있는 자리를 0 으로 채우면 아래끝, 9 로 채우면 위끝이다.
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW linked AS
        SELECT t.trade_id, t.sigungu_cd, t.umd, t.jibun, t.area_m2,
               t.is_share_deal, tp.pnu,
               substr(tp.pnu, 1, 10)             AS bjd10,
               substr(tp.pnu, 11, 1)             AS mount_pnu,
               CAST(substr(tp.pnu, 12, 4) AS INT) AS bon_pnu,
               CAST(substr(tp.pnu, 16, 4) AS INT) AS bu_pnu,
               -- 지번에서 산 표시를 떼고 본번 토막만 남긴다
               split_part(replace(trim(t.jibun), '산', ''), '-', 1) AS bon_tok,
               CASE WHEN trim(t.jibun) LIKE '산%' THEN '2' ELSE '1' END AS mount_jb
        FROM trade t JOIN trade_parcel tp USING (trade_id)
        WHERE length(tp.pnu) = 19 AND t.jibun IS NOT NULL {where_sgg}
    """)
    con.execute("""
        CREATE OR REPLACE TEMP VIEW chk AS
        SELECT *,
               TRY_CAST(replace(bon_tok, '*', '0') AS INT) AS bon_lo,
               TRY_CAST(replace(bon_tok, '*', '9') AS INT) AS bon_hi
        FROM linked
        WHERE regexp_matches(bon_tok, '^[0-9*]{1,4}$')
    """)

    # ── 1. 본번이 마스킹 범위 안인가 ────────────────────────────────
    head("1. 붙은 필지의 본번이 마스킹 범위 안에 있나")
    print("  `1**` 로 신고된 거래면 붙은 필지의 본번은 100~199 여야 합니다.")
    tot, inside, out_bon, out_mt = con.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE bon_pnu BETWEEN bon_lo AND bon_hi
                                  AND mount_pnu = mount_jb),
               count(*) FILTER (WHERE NOT (bon_pnu BETWEEN bon_lo AND bon_hi)),
               count(*) FILTER (WHERE mount_pnu <> mount_jb)
        FROM chk WHERE bon_lo IS NOT NULL""").fetchone()
    rate_bon = inside / max(tot, 1)
    print(f"\n  볼 수 있는 것 {tot:,}건")
    print(f"    범위 안 · 산여부도 맞음  {inside:>12,}  {rate_bon:>7.1%}  {bar(rate_bon)}")
    print(f"    본번이 범위 밖          {out_bon:>12,}  {out_bon / max(tot, 1):>7.1%}")
    print(f"    산여부가 어긋남         {out_mt:>12,}  {out_mt / max(tot, 1):>7.1%}")

    print("\n  붙은 본번이 어디에 몰려 있나 (범위 밖인 것만)")
    print("  뭉갰다면 작은 번호(1·2·…)에 쌓입니다.")
    for b, n in con.execute("""
            SELECT bon_pnu, count(*) FROM chk
            WHERE bon_lo IS NOT NULL AND NOT (bon_pnu BETWEEN bon_lo AND bon_hi)
            GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").fetchall():
        print(f"    본번 {b:<8}{n:>12,}")

    # ── 2. 면적이 맞나 (가장 강한 검증) ─────────────────────────────
    head("2. 거래 면적과 붙은 필지의 면적이 맞나")
    print("  면적은 지오코딩과 아무 상관이 없는 칸입니다. 링크가 맞으면")
    print("  저절로 맞고, 틀리면 저절로 어긋납니다. 지분거래는 뺍니다.")
    rows = con.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE abs(l.area_m2 - p.area_m2) <= p.area_m2 * 0.01),
               count(*) FILTER (WHERE abs(l.area_m2 - p.area_m2) <= p.area_m2 * 0.05),
               count(*) FILTER (WHERE abs(l.area_m2 - p.area_m2) <= p.area_m2 * 0.20),
               median(abs(l.area_m2 - p.area_m2) / p.area_m2)
        FROM linked l JOIN parcel p USING (pnu)
        WHERE l.area_m2 > 0 AND p.area_m2 > 0
          AND NOT coalesce(l.is_share_deal, FALSE)""").fetchone()
    n_a, w1, w5, w20, med = rows
    if not n_a:
        print("\n  견줄 수 있는 것이 없습니다 (parcel 표에 면적이 없음)")
        rate_area = None
    else:
        rate_area = w5 / n_a
        print(f"\n  견줄 수 있는 것 {n_a:,}건 · 면적 차이 중앙값 {med:.1%}")
        print(f"    1% 안      {w1:>12,}  {w1 / n_a:>7.1%}  {bar(w1 / n_a)}")
        print(f"    5% 안      {w5:>12,}  {w5 / n_a:>7.1%}  {bar(w5 / n_a)}")
        print(f"    20% 안     {w20:>12,}  {w20 / n_a:>7.1%}  {bar(w20 / n_a)}")
        print("\n  **견줄 자리**: 무작위로 이어 붙이면 얼마나 맞을까.")
        print("  같은 법정동의 아무 필지나 짝지었을 때와 견줍니다.")
        # **조인이 폭발하지 않게 양쪽을 먼저 줄인다.** 거래 1,000건 ×
        # 법정동마다 필지 50개 = 5만 쌍이면 비율을 재기에 충분하다.
        rnd = con.execute("""
            WITH ts AS (
              SELECT bjd10, area_m2 AS a FROM linked
              WHERE area_m2 > 0 AND NOT coalesce(is_share_deal, FALSE)
              USING SAMPLE 1000 ROWS),
            ps AS (
              SELECT substr(pnu, 1, 10) AS bjd10, area_m2 AS b,
                     row_number() OVER (PARTITION BY substr(pnu, 1, 10)
                                        ORDER BY random()) AS rk
              FROM parcel WHERE area_m2 > 0)
            SELECT count(*), count(*) FILTER (WHERE abs(a - b) <= b * 0.05)
            FROM ts JOIN ps USING (bjd10) WHERE ps.rk <= 50""").fetchone()
        if rnd and rnd[0]:
            print(f"    무작위 짝 {rnd[0]:,}쌍 중 5% 안 {rnd[1]:,} "
                  f"({rnd[1] / rnd[0]:.1%})  {bar(rnd[1] / rnd[0])}")

    # ── 3. 좌표가 뭉쳤나 ────────────────────────────────────────────
    head("3. 한 법정동의 거래가 몇 점으로 모였나")
    print("  필지마다 다른 점이어야 정상입니다. 지오코더가 뭉갰다면")
    print("  거래는 많은데 서로 다른 좌표는 몇 개 안 됩니다.")
    for lvl in ("parcel", "umd"):
        r = con.execute(f"""
            WITH g AS (
              SELECT sigungu_cd, umd, count(*) AS n,
                     count(DISTINCT round(lat, 6)::VARCHAR || ','
                                    || round(lon, 6)::VARCHAR) AS pts
              FROM trade t
              WHERE geocode_level = '{lvl}' AND lat IS NOT NULL {where_sgg}
              GROUP BY 1, 2 HAVING count(*) >= 50)
            SELECT count(*), median(pts * 1.0 / n), median(n), median(pts) FROM g
        """).fetchone()
        if r and r[0]:
            print(f"\n  {lvl:<8} 법정동 {r[0]:,}개 (거래 50건 이상인 곳)")
            print(f"    거래 수 중앙값 {r[2]:,.0f} · 서로 다른 좌표 중앙값 {r[3]:,.0f}")
            print(f"    좌표/거래 비율 중앙값 {r[1]:.1%}  {bar(r[1])}")

    # ── 4. 한 필지에 몇 건이 몰렸나 ─────────────────────────────────
    head("4. 한 필지에 거래가 몇 건이나 몰렸나")
    r = con.execute("""
        WITH g AS (SELECT pnu, count(*) AS n FROM linked GROUP BY 1)
        SELECT count(*), sum(n), median(n), max(n),
               sum(n) FILTER (WHERE n >= 10)
        FROM g""").fetchone()
    if r and r[0]:
        npar, nall, med_n, mx, heavy = r
        print(f"  필지 {npar:,}개에 거래 {nall:,}건")
        print(f"    한 필지당 중앙값 {med_n:,.0f}건 · 최대 {mx:,}건")
        print(f"    10건 이상 몰린 필지에 든 거래 {heavy or 0:,}건 "
              f"({(heavy or 0) / max(nall, 1):.1%})")
        print("\n  가장 많이 몰린 필지")
        for pnu_, n in con.execute("""
                SELECT pnu, count(*) FROM linked GROUP BY 1
                ORDER BY 2 DESC LIMIT 5""").fetchall():
            print(f"    …{pnu_[-9:]}  본번 {int(pnu_[11:15]):<6}{n:>10,}건")

    # ── 판정 ────────────────────────────────────────────────────────
    head("판정")
    verdicts = []
    print(f"  1절 본번이 범위 안      {rate_bon:>7.1%}   "
          f"(기준 {OK_BON:.0%})  {'통과' if rate_bon >= OK_BON else '❌ 미달'}")
    verdicts.append(rate_bon >= OK_BON)
    if rate_area is not None:
        print(f"  2절 면적이 5% 안       {rate_area:>7.1%}   "
              f"(기준 {OK_AREA:.0%})  {'통과' if rate_area >= OK_AREA else '❌ 미달'}")
        verdicts.append(rate_area >= OK_AREA)
    print()
    if all(verdicts):
        print("  ✅ 필지 단위 좌표를 믿을 만합니다. 가려진 지번으로 물었는데도")
        print("     맞았다면, 지오코더가 마스킹을 그냥 무시하지 않고 뭔가를")
        print("     제대로 하고 있다는 뜻입니다.")
    else:
        print("  ❌ 믿을 수 없습니다. 282만 건의 '필지 단위' 좌표와 그 위에")
        print("     붙은 필지 특성(도로접면·형상·지세·공시지가)을 다시 봐야")
        print("     합니다. 지금 화면에 나가는 숫자입니다.")
        print()
        print("     다음에 할 일:")
        print("       · geocode_level 을 'parcel' 로 적는 조건을 좁힌다")
        print("         — 가려진 지번으로 물은 것은 필지 단위가 아니다")
        print("       · 밴드 분석과 필지 진단 레이더가 이 좌표에 얼마나")
        print("         기대고 있는지 세고, 영향받는 화면을 정한다")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
