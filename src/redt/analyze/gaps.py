"""영업소가 어느 단계에서 새는지 센다.

패널이 얇을 때 원인이 셋인데 로그만으로는 구분되지 않는다.

  1. 교통량은 있는데 마스터에 없다 (명단을 덜 받았다)
  2. 마스터에 있는데 좌표가 없다 (지도에 못 올린다)
  3. 좌표까지 있는데 거래가 안 붙었다 (그 주변에 우리가 받은 거래가 없다)

셋은 손쓰는 방법이 다르다. 1번은 명단을 다시 받고, 2번은 좌표를 채우고,
3번은 그 지역 거래를 더 받거나 지오코딩을 더 해야 한다. 뭉뚱그리면
엉뚱한 곳을 고치게 된다.
"""
from __future__ import annotations

import pandas as pd


def tollgate_gaps(con) -> dict[str, pd.DataFrame]:
    """단계별 누락을 표로 돌려준다."""
    out: dict[str, pd.DataFrame] = {}

    out["단계"] = con.execute("""
        WITH t AS (SELECT DISTINCT tollgate_id FROM traffic),
             m AS (SELECT tollgate_id, lat, lon FROM tollgate),
             l AS (SELECT DISTINCT tollgate_id FROM trade_tollgate_link)
        SELECT
          (SELECT count(*) FROM t)                                    AS 교통량있음,
          (SELECT count(*) FROM m)                                    AS 마스터등재,
          (SELECT count(*) FROM m WHERE lat IS NOT NULL)              AS 좌표있음,
          (SELECT count(*) FROM t JOIN m USING (tollgate_id))         AS 교통량과짝맞음,
          (SELECT count(*) FROM t JOIN m USING (tollgate_id)
             WHERE lat IS NOT NULL)                                   AS 짝맞고좌표있음,
          (SELECT count(*) FROM l)                                    AS 거래붙음
    """).fetchdf()

    # 1. 교통량은 있는데 마스터에 없다
    out["교통량만있고_마스터없음"] = con.execute("""
        SELECT t.tollgate_id,
               count(*) AS 교통량행,
               min(t.year) AS 시작, max(t.year) AS 종료,
               round(sum(t.volume)) AS 총교통량
        FROM traffic t
        LEFT JOIN tollgate m USING (tollgate_id)
        WHERE m.tollgate_id IS NULL
        GROUP BY t.tollgate_id
        ORDER BY 총교통량 DESC NULLS LAST
    """).fetchdf()

    # 2. 마스터에 있는데 좌표가 없다
    out["마스터있고_좌표없음"] = con.execute("""
        SELECT m.tollgate_id, m.name, m.route_no, m.sido, m.sigungu
        FROM tollgate m
        WHERE m.lat IS NULL OR m.lon IS NULL
        ORDER BY m.tollgate_id
    """).fetchdf()

    # 3. 좌표까지 있는데 거래가 한 건도 안 붙었다
    out["좌표있고_거래없음"] = con.execute("""
        SELECT m.tollgate_id, m.name, m.sido, m.sigungu,
               coalesce(v.교통량행, 0) AS 교통량행
        FROM tollgate m
        LEFT JOIN (SELECT tollgate_id, count(*) AS 교통량행
                   FROM traffic GROUP BY tollgate_id) v USING (tollgate_id)
        WHERE m.lat IS NOT NULL
          AND m.tollgate_id NOT IN (SELECT tollgate_id FROM trade_tollgate_link)
        ORDER BY 교통량행 DESC
    """).fetchdf()

    # 밴드별로 몇 개나 살아남았는지 — 위약 밴드가 얇은 이유가 여기서 보인다
    out["밴드별_영업소"] = con.execute("""
        SELECT band,
               count(DISTINCT tollgate_id) AS 영업소,
               count(*)                    AS 거래연결
        FROM trade_tollgate_link
        GROUP BY band ORDER BY band
    """).fetchdf()

    return out


def report(con) -> None:
    tables = tollgate_gaps(con)

    step = tables["단계"].iloc[0]
    print("=== 영업소가 어디서 새는가 ===")
    print(f"  교통량 파일에 있는 영업소      {int(step['교통량있음']):>5,}")
    print(f"  영업소 마스터에 등재           {int(step['마스터등재']):>5,}")
    print(f"  그중 좌표 있음                 {int(step['좌표있음']):>5,}")
    print(f"  교통량과 마스터가 짝맞음       {int(step['교통량과짝맞음']):>5,}")
    print(f"  짝맞고 좌표까지 있음           {int(step['짝맞고좌표있음']):>5,}"
          "   ← 분석에 쓸 수 있는 최대치")
    print(f"  실제로 거래가 붙은 영업소      {int(step['거래붙음']):>5,}")

    for title, hint in (
        ("교통량만있고_마스터없음", "영업소 명단을 덜 받았습니다. tollgates 를 다시 받으세요."),
        ("마스터있고_좌표없음", "좌표가 없어 지도에 못 올립니다."),
        ("좌표있고_거래없음", "그 주변에 우리가 받은 거래가 없습니다. 권역을 넓히거나 지오코딩을 더 하세요."),
    ):
        df = tables[title]
        print(f"\n--- {title.replace('_', ' ')} : {len(df)}개 ---")
        if df.empty:
            print("  없음")
            continue
        print("  " + hint)
        print(df.head(20).to_string(index=False))
        if len(df) > 20:
            print(f"  … 외 {len(df) - 20}개")

    print("\n--- 밴드별 영업소 ---")
    print(tables["밴드별_영업소"].to_string(index=False))
