"""거짓 'parcel' 라벨을 내리면 무엇이 얼마나 달라지나 — 영향 범위.

요구사항(2026-09-19): "2번 부터해봅시다." (영향 범위를 센다)

## 앞에서 확정된 것

parcel_trust_probe 가 전국에서 이렇게 찍었다.

    1절 본번이 마스킹 범위 안    2.3%   (2,748,902건 중 63,873건)
    2절 면적이 5% 안            2.0%   ← 무작위 짝 2.2% 보다 낮다
    3절 법정동당 거래 508건이 서로 다른 좌표 9개로
    4절 한 필지에 최대 6,226건

지오코더가 가려진 지번(`1**`)을 못 찾고 그 리의 앞 번호로 뭉갰다.
붙은 본번이 1→734,941 · 2→404,894 · 3→339,879 … 내림 계단이다.

## 이 탐침이 세는 것

라벨을 내리면 **무엇이 줄고, 화면 숫자가 얼마나 달라지는가.**

    1절  믿을 수 있는 링크가 몇 개인가
    2절  이 링크를 읽는 곳마다 표본이 얼마나 줄어드나
    3절  화면에 직접 나가는 숫자가 달라지나 (도로접면 분포)
    4절  위치 오차가 실제로 얼마인가
    5절  못 재는 것은 무엇인가

## 믿을 수 있는 링크의 정의

    본번이 마스킹 범위 안  AND  산여부 일치  AND  |거래면적 − 필지면적| ≤ 5%

부번은 걸지 않는다. 마스킹이 부번을 통째로 지워서 (`1**` 에는 부번
자리가 없다) 맞는지 틀린지 알 방법이 없다. 모르는 것을 조건으로 걸면
맞는 것까지 버린다.

## 읽는 곳 (grep 으로 확인)

    cli.py:405       필지 특성 표본 — 감정평가 배수 산출
    cli.py:1497      반경 3~5km 판정 (geocode_level 만)
    cli.py:2305      도로접면별 가격
    webexport.py:135 화면 거래 표본
    webexport.py:1786 **도로접면 분포 — 화면에 직접 나간다**
    valuation.py:923 현재 가치
    parcelscore.py:218·282  필지 진단 레이더
    urban.py:125     도시화 지표
    panel.py:408     **근거리 밴드의 신뢰 조건** ← 가장 아픈 자리

호출 0. DB 만 읽는다.

  python scripts/blast_radius_probe.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import duckdb                                               # noqa: E402

from redt.config import DB_PATH                             # noqa: E402

AREA_TOL = 0.05


def head(n: str) -> None:
    print()
    print(n)
    print("-" * (len(n) + 12))


def main() -> int:
    if not DB_PATH.exists():
        print(f"  {DB_PATH} 가 없습니다 (러너에서 캐시 복원 뒤 도십시오)")
        return 1
    con = duckdb.connect(str(DB_PATH), read_only=True)

    print("=" * 68)
    print(" 거짓 'parcel' 라벨을 내리면 무엇이 얼마나 달라지나")
    print("=" * 68)

    # 믿을 수 있는 링크. 두 검사를 다 통과한 것만.
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW trust AS
        WITH j AS (
          SELECT t.trade_id, tp.pnu, t.area_m2 AS deal_area, p.area_m2 AS par_area,
                 substr(tp.pnu, 11, 1) AS mount_pnu,
                 CAST(substr(tp.pnu, 12, 4) AS INT) AS bon_pnu,
                 split_part(replace(trim(t.jibun), '산', ''), '-', 1) AS bon_tok,
                 CASE WHEN trim(t.jibun) LIKE '산%' THEN '2' ELSE '1' END AS mount_jb
          FROM trade t
          JOIN trade_parcel tp USING (trade_id)
          LEFT JOIN parcel p ON p.pnu = tp.pnu
          WHERE t.jibun IS NOT NULL AND length(tp.pnu) = 19)
        SELECT trade_id, pnu FROM j
        WHERE regexp_matches(bon_tok, '^[0-9*]{{1,4}}$')
          AND mount_pnu = mount_jb
          AND bon_pnu BETWEEN TRY_CAST(replace(bon_tok, '*', '0') AS INT)
                          AND TRY_CAST(replace(bon_tok, '*', '9') AS INT)
          AND deal_area > 0 AND par_area > 0
          AND abs(deal_area - par_area) <= par_area * {AREA_TOL}
    """)

    # ── 1. 믿을 수 있는 링크 ────────────────────────────────────────
    head("1. 믿을 수 있는 링크가 몇 개인가")
    print(f"  두 검사를 다 통과한 것 — 본번 범위 안 · 산여부 일치 · 면적 {AREA_TOL:.0%} 안")
    n_link, n_trust = con.execute("""
        SELECT (SELECT count(*) FROM trade_parcel),
               (SELECT count(*) FROM trust)""").fetchone()
    print(f"\n  지금 링크   {n_link:>12,}건")
    print(f"  믿을 수 있음 {n_trust:>12,}건   ({n_trust / max(n_link, 1):.2%})")
    print(f"  끊어야 함   {n_link - n_trust:>12,}건")

    print("\n  왜 떨어졌나 (하나씩 걸었을 때 남는 수)")
    for label, cond in [
            ("아무 조건 없음", "1=1"),
            ("산여부만 일치", "mount_pnu = mount_jb"),
            ("본번 범위만 안", "bon_pnu BETWEEN lo AND hi"),
            ("면적만 5% 안", "abs(deal_area - par_area) <= par_area * 0.05"),
            ("셋 다", "mount_pnu = mount_jb AND bon_pnu BETWEEN lo AND hi "
                      "AND abs(deal_area - par_area) <= par_area * 0.05")]:
        n = con.execute(f"""
            WITH j AS (
              SELECT substr(tp.pnu, 11, 1) AS mount_pnu,
                     CAST(substr(tp.pnu, 12, 4) AS INT) AS bon_pnu,
                     t.area_m2 AS deal_area, p.area_m2 AS par_area,
                     split_part(replace(trim(t.jibun), '산', ''), '-', 1) AS bon_tok,
                     CASE WHEN trim(t.jibun) LIKE '산%' THEN '2' ELSE '1' END AS mount_jb
              FROM trade t JOIN trade_parcel tp USING (trade_id)
              LEFT JOIN parcel p ON p.pnu = tp.pnu
              WHERE t.jibun IS NOT NULL AND length(tp.pnu) = 19
                AND t.area_m2 > 0 AND p.area_m2 > 0),
            k AS (SELECT *, TRY_CAST(replace(bon_tok,'*','0') AS INT) AS lo,
                            TRY_CAST(replace(bon_tok,'*','9') AS INT) AS hi
                  FROM j WHERE regexp_matches(bon_tok, '^[0-9*]{{1,4}}$'))
            SELECT count(*) FROM k WHERE {cond}""").fetchone()[0]
        print(f"    {label:<18}{n:>12,}")

    # ── 2. 읽는 곳마다 표본이 얼마나 줄어드나 ───────────────────────
    head("2. 이 링크를 읽는 곳마다 표본이 얼마나 줄어드나")
    cases = [
        ("cli.py:405  필지 특성 표본 (감정평가 배수)",
         "t.kind='land' AND NOT coalesce(t.is_cancelled,FALSE) "
         "AND NOT coalesce(t.is_share_deal,FALSE) AND t.geocode_level='parcel' "
         "AND pc.official_price > 0 AND t.price_per_m2 > 0"),
        ("cli.py:2305 도로접면별 가격",
         "t.kind='land' AND NOT coalesce(t.is_cancelled,FALSE) "
         "AND NOT coalesce(t.is_share_deal,FALSE) AND pc.road_side IS NOT NULL "
         "AND t.price_per_m2 > 0 AND t.area_m2 > 0"),
        ("valuation.py:923 현재 가치",
         "t.kind='land' AND NOT coalesce(t.is_cancelled,FALSE) "
         "AND t.price_per_m2 > 0"),
    ]
    print(f"  {'읽는 곳':<40}{'지금':>12}{'믿을 만':>12}{'남는 비율':>11}")
    for label, cond in cases:
        now, keep = con.execute(f"""
            SELECT count(*),
                   count(*) FILTER (WHERE tr.trade_id IS NOT NULL)
            FROM trade t
            JOIN trade_parcel tp USING (trade_id)
            JOIN parcel pc ON pc.pnu = tp.pnu
            LEFT JOIN trust tr ON tr.trade_id = t.trade_id
            WHERE {cond}""").fetchone()
        print(f"  {label:<40}{now:>12,}{keep:>12,}{keep / max(now, 1):>10.2%}")

    # ── 3. 화면에 직접 나가는 숫자 ──────────────────────────────────
    head("3. 화면에 직접 나가는 숫자가 달라지나 — 도로접면 분포")
    print("  webexport.py:1786 이 이 분포를 화면에 올립니다.")
    print("  '차가 들어가는 땅' 비율이 여기서 나옵니다.")
    rows = con.execute("""
        SELECT coalesce(pc.road_side, '(모름)') AS rs,
               count(*) AS now_n,
               count(*) FILTER (WHERE tr.trade_id IS NOT NULL) AS keep_n
        FROM trade t
        JOIN trade_parcel tp USING (trade_id)
        JOIN parcel pc ON pc.pnu = tp.pnu
        LEFT JOIN trust tr ON tr.trade_id = t.trade_id
        WHERE t.kind = 'land'
        GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    tn = sum(r[1] for r in rows) or 1
    tk = sum(r[2] for r in rows) or 1
    print(f"\n  {'도로접면':<16}{'지금':>11}{'비중':>8}"
          f"{'믿을 만':>11}{'비중':>8}{'차이':>9}")
    for rs, a, b in rows[:10]:
        pa, pb = a / tn, b / tk
        print(f"  {rs:<16}{a:>11,}{pa:>7.1%}{b:>11,}{pb:>7.1%}"
              f"{(pb - pa) * 100:>+7.1f}%p")
    print(f"\n  합계 {tn:,}건 → {tk:,}건")

    # ── 4. 위치 오차 ────────────────────────────────────────────────
    head("4. 위치 오차가 실제로 얼마인가")
    print("  같은 법정동 안 'parcel' 좌표들이 얼마나 퍼져 있는지 잽니다.")
    print("  그 퍼짐이 곧 '어느 점으로 뭉쳤는가' 의 규모입니다.")
    r = con.execute("""
        WITH g AS (
          SELECT sigungu_cd, umd,
                 count(*) AS n, avg(lat) AS clat, avg(lon) AS clon,
                 max(lat) - min(lat) AS dlat, max(lon) - min(lon) AS dlon
          FROM trade
          WHERE geocode_level = 'parcel' AND lat IS NOT NULL
          GROUP BY 1, 2 HAVING count(*) >= 50)
        SELECT count(*), median(dlat), median(dlon), median(clat) FROM g""").fetchone()
    if r and r[0]:
        n_g, dlat, dlon, clat = r
        km_lat = (dlat or 0) * 110.54
        km_lon = (dlon or 0) * 111.32 * math.cos(math.radians(clat or 37))
        print(f"\n  법정동 {n_g:,}개 (거래 50건 이상)")
        print(f"    좌표가 퍼진 폭 중앙값  세로 {km_lat:.2f}km · 가로 {km_lon:.2f}km")
        print("    → 이 안 어딘가에 흩어져 있고, 어느 점이 맞는지 모릅니다.")
        print("       근거리 밴드(3~5km)를 가르기에는 큰 폭입니다.")

    # ── 5. 못 재는 것 ───────────────────────────────────────────────
    head("5. 못 재는 것")
    n_band = con.execute("SELECT count(*) FROM trade_tollgate_link").fetchone()[0]
    print(f"  trade_tollgate_link {n_band:,}건")
    if not n_band:
        print("  **밴드 영향은 못 잽니다.** 조인 결과가 비어 있습니다 —")
        print("  지금 캐시는 stage=web 으로 복원한 것이라 조인을 안 돌렸습니다.")
        print("  panel.py:408 이 근거리 밴드에서 geocode_level='parcel' 만")
        print("  통과시키는데, 그 라벨이 거짓이라 **필터가 통과시키고 있습니다.**")
        print("  얼마나 새는지는 analyze 를 한 번 돌려야 나옵니다.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
