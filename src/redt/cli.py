"""파이프라인 CLI.

  python -m redt.cli tollgates
  python -m redt.cli traffic --path data/raw/traffic.csv [--inspect]
  python -m redt.cli trades --kind land --from 2015-01 --to 2025-12 [--sigungu 41590]
  python -m redt.cli geocode [--limit 5000]
  python -m redt.cli link
  python -m redt.cli panel
  python -m redt.cli analyze [--volume freight]
  python -m redt.cli status
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from . import db, webexport
from .analyze import correlation, scoring
from .collect import geocode as gc
from .collect import backfill, ex_api, rtms, tollgate, traffic as tr
from . import regions as rg
from .config import PROCESSED, settings
from .transform import panel as pn
from .transform import spatial


def _months(start: str, end: str) -> list[str]:
    rng = pd.period_range(start=start, end=end, freq="M")
    return [p.strftime("%Y%m") for p in rng]


def cmd_tollgates(args):
    df = tollgate.load_from_csv(args.path) if args.path else tollgate.fetch_tollgates()
    with db.connect() as con:
        n = db.upsert(con, "tollgate", df)
    print(f"영업소 {n}건 저장")


def cmd_traffic(args):
    if args.inspect:
        tr.inspect(args.path)
        return
    mapping = json.loads(args.mapping) if args.mapping else None
    df = tr.load_and_normalize(
        args.path, mapping, args.source, args.unit_type,
        {"daily": True, "annual": False, "auto": None}[args.value],
    )
    if args.unit_type == "point":
        with db.connect() as con:
            tgs = con.execute(
                "SELECT tollgate_id, lat, lon FROM tollgate WHERE lat IS NOT NULL"
            ).fetchdf()
        df = tr.map_points_to_tollgates(df, tgs, max_km=args.max_match_km)

    df = df.drop(columns=[c for c in ("lat", "lon") if c in df.columns])
    with db.connect() as con:
        n = db.upsert(con, "traffic", df)
    span = f"{df['year'].min()}~{df['year'].max()}" if len(df) else "-"
    print(f"교통량 {n:,}행 저장  source={df['source'].iat[0] if n else '-'}  "
          f"영업소 {df['tollgate_id'].nunique()}개  기간 {span}")
    if n:
        years = sorted(df["year"].unique())
        if len(years) < 3:
            print(f"\n⚠️ 연도가 {len(years)}개뿐입니다 ({years}).")
            print("   Δ교통량 ↔ Δ가격 분석(H2)에는 최소 3개 연도가 필요합니다.")
            print("   docs/traffic-history.md 의 과거자료 확보 경로를 확인하세요.")


def cmd_probe_ex(args):
    ex_api.probe()


def cmd_probe_history(args):
    ex_api.probe_history(args.endpoint, args.date_param)


def cmd_backfill(args):
    from datetime import date

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if not (args.endpoint and args.date_param):
        sys.exit("--endpoint 와 --date-param 이 필요합니다. "
                 "`probe-history` 로 먼저 확인하세요.")
    n = backfill.run(args.endpoint, args.date_param, start, end, args.refresh)
    print(f"\n일별 교통량 {n:,}행 저장. 이어서 `rollup` 을 실행하세요.")


def cmd_rollup(args):
    with db.connect() as con:
        annual = backfill.rollup(con)
        if annual.empty:
            sys.exit("traffic_daily 가 비어 있습니다. 먼저 `backfill` 을 실행하세요.")
        n = db.upsert(con, "traffic", annual)
    print(f"\n연 집계 {n:,}행 → traffic (source=tcs)")
    print(f"기간 {annual['year'].min()}~{annual['year'].max()} / "
          f"영업소 {annual['tollgate_id'].nunique()}개")


def cmd_coverage(args):
    """교통량 시계열이 실제로 얼마나 확보됐는지 — 분석 가능 여부를 판정한다."""
    with db.connect() as con:
        by_source = con.execute("""
            SELECT source, unit_type,
                   count(DISTINCT tollgate_id) AS 영업소,
                   min(year) AS 시작, max(year) AS 종료,
                   count(DISTINCT year) AS 연수,
                   count(DISTINCT vehicle_type) AS 차종수
            FROM traffic GROUP BY source, unit_type ORDER BY 연수 DESC
        """).fetchdf()
        usable = con.execute("""
            SELECT count(*) FROM (
                SELECT tollgate_id FROM traffic
                GROUP BY tollgate_id HAVING count(DISTINCT year) >= 3
            )
        """).fetchone()[0]

    if by_source.empty:
        print("적재된 교통량이 없습니다.")
        return
    print(by_source.to_string(index=False))
    print(f"\n3개 연도 이상 확보된 영업소: {usable}개")
    if usable == 0:
        print("\n❌ H2(Δ교통량 ↔ Δ가격) 분석 불가 — 연도가 부족합니다.")
        print("   과거자료 확보 경로: docs/traffic-history.md")
        print("   대안: H5(지구지정 이벤트 스터디)는 교통량 시계열 없이도 가능합니다.")
    elif usable < 20:
        print(f"\n⚠️ 표본이 {usable}개 영업소뿐이라 밴드별 추정이 불안정할 수 있습니다.")
    else:
        print("\n✅ H2 분석 가능")


def _target_sigungu(args, con) -> dict[str, str]:
    """수집 대상 시군구 결정: --sigungu > --region > pilot_regions.yaml 의 active."""
    if args.sigungu:
        return {code.strip(): "" for code in args.sigungu.split(",") if code.strip()}
    if args.region == "all":
        codes = [r[0] for r in con.execute(
            "SELECT DISTINCT sigungu_cd FROM tollgate WHERE sigungu_cd IS NOT NULL"
        ).fetchall()]
        if not codes:
            sys.exit("tollgate.sigungu_cd 가 비어 있어 전국 수집 대상을 만들 수 없습니다. "
                     "--region 또는 --sigungu 를 쓰세요.")
        return {c: "" for c in codes}
    names = args.region.split(",") if args.region else None
    return rg.sigungu_codes(names)


def cmd_regions(args):
    """권역 목록 확인. --verify 는 각 시군구 코드로 1개월 시험 조회를 한다."""
    for name, meta in rg.all_regions().items():
        mark = "★" if name in rg.active_regions() else " "
        print(f"{mark} {name}  —  {meta['name']}  ({len(meta['sigungu'])}개 시군구)")
        for code, label in meta["sigungu"].items():
            print(f"     {code}  {label}")
    print(f"\nactive: {rg.active_regions()}")

    if not args.verify:
        return
    print("\n=== 코드 검증 (land, 시험 조회) ===")
    print("주의: RTMS 는 잘못된 코드에 오류 대신 0건을 반환합니다. "
          "0건이면 코드나 기간을 의심하세요.")
    for name, meta in rg.all_regions().items():
        for code, label in meta["sigungu"].items():
            try:
                _, total = rtms.fetch_page("land", code, args.probe_ymd, page=1, rows=1)
                flag = "OK " if total > 0 else "0건"
                print(f"  {flag} {code} {label:14s} totalCount={total}")
            except Exception as exc:
                print(f"  ERR {code} {label:14s} {exc}")
            rtms.polite_sleep()


def cmd_trades(args):
    with db.connect() as con:
        targets = _target_sigungu(args, con)
        months = _months(args.start, args.end)
        kinds = args.kind.split(",") if args.kind else settings()["trade_kinds"]

        planned = len(kinds) * len(targets) * len(months)
        print(f"수집 계획: {len(kinds)}종 × {len(targets)}개 시군구 × {len(months)}개월 "
              f"= {planned:,} 요청")

        total_rows = 0
        for kind in kinds:
            done = set() if args.refresh else db.done_cells(con, kind)
            todo = [(c, ym) for c in targets for ym in months if (c, ym) not in done]
            print(f"\n[{kind}] 남은 셀 {len(todo):,} (이미 완료 {len(done):,})")

            for i, (code, ym) in enumerate(todo, 1):
                try:
                    df = rtms.fetch_month(kind, code, ym)
                except Exception as exc:
                    db.log_cell(con, kind, code, ym, 0, "error", str(exc))
                    print(f"  실패 {code}/{ym}: {exc}")
                    continue
                n = db.upsert(con, "trade", df)
                db.log_cell(con, kind, code, ym, n, "ok" if n else "empty")
                total_rows += n
                if i % 50 == 0 or i == len(todo):
                    print(f"  {i:,}/{len(todo):,}  누적 {total_rows:,}건")
                rtms.polite_sleep()

    print(f"\n실거래 {total_rows:,}건 신규 저장")


def cmd_geocode(args):
    with db.connect() as con:
        todo = con.execute(
            "SELECT DISTINCT sigungu, umd, jibun FROM trade WHERE lat IS NULL"
        ).fetchdf()
        if todo.empty:
            print("지오코딩할 거래가 없습니다.")
            return

        rows = [(r.sigungu, r.umd, r.jibun) for r in todo.itertuples()]
        coords = gc.geocode_many(rows, limit=args.limit)

        resolved = pd.DataFrame(
            [{"sigungu": s, "umd": u, "jibun": j,
              "lat": v[0], "lon": v[1], "geocode_level": v[2]}
             for (s, u, j), v in coords.items() if v[0] is not None]
        )
        if resolved.empty:
            print("좌표를 얻은 건이 없습니다.")
            return

        con.register("_geo", resolved)
        con.execute("""
            UPDATE trade SET lat = g.lat, lon = g.lon, geocode_level = g.geocode_level
            FROM _geo g
            WHERE trade.lat IS NULL
              AND trade.umd IS NOT DISTINCT FROM g.umd
              AND trade.jibun IS NOT DISTINCT FROM g.jibun
              AND trade.sigungu IS NOT DISTINCT FROM g.sigungu
        """)
        con.unregister("_geo")

        breakdown = con.execute("""
            SELECT coalesce(geocode_level, '미해결') AS level, count(*) AS n
            FROM trade GROUP BY 1 ORDER BY n DESC
        """).fetchdf()
    print("\n거래 기준 좌표 정밀도")
    print(breakdown.to_string(index=False))
    print("\n※ 지번단위(parcel)가 아닌 건은 법정동 중심점이라 오차 ±1~2km 입니다.")
    print("   0-3km 밴드 분석에서는 settings.yaml 의 require_parcel_bands 로 걸러집니다.")


def cmd_link(args):
    with db.connect() as con:
        trades = con.execute(
            "SELECT trade_id, lat, lon FROM trade WHERE lat IS NOT NULL"
        ).fetchdf()
        tgs = con.execute(
            "SELECT tollgate_id, lat, lon FROM tollgate WHERE lat IS NOT NULL"
        ).fetchdf()
        links = spatial.link_trades_to_tollgates(trades, tgs)
        con.execute("DELETE FROM trade_tollgate_link")
        n = db.upsert(con, "trade_tollgate_link", links)
    print(f"공간 조인 {n:,}쌍 "
          f"({links['trade_id'].nunique():,}건 거래가 영업소 반경 내)" if n else "조인 결과 없음")


def cmd_panel(args):
    with db.connect() as con:
        trades = con.execute("SELECT * FROM trade WHERE lat IS NOT NULL").fetchdf()
        links = con.execute("SELECT * FROM trade_tollgate_link").fetchdf()
        traffic = con.execute("SELECT * FROM traffic").fetchdf()
    if trades.empty or links.empty or traffic.empty:
        sys.exit("패널을 만들 재료가 부족합니다. status 로 확인하세요.")

    panel = pn.build_panel(trades, links, traffic)
    out = PROCESSED / "panel.parquet"
    panel.to_parquet(out, index=False)
    print(f"패널 {len(panel):,}행 → {out}")
    print(panel.groupby("band")["price_index"].count().to_string())


def cmd_analyze(args):
    path = PROCESSED / "panel.parquet"
    if not path.exists():
        sys.exit("panel.parquet 이 없습니다. 먼저 `panel` 을 실행하세요.")
    panel = pd.read_parquet(path)
    col = f"volume_{args.volume}" if args.volume != "total" else "volume_total"

    print("\n=== L1 수준 상관 (참고용, 교란 있음) ===")
    print(correlation.level_correlation(panel, col).to_string(index=False))

    print(f"\n=== L2/L3 거리밴드별 탄력성 ({col}, 1년 시차) ===")
    elast = correlation.elasticity_by_band(panel, col)
    print(elast.to_string(index=False))
    elast.to_csv(PROCESSED / f"elasticity_{col}.csv", index=False)

    print("\n=== 해석 ===")
    print(correlation.interpret(elast))


def cmd_score(args):
    path = PROCESSED / "panel.parquet"
    if not path.exists():
        sys.exit("panel.parquet 이 없습니다. 먼저 `panel` 을 실행하세요.")
    scores = scoring.build_scores(pd.read_parquet(path), band=args.band,
                                  volume_col=f"volume_{args.volume}")
    if scores.empty:
        sys.exit("스코어를 계산할 표본이 없습니다.")
    out = PROCESSED / "scores.csv"
    scores.to_csv(out, index=False)

    print(scores.groupby("quadrant").size().rename("영업소 수").to_string())
    print(f"\n=== 저평가 후보 상위 10 ===")
    top = scores[scores["quadrant_key"] == "undervalued"].head(10)
    cols = ["tollgate_id", "traffic_cagr", "price_cagr",
            "traffic_score", "price_score", "n_trades", "confidence"]
    print(top[cols].to_string(index=False) if len(top) else "  해당 없음")
    print(f"\n→ {out}")


def cmd_export_web(args):
    meta = webexport.export(band=args.band, volume_col=f"volume_{args.volume}")
    print("web/app/data/ 에 4개 파일 생성")
    print(f"  영업소 {meta['counts']['tollgates']} (스코어 {meta['counts']['scored']})")
    print(f"  거래 {meta['counts']['trades_total']:,} 중 지도 표시 "
          f"{meta['counts']['trades_plotted']:,}")
    print(f"  기간 {meta['year_min']}~{meta['year_max']}")
    if meta["is_synthetic"]:
        print("\n⚠️ 합성 데이터입니다 — 화면 상단에 데모 배너가 표시됩니다.")


def cmd_serve_api(args):
    import uvicorn
    print(f"http://{args.host}:{args.port} — 화면과 매물 API 가 같은 포트에서 뜹니다")
    uvicorn.run("redt.server.app:app", host=args.host, port=args.port, reload=args.reload)


def cmd_status(args):
    with db.connect(read_only=False) as con:
        for table in ("tollgate", "traffic", "trade", "trade_tollgate_link", "zone_event"):
            n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"{table:24s} {n:>12,}")
        geo = con.execute(
            "SELECT count(*) FILTER (WHERE lat IS NOT NULL), count(*) FROM trade"
        ).fetchone()
        if geo[1]:
            print(f"{'  └ 좌표 보유':24s} {geo[0]:>12,} ({geo[0] / geo[1]:.1%})")

        con.execute(db.COLLECT_LOG)
        progress = con.execute("""
            SELECT kind,
                   count(*) FILTER (WHERE status = 'ok')    AS ok,
                   count(*) FILTER (WHERE status = 'empty') AS empty,
                   count(*) FILTER (WHERE status = 'error') AS err
            FROM collect_log GROUP BY kind ORDER BY kind
        """).fetchdf()
        if not progress.empty:
            print("\n수집 진행 (셀 = 시군구×년월)")
            print(progress.to_string(index=False))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="redt", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("tollgates", help="영업소 마스터 수집")
    p.add_argument("--path", help="API 대신 사용할 CSV 경로")
    p.set_defaults(func=cmd_tollgates)

    p = sub.add_parser("traffic", help="교통량 파일 정규화·적재")
    p.add_argument("--path", required=True)
    p.add_argument("--inspect", action="store_true", help="컬럼만 확인하고 종료")
    p.add_argument("--source", help="소스 이름 (tcs / aadt / 자유문자열). 기본: 파일명")
    p.add_argument("--unit-type", default="tollgate", choices=["tollgate", "point"],
                   help="point 면 좌표로 최근접 영업소에 매핑")
    p.add_argument("--value", default="auto", choices=["auto", "daily", "annual"],
                   help="값이 일평균인지 연간누적인지")
    p.add_argument("--max-match-km", type=float, default=5.0,
                   help="point→영업소 매핑 최대 거리")
    p.add_argument("--mapping", help='컬럼 직접 지정 JSON 예: \'{"volume":"교통량"}\'')
    p.set_defaults(func=cmd_traffic)

    sub.add_parser("probe-ex", help="도로공사 API 엔드포인트 탐침").set_defaults(func=cmd_probe_ex)

    p = sub.add_parser("probe-history",
                       help="과거 날짜 조회 가능 범위 판정 (일별 백필 가능 여부)")
    p.add_argument("--endpoint", help="probe-ex 에서 확인한 경로")
    p.add_argument("--date-param", help="날짜 파라미터명 (예: stdDt)")
    p.set_defaults(func=cmd_probe_history)

    p = sub.add_parser("backfill", help="일별 교통량 백필 (중단 시 재개)")
    p.add_argument("--endpoint", required=True)
    p.add_argument("--date-param", required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_backfill)

    sub.add_parser("rollup", help="traffic_daily → 연 집계").set_defaults(func=cmd_rollup)
    sub.add_parser("coverage", help="교통량 시계열 확보 현황·분석가능 판정").set_defaults(
        func=cmd_coverage)

    p = sub.add_parser("trades", help="실거래가 수집 (중단 시 재개 가능)")
    p.add_argument("--kind", help="land,factory,house,commercial (기본: settings.yaml)")
    p.add_argument("--start", dest="start", default="2015-01")
    p.add_argument("--end", dest="end", default="2025-12")
    p.add_argument("--region", help="pilot_regions.yaml 의 권역명 (쉼표구분) 또는 all")
    p.add_argument("--sigungu", help="쉼표구분 5자리 코드 (--region 보다 우선)")
    p.add_argument("--refresh", action="store_true", help="이미 수집한 셀도 다시 조회")
    p.set_defaults(func=cmd_trades)

    p = sub.add_parser("regions", help="파일럿 권역 / 시군구 코드 확인")
    p.add_argument("--verify", action="store_true", help="각 코드로 시험 조회 (API 키 필요)")
    p.add_argument("--probe-ymd", default="202401", help="검증에 쓸 계약년월 YYYYMM")
    p.set_defaults(func=cmd_regions)

    p = sub.add_parser("geocode", help="지번 → 좌표")
    p.add_argument("--limit", type=int, help="이번 실행에서 신규 호출 상한")
    p.set_defaults(func=cmd_geocode)

    sub.add_parser("link", help="거래-영업소 공간 조인").set_defaults(func=cmd_link)
    sub.add_parser("panel", help="분석 패널 생성").set_defaults(func=cmd_panel)

    p = sub.add_parser("analyze", help="상관·탄력성 분석")
    p.add_argument("--volume", default="total", choices=["total", "freight", "passenger", "mid"])
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("score", help="영업소별 투자 스크리닝 스코어")
    p.add_argument("--band", default="0-3")
    p.add_argument("--volume", default="freight",
                   choices=["total", "freight", "passenger", "mid"])
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("export-web", help="웹 화면용 JSON 생성")
    p.add_argument("--band", default="0-3")
    p.add_argument("--volume", default="freight",
                   choices=["total", "freight", "passenger", "mid"])
    p.set_defaults(func=cmd_export_web)

    p = sub.add_parser("serve-api", help="매물 API + 화면 서버")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_serve_api)

    sub.add_parser("status", help="적재 현황").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
