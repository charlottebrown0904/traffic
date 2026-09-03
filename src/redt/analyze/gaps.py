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

    # 밴드별로 몇 개나 살아남았는지 — 위약 밴드가 얇은 이유가 여기서 보인다.
    #
    # 두 줄로 나눠 세는 데 이유가 있다. 연결 테이블은 한 거래를 반경 안의 모든
    # 영업소에 이어 두지만, 패널은 **가장 가까운 영업소 하나**만 쓴다
    # (transform/panel.py 의 nearest_only). 그래서 '전체' 열이 커도 패널에
    # 들어가는 것은 '최근접' 열뿐이다. 이 차이를 안 보면 위약 밴드가 얇은 이유를
    # 좌표나 명단 탓으로 오해하게 된다.
    out["밴드별_영업소"] = con.execute("""
        SELECT band,
               count(DISTINCT tollgate_id)                                  AS 영업소_전체,
               count(*)                                                     AS 거래연결_전체,
               count(DISTINCT CASE WHEN is_nearest THEN tollgate_id END)    AS 영업소_최근접,
               count(*) FILTER (WHERE is_nearest)                           AS 거래연결_최근접
        FROM trade_tollgate_link
        GROUP BY band ORDER BY band
    """).fetchdf()

    # 4. 명부에는 가동중인데 TCS 교통량이 **한 해도** 없다.
    #
    # 이것을 '누락' 으로 부르면 고칠 수 없는 것을 고치려 든다. 운영기관별로
    # 세어 보면 기관 단위로 딱 갈린다 — 도로공사가 요금을 걷는 노선은
    # 100% 있고, 민자 운영사가 직접 걷는 노선은 100% 없다. 도로공사가
    # 내는 자료이므로 당연하다. 채울 수 있는 결측이 아니라 **다른 기관이
    # 가진 자료**다. 마도(805)가 여기 해당한다.
    out["교통량_미공개"] = con.execute("""
        SELECT coalesce(m.operator_cd, '(미상)') AS 운영기관,
               count(*)                          AS 영업소,
               count(m.lat)                      AS 좌표있음,
               string_agg(m.name, ', ' ORDER BY m.tollgate_id) AS 예시
        FROM tollgate m
        WHERE m.tollgate_id NOT IN (SELECT DISTINCT tollgate_id FROM traffic)
          AND m.name IS NOT NULL AND trim(m.name) <> ''
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchdf()

    out["좌표_출처"] = con.execute("""
        SELECT coalesce(src, '(미상)') AS 출처, count(*) AS 영업소
        FROM tollgate WHERE lat IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchdf()

    return out


def _attach_names(df: pd.DataFrame) -> pd.DataFrame:
    """교통량 CSV 의 영업소명을 붙인다. 코드만 보고는 어디인지 알 수 없다."""
    if df.empty or "tollgate_id" not in df:
        return df
    try:
        from ..collect.tollgate_fill import names_from_traffic
        names = names_from_traffic()
    except Exception:                              # noqa: BLE001 — 이름은 부가정보
        return df
    if not names:
        return df
    out = df.copy()
    out.insert(1, "name", out["tollgate_id"].map(names).fillna(""))
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
        if title == "교통량만있고_마스터없음":
            df = _attach_names(df)
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
    print("  전체 = 반경 안에 든 모든 연결 · 최근접 = 가장 가까운 영업소로만 센 것.")
    print("  패널은 최근접만 씁니다. 두 열이 크게 벌어진 밴드는 좌표나 명단이 아니라")
    print("  '그 IC 가 가장 가까운 땅' 이 드물다는 뜻입니다.")

    bands = tables["밴드별_영업소"]
    if {"거래연결_전체", "거래연결_최근접"} <= set(bands.columns) and len(bands):
        worst = bands.assign(
            _ratio=bands["거래연결_최근접"] / bands["거래연결_전체"].replace(0, pd.NA)
        ).sort_values("_ratio")
        row = worst.iloc[0]
        if pd.notna(row["_ratio"]) and row["_ratio"] < 0.2:
            print(f"  가장 많이 걸러지는 밴드: {row['band']} "
                  f"— 연결 {int(row['거래연결_전체']):,}건 중 "
                  f"{int(row['거래연결_최근접']):,}건({row['_ratio']:.1%})만 패널에 들어갑니다.")

    nt = tables.get("교통량_미공개")
    if nt is not None and not nt.empty:
        total = int(nt["영업소"].sum())
        print(f"\n--- 통행량 미공개 : {total}개 (운영기관 {len(nt)}곳) ---")
        print("  도로공사 TCS 에 한 해도 통행량이 없는 영업소입니다. 대부분 민자")
        print("  운영사가 요금을 직접 걷는 노선이라 도로공사가 그 자료를 갖고")
        print("  있지 않습니다 — 채울 수 있는 결측이 아닙니다. 지도에는 '통행량")
        print("  미공개' 로 그리고, 교통량이 필요한 분석에서는 뺍니다.")
        view = nt.copy()
        view["예시"] = view["예시"].str.slice(0, 60)
        print(view.head(15).to_string(index=False))
        if len(nt) > 15:
            print(f"  … 외 운영기관 {len(nt) - 15}곳")

    src = tables.get("좌표_출처")
    if src is not None and not src.empty:
        print("\n--- 좌표 출처 ---")
        print(src.to_string(index=False))
