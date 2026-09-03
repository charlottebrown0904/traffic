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
import yaml

from . import db, webexport
from .analyze import correlation, scoring
from .collect import geocode as gc
from .collect import backfill, ex_api, h3_files, rtms, tollgate, tollgate_fill, traffic as tr
from .collect import traffic_files as tfiles
from . import regions as rg
from .config import PROCESSED, ROOT, settings

ROOT_CFG = ROOT / "config"
from .transform import panel as pn
from .transform import spatial


# 다시 수집해도 지워지면 안 되는 칸들. 어느 것도 원본 API 응답에 없고,
# 따로 돈이나 호출을 들여 붙인 것이다 (db.upsert 의 preserve 참고).
GEOCODE_COLS = ["lat", "lon", "geocode_level"]      # 브이월드 하루 4,000건
# 민자 영업소 이름으로 찾은 좌표·지역, 그리고 명부에서만 오는 운영기관코드·
# 노선번호. 어느 출처도 나머지 출처의 칸을 갖고 있지 않으므로, 지키지 않으면
# 단계를 하나 돌 때마다 서로의 값을 지운다.
TOLLGATE_FILLED = ["lat", "lon", "sido", "sigungu", "operator_cd",
                   "route_no", "name"]


def _months(start: str, end: str) -> list[str]:
    rng = pd.period_range(start=start, end=end, freq="M")
    return [p.strftime("%Y%m") for p in rng]


def cmd_tollgates(args):
    df = tollgate.load_from_csv(args.path) if args.path else tollgate.fetch_tollgates()
    with db.connect() as con:
        # 도로공사 마스터에는 민자고속도로 좌표가 없다. fill-tollgates 가
        # 이름으로 찾아 채워둔 것을 이 단계가 다시 지우면, 매 실행마다
        # 같은 일을 반복하면서 그 사이 분석은 좌표 없는 영업소를 버린다.
        n = db.upsert(con, "tollgate", df, preserve=TOLLGATE_FILLED)
        # 도로공사 API 는 자기가 운영하는 노선만 안다. 명부(CSV)에는 민자
        # 노선 영업소까지 942곳이 들어 있고, 그중 가동중·비가상이 646곳이다.
        # 등재해 두지 않으면 fill-tollgates 가 좌표를 찾을 대상조차 모른다.
        roster = tollgate_fill.roster_from_master()
        m = db.upsert(con, "tollgate", roster,
                      preserve=["lat", "lon", "sido", "sigungu",
                                "sigungu_cd", "is_open_type"]) if len(roster) else 0
    print(f"영업소 {n}건 저장 · 명부 등재 {m}건")


def cmd_fill_tollgates(args):
    """교통량에만 있고 마스터에 없는 영업소(대부분 민자고속도로)를 이름으로 채운다."""
    with db.connect() as con:
        df = tollgate_fill.fill_missing(con, limit=args.limit)
        # 이름검색 결과에는 운영기관코드도 노선번호도 없다. 지키지 않으면
        # 좌표를 채우는 대가로 명부에서 받아온 칸을 지운다.
        n = db.upsert(con, "tollgate", df,
                      preserve=["operator_cd", "route_no"]) if len(df) else 0
        # 좌표를 채운 뒤에 지역을 되짚는다. 방금 넣은 영업소도 함께 채워진다.
        regions = 0 if args.skip_regions else tollgate_fill.fill_regions(con)
    print(f"영업소 {n}건 추가 (출처: 이름검색) · 지역 {regions}건 보완")


def cmd_load_traffic(args):
    """포털에서 받아 정리해둔 연간 교통량 CSV 를 traffic 테이블에 싣는다."""
    df = tfiles.load_files(args.pattern)
    if df.empty:
        sys.exit("실을 교통량 파일이 없습니다. scripts/convert_tcs_daily.py 로 "
                 "data/raw/tcs_annual_<연도>.csv 를 먼저 만드세요.")
    with db.connect() as con:
        ids = {r[0] for r in con.execute(
            "SELECT DISTINCT tollgate_id FROM tollgate").fetchall()}
        rate = tfiles.report_match(df, ids)
        n = db.upsert(con, "traffic", df)
    print(f"교통량 {n:,}행 저장 · 영업소 {df['tollgate_id'].nunique()}개 "
          f"· 연도 {[int(y) for y in sorted(df['year'].unique())]}")
    # 짝이 거의 안 맞으면 여기서 멈춘다. 그대로 두면 패널이 조용히 비고,
    # 표본이 없는 것인지 조인이 어긋난 것인지 구분할 수 없다.
    if ids and rate < 0.2:
        sys.exit("영업소 마스터와 짝이 거의 맞지 않습니다. 위 경고를 확인하세요.")


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


def cmd_probe_landprice(args):
    from .collect import landprice
    landprice.probe()


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


def cmd_sweep_codes(args):
    """접두사로 시군구 코드 범위를 훑어 실제로 자료가 있는 코드를 찾는다.

    구가 있는 시는 시 단위 코드에 0건이 온다. 게다가 행정구역 개편으로
    코드가 바뀌기도 한다 — 추측으로 적어 넣으면 그 시군구만 조용히 빈다.
    범위를 훑어 사실을 확인하는 편이 빠르고 확실하다.
    """
    prefix = args.prefix
    print(f"{prefix}00 ~ {prefix}99 를 훑습니다 ({args.probe_ymd}, land)")
    found = []
    for tail in range(100):
        code = f"{prefix}{tail:02d}"
        try:
            _, total = rtms.fetch_page("land", code, args.probe_ymd, page=1, rows=1)
        except Exception as exc:                     # noqa: BLE001
            print(f"  ERR {code} {exc}")
            continue
        if total > 0:
            print(f"  OK  {code}  totalCount={total}")
            found.append((code, total))
        rtms.polite_sleep()
    print(f"\n자료가 있는 코드 {len(found)}개: {[c for c, _ in found]}")


# 시도 2자리 접두. 세종(36)은 시군구 분할이 없지만 코드 체계는 같다.
# 손으로 적은 목록은 행정구역이 개편되면 조용히 낡습니다. 그래서 실호출로
# 확인한 것만 넣습니다.
#
#   12  전남광주통합특별시. 광주(29)와 전남(46)이 통합되면서 난 새 코드입니다.
#       find-new-sido 가 12110·12130·12170·12710·12730·12800 에서 실제
#       거래를 받아 확인했습니다. 그전까지 29·46 이 1000개 코드 모두 0건이라
#       '자료가 없다' 로 읽힐 뻔했습니다.
#   45  전북(구). 2024년에 52 로 바뀌었습니다.
#   29·46  통합 전 광주·전남. 과거 거래가 이 코드로 남아 있을 수 있어
#       지우지 않습니다 — 지우면 2006~2025 중 통합 이전 구간을 잃습니다.
# 실패가 코드 수의 이 비율을 넘으면 재시도하지 않는다.
RETRY_MAX_SHARE = 0.2

# 코드 체계가 바뀌어 **없어진 것이 정상인** 접두사.
#   29 광주 · 46 전남  → 12 전남광주통합 으로 합쳐짐 (27개 확인)
#   45 전북           → 52 전북특별자치도 로 바뀜
# 과거 거래가 옛 코드로 남아 있을 수 있어 목록에서 지우지는 않지만,
# 비어 있다고 경고하면 안 된다 — 거짓 경보가 잦으면 진짜 경보도 무시된다.
RETIRED_PREFIX = {"29", "45", "46"}

# 시군구가 원래 적은 시도. 세종은 단일 시라 1개, 제주는 2개가 정상이다.
SMALL_SIDO = {"36": 1, "50": 2}


SIDO_PREFIX = ["11", "12", "26", "27", "28", "29", "30", "31", "36",
               "41", "43", "44", "45", "46", "47", "48", "50", "51", "52"]


def probe_sigungu(args_):
    """시군구 코드 하나를 물어본다. (code, 건수) 또는 (code, None).

    **None 은 '모른다' 는 뜻이다. 0 과 다르다.**

    예전에는 예외를 전부 0 으로 바꿨다. 그러면 '호출이 막혔다' 가 '이 코드는
    존재하지 않는다' 로 기록된다. run 13 에서 광주(29)와 전남(46)이 통째로
    0개로 나온 것이 이것이다 — 27개 시군구가 전국에서 조용히 빠졌고, 화면이
    비어도 '거래가 없구나' 로 읽혔을 것이다.

    tollgate_fill.py 에서 CallFailed 로 이미 한 번 고친 실수인데, 여기로
    옮기지 않았다.
    """
    code, ym, kind = args_
    try:
        _, total = rtms.fetch_page(kind, code, ym, page=1, rows=1)
    except Exception:                                 # noqa: BLE001
        return code, None
    return code, total


# 시군구 코드의 첫 자리는 대개 이런 꼬리를 씁니다 — 구가 있는 시는 110·140,
# 군은 710·720 대. 접두사 하나가 살아 있는지 보는 데는 이 몇 개면 됩니다.
PROBE_TAILS = ("110", "111", "130", "170", "200", "710", "720", "730", "800")


def cmd_find_new_sido(args):
    """행정구역 개편으로 새로 난 시도 접두사를 찾는다.

    광주(29)·전남(46)이 RTMS 에서 1000개 코드 모두 0건입니다. KOSIS 시도
    목록에 '전남광주통합특별시' 가 있고 시도가 17개에서 16개로 줄었으니,
    통합되면서 새 코드를 받은 것으로 보입니다. 전북 45→52 와 같습니다.

    **새 코드가 무엇인지는 추측하지 않습니다.** 다만 접두사마다 1000개를
    다 훑으면 너무 비쌉니다(40개 접두사 × 1000 = 4만 회). 접두사 하나에
    대표 꼬리 9개만 찔러 보고, 하나라도 걸리는 접두사만 전면 훑습니다.
    """
    from concurrent.futures import ThreadPoolExecutor

    known = set(SIDO_PREFIX)
    cands = [f"{n:02d}" for n in range(int(args.lo), int(args.hi) + 1)
             if f"{n:02d}" not in known]
    print(f"후보 접두사 {len(cands)}개 × 꼬리 {len(PROBE_TAILS)}개 = "
          f"{len(cands) * len(PROBE_TAILS):,}회 (전면 훑기의 1/111)")
    print(f"  건너뛴 접두사(이미 아는 것): {sorted(known)}")

    pairs = [(f"{p}{t}", args.probe_ymd, "land")
             for p in cands for t in PROBE_TAILS]
    hits: dict[str, list[str]] = {}
    failed: list[tuple] = []
    calls = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for (code, total), pair in zip(pool.map(probe_sigungu, pairs), pairs):
            calls += 1
            if total is None:
                failed.append(pair)
            elif total > 0:
                hits.setdefault(code[:2], []).append(code)

    # 첫 실행에서 378번 중 272번이 실패했습니다(72%). 그 상태로는 '걸린 것이
    # 없다' 와 '못 물어봤다' 를 구분할 수 없습니다. 실패한 것만 천천히 다시
    # 물어봅니다 — 동시 수를 줄이고 사이를 띄웁니다.
    if failed:
        print(f"  실패 {len(failed):,}회 — 천천히 다시 물어봅니다")
        from .collect.rtms import polite_sleep
        still = []
        with ThreadPoolExecutor(max_workers=max(2, args.workers // 4)) as pool:
            for (code, total), pair in zip(pool.map(probe_sigungu, failed), failed):
                calls += 1
                if total is None:
                    still.append(pair)
                elif total > 0:
                    hits.setdefault(code[:2], []).append(code)
                polite_sleep(0.05)
        failed = still

    print(f"\n호출 {calls:,}회 · 끝내 실패 {len(failed):,}회")
    if failed:
        rate = len(failed) / max(calls, 1)
        print(f"  ⚠ 실패율 {rate:.0%} — 이 결과는 결론이 아닙니다.")
        print("     못 물어본 접두사에 코드가 있어도 안 걸립니다. 실패율이")
        print("     낮아질 때까지 --workers 를 줄여 다시 돌리세요.")
    if not hits:
        print("걸린 접두사가 없습니다.")
        print("  대표 꼬리에 없는 번호만 쓰는 시도일 수 있습니다. --lo/--hi 를")
        print("  넓히거나, 걸리는 것이 없으면 통합 시도가 아직 RTMS 에")
        print("  반영되지 않은 것입니다.")
        return
    print(f"\n걸린 접두사 {len(hits)}개 — 이것만 전면 훑으면 됩니다:")
    for prefix, codes in sorted(hits.items()):
        print(f"  {prefix}  {sorted(codes)}")
    print(f"\n다음: python -m redt.cli discover-sigungu --refresh "
          f"--sido {','.join(sorted(hits))}")


def cmd_discover_sigungu(args):
    """전국 시군구 코드를 **훑어서** 찾는다. 추측하지 않는다.

    RTMS 는 잘못된 코드에 오류가 아니라 0건을 돌려줍니다. 그래서 코드를
    손으로 적어 넣으면 그 시군구만 조용히 빕니다 — 표가 비어도 '거래가
    없구나' 로 읽히고, 몇 달 뒤에야 알아챕니다. 실제로 그럴 뻔했습니다.

    시도 18개 × 3자리 꼬리 1000 = 18,000개를 **한 번씩** 물어봅니다.
    한 번만 하면 되고, 결과는 config/sigungu_codes.yaml 에 남아 다음부터는
    안 물어봅니다.

    처음에는 '거래가 드문 군을 놓치지 않으려고' 세 달 × 두 종류를 시도해
    코드당 최대 6회를 불렀습니다. 108,000회로 하루 한도(10만)를 넘겨
    1시간 25분 만에 취소했습니다. 비용의 거의 전부가 **없는 코드를 확인하는
    데** 들어갑니다 — 유효한 코드는 250개 안팎이고 나머지 17,750개가 6회씩
    불렸습니다.
    """
    from concurrent.futures import ThreadPoolExecutor

    out_path = ROOT_CFG / "sigungu_codes.yaml"
    known: dict[str, dict] = {}
    if out_path.exists():
        # --refresh 여도 읽는다. 병합하려면 기존 내용을 알아야 한다.
        known = yaml.safe_load(out_path.read_text(encoding="utf-8")) or {}
    if out_path.exists() and not args.refresh:
        total = sum(len(v) for v in known.values())
        print(f"이미 찾아둔 코드 {total:,}개 — 다시 찾으려면 --refresh")
        # **부실한 목록이 조용히 재사용되는 것을 막습니다.**
        #
        # 훑기는 상대가 막으면 코드를 놓칩니다. 그렇게 만들어진 목록이
        # 파일에 남으면, 다음부터는 '이미 찾아뒀다' 며 건너뛰고 그 시군구는
        # 영원히 빕니다. 오류도 경고도 없이 표만 비어 보입니다.
        #
        # 그래서 건너뛸 때마다 파일 자체를 훑어 수상한 것을 말합니다.
        def _suspicious(sido: str, codes) -> str:
            """비어 있거나 적은 것이 **이상한** 경우만 고른다."""
            if sido in RETIRED_PREFIX:
                return ""          # 없어진 것이 정상이다
            floor = SMALL_SIDO.get(sido, 3)
            if not codes:
                return "   ⚠ 비어 있습니다 — 훑기가 막혔을 수 있습니다"
            if len(codes) < floor:
                return f"   ⚠ 너무 적습니다 ({floor}개 이상이 정상)"
            return ""

        empty = [k for k, v in known.items()
                 if not v and k not in RETIRED_PREFIX]
        thin = [k for k, v in known.items()
                if v and _suspicious(k, v)]
        for sido, codes in sorted(known.items()):
            mark = _suspicious(sido, codes)
            if sido in RETIRED_PREFIX and not codes:
                mark = "   (코드 체계가 바뀌어 없어진 접두사 — 정상)"
            print(f"  {sido}  {len(codes):>3}개{mark}")
        if empty or thin or total < 200:
            print()
            print("  ⚠ 이 목록은 온전하지 않아 보입니다.")
            if empty:
                print(f"     빈 시도: {sorted(empty)}")
            if thin:
                print(f"     너무 적은 시도: {sorted(thin)}")
            if total < 200:
                print(f"     전체 {total}개 — 230개 안팎이 정상입니다")
            print("     그 시군구의 거래는 계속 0건으로 보입니다. 고치려면:")
            print(f"     discover-sigungu --refresh --sido "
                  f"{','.join(sorted(set(empty + thin))) or '<해당 시도>'}")
            print("     (이제 병합되므로 다른 시도는 지워지지 않습니다)")
        return

    prefixes = args.sido.split(",") if args.sido else SIDO_PREFIX
    ymd = args.probe_ymd
    print(f"시도 {len(prefixes)}개 × 1000 코드를 {ymd} 기준으로 훑습니다 "
          f"(동시 {args.workers}개)")
    print("주의: 0건이 '코드가 없다' 는 뜻은 아닙니다 — 그 달 그 시군구에 "
          "토지 거래가 없었을 수도 있습니다. 그래서 여러 달을 시도합니다.")

    # **코드 하나에 한 번만 묻는다.**
    #
    # 처음에는 '거래가 드문 군을 놓치지 않으려고' 세 달 × 두 종류를 시도했다.
    # 코드 하나에 최대 6회다. 18,000개 × 6 = 108,000회로 하루 한도(10만)를
    # 넘긴다. 실제로 그렇게 돌려 1시간 25분 만에 취소했다. 유효한 코드는
    # 250개 안팎이고 나머지 17,750개가 6회씩 부르는 구조였다 — 비용의
    # 거의 전부가 '없는 코드' 를 확인하는 데 들어간다.
    #
    # 토지 거래는 전국 어느 시군구든 매달 있다. 한 번으로 충분하다.
    # 그래도 0 이 나온 코드는 2차로 한 번 더 본다 — 다만 **찾은 코드
    # 근처만** 본다. 시군구 코드는 뭉쳐 있어서, 유효한 코드 옆이 아니면
    # 유효할 가능성이 거의 없다.
    probe = probe_sigungu

    extra = [m for m in (args.extra_ymd or "").split(",") if m.strip()]
    found: dict[str, dict] = {}
    shaky: list[str] = []        # 호출이 끝내 실패해 결론을 못 낸 시도
    calls = 0
    for prefix in prefixes:
        codes = [f"{prefix}{tail:03d}" for tail in range(1000)]
        hits: dict[str, int] = {}
        failed: list[str] = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for code, total in pool.map(probe, [(c, ymd, "land") for c in codes]):
                calls += 1
                if total is None:
                    failed.append(code)
                elif total > 0:
                    hits[code] = int(total)

        # 실패한 것만 한 번 더 물어본다. **다만 실패가 많으면 안 한다.**
        #
        # '정상이면 몇 개 안 되므로 싸다' 고 적어놓고 그 전제를 확인하지
        # 않았습니다. 실제로는 실패율이 70%까지 올라갔고, 실패 하나가
        # 15초 대기(get_once 시한)를 씁니다. 1000개 중 700개가 실패하면
        # 재시도만으로 700×15초÷8 = 22분이 시도 하나에 더 붙습니다.
        # 18개 시도면 6시간이 넘어 작업 제한을 넘습니다.
        #
        # 실패가 많다는 것은 상대가 막고 있다는 뜻이고, 그때 더 부르는 것은
        # 상황을 나쁘게만 합니다. 그냥 '결론이 아니다' 라고 말하고 넘어갑니다.
        if failed and len(failed) > len(codes) * RETRY_MAX_SHARE:
            print(f"  ⚠ {prefix}: 실패 {len(failed):,}/{len(codes):,} — 너무 많아 "
                  f"재시도하지 않습니다 (상대가 막고 있을 때 더 부르면 악화됩니다)")
        elif failed:
            retry_pairs = [(c, ymd, "land") for c in failed]
            failed = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for code, total in pool.map(probe, retry_pairs):
                    calls += 1
                    if total is None:
                        failed.append(code)
                    elif total > 0:
                        hits[code] = int(total)

        # 2차: 찾은 코드의 ±3 이웃 중 아직 0 인 것만, 다른 달로 한 번 더.
        if hits and extra:
            near = set()
            for code in hits:
                tail = int(code[-3:])
                near |= {f"{prefix}{t:03d}" for t in range(max(0, tail - 3), tail + 4)}
            retry = [c for c in sorted(near) if c not in hits]
            if retry:
                pairs = [(c, extra[0], "land") for c in retry]
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    for code, total in pool.map(probe, pairs):
                        calls += 1
                        # total 은 None(모름)일 수 있다. 여기서 그것을 빠뜨려
                        # run 14 가 터졌다 — 세 군데 중 두 군데만 고쳤었다.
                        if total is not None and total > 0:
                            hits[code] = int(total)

        found[prefix] = hits
        note = ""
        if failed:
            shaky.append(prefix)
            note = f"  ⚠ 호출 실패 {len(failed)}건 — 이 시도는 결론이 아닙니다"
        print(f"  {prefix}  {len(hits):>3}개  {sorted(hits)[:8]}"
              f"{' …' if len(hits) > 8 else ''}  (누적 호출 {calls:,}){note}")
        # 시도 하나가 통째로 비는 것은 자료가 아니라 사고다. 어느 시도든
        # 토지 거래가 한 달에 0건일 수는 없다. 유일한 정상 사례는 코드
        # 체계가 바뀐 경우다 (전북 45 → 52, 강원 42 → 51).
        if not hits and not failed:
            print(f"       ⚠ {prefix} 는 한 건도 없습니다. 그 시도에 토지 "
                  f"거래가 정말 0건일 수는 없습니다 — 코드 체계가 바뀌었거나"
                  f"(전북 45→52 처럼) 호출이 조용히 막힌 것입니다.")

    print(f"\n총 호출 {calls:,}회")
    if shaky:
        print(f"⚠ 호출이 끝내 실패한 시도: {', '.join(shaky)} — "
              f"--sido {','.join(shaky)} 로 다시 돌리세요.")

    # **이번에 훑지 않은 시도는 그대로 둔다.**
    #
    # found 만 그대로 쓰면, `--refresh --sido 12` 처럼 한 시도만 다시 훑을 때
    # 나머지 197개 코드가 통째로 지워진다. 새 시도(전남광주통합 12)를
    # 넣으려고 바로 그렇게 할 참이었다.
    merged = dict(known)
    for prefix, codes in found.items():
        merged[prefix] = codes
    kept = [k for k in merged if k not in found]
    if kept and known:
        print(f"\n이번에 안 훑은 시도 {len(kept)}개는 그대로 둡니다: {sorted(kept)}")

    total_codes = sum(len(v) for v in merged.values())
    print(f"\n전국 시군구 코드 {total_codes:,}개 "
          f"(이번에 찾은 것 {sum(len(v) for v in found.values()):,}개)")
    if total_codes < 200:
        print("  ⚠ 230개 안팎이 정상입니다. 이보다 훨씬 적으면 조회한 달에 "
              "거래가 드물었을 수 있습니다. --extra-ymd 로 달을 더 주세요.")
    out_path.write_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=True), encoding="utf-8")
    print(f"→ {out_path}")


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


# 한 요청에 1.6초가 걸리는데 그 대부분이 왕복 대기다. 미국 러너에서
# 서울 중계기를 거쳐 국토부까지 갔다 온다. 순차로 만 번을 돌면 다섯 시간이
# 넘고, 그 시간의 거의 전부가 기다림이다. 동시에 보내면 그만큼 줄어든다.
#
# 가져오기만 여러 스레드로 하고, DB 쓰기는 이 스레드에서만 한다. DuckDB
# 연결은 여러 스레드가 동시에 쓰라고 만들어진 물건이 아니다.
def _collect_cells(con, kind, todo, workers):
    """(저장한 행수, 중단했는가). 셀 하나가 실패해도 나머지는 계속한다."""
    from concurrent.futures import ThreadPoolExecutor

    if not todo:
        return 0, False

    # 연달아 이만큼 실패하면 우리가 차단당한 것으로 본다. 하나둘 실패는
    # 흔하지만 연속 실패는 다르다. 그대로 두면 남은 셀을 전부 '조회했으나
    # 실패' 로 기록해버려서, 다음 실행이 이어받을 것을 없애버린다.
    GIVE_UP = 40

    total_rows = 0
    streak = 0
    n_err = 0
    stopped = False

    def work(cell):
        code, ym = cell
        try:
            return cell, rtms.fetch_month(kind, code, ym), None
        except Exception as exc:                      # noqa: BLE001
            return cell, None, exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # map 은 순서를 지키므로 진행률이 사람이 읽기 좋게 나온다.
        for i, (cell, df, exc) in enumerate(pool.map(work, todo), 1):
            code, ym = cell
            if exc is not None:
                db.log_cell(con, kind, code, ym, 0, "error", str(exc))
                n_err += 1
                streak += 1
                if streak <= 3 or streak % 10 == 0:
                    print(f"  실패 {code}/{ym}: {exc}")
                if streak >= GIVE_UP:
                    print(f"\n연달아 {streak}건 실패했습니다. 차단이나 장애로 보고 멈춥니다.")
                    stopped = True
                    break
                continue
            streak = 0
            # 좌표는 지오코딩이 따로 붙인 것이라 API 응답에 없다.
            # preserve 없이 넣으면 재수집이 그것을 지운다(db.upsert 참고).
            n = db.upsert(con, "trade", df,
                          preserve=GEOCODE_COLS)
            db.log_cell(con, kind, code, ym, n, "ok" if n else "empty")
            total_rows += n
            if i % 100 == 0 or i == len(todo):
                print(f"  {i:,}/{len(todo):,}  누적 {total_rows:,}건"
                      + (f"  실패 {n_err:,}" if n_err else ""))

    if n_err and not stopped:
        print(f"  실패 {n_err:,}건 — 다음 실행에서 다시 시도합니다.")
    return total_rows, stopped


def cmd_trades(args):
    with db.connect() as con:
        targets = _target_sigungu(args, con)
        months = _months(args.start, args.end)
        kinds = args.kind.split(",") if args.kind else settings()["trade_kinds"]

        planned = len(kinds) * len(targets) * len(months)
        print(f"수집 계획: {len(kinds)}종 × {len(targets)}개 시군구 × {len(months)}개월 "
              f"= {planned:,} 요청")

        workers = max(1, int(args.workers))
        print(f"동시 요청 {workers}개")

        # 전국 × 2006~2025 는 셀이 11만 개가 넘어 하루 한도(운영계정 10만)를
        # 한 번에 못 넘깁니다. 이번 실행에서 몇 개까지 할지 정해 두고, 남은
        # 것은 다음 실행이 이어받습니다. done_cells 가 이미 그렇게 되어 있어
        # 여기서는 자를 지점만 정하면 됩니다.
        budget = args.max_cells if args.max_cells and args.max_cells > 0 else None
        if budget:
            print(f"이번 실행 예산 {budget:,}셀 — 남는 것은 다음 실행이 이어받습니다")

        total_rows = 0
        spent = 0
        for kind in kinds:
            done = set() if args.refresh else db.done_cells(con, kind)
            todo = [(c, ym) for c in targets for ym in months if (c, ym) not in done]
            remaining = len(todo)
            if budget is not None:
                todo = todo[: max(0, budget - spent)]
            print(f"\n[{kind}] 남은 셀 {remaining:,} (이미 완료 {len(done):,})"
                  + (f" · 이번에 {len(todo):,}개" if budget else ""))
            if not todo:
                continue
            n_rows, stopped = _collect_cells(con, kind, todo, workers)
            total_rows += n_rows
            spent += len(todo)
            if stopped:
                print("\n남은 셀은 다음 실행에서 이어받습니다.")
                break
            if budget is not None and spent >= budget:
                print(f"\n예산 {budget:,}셀을 다 썼습니다. 남은 것은 다음 실행에서.")
                break

    print(f"\n실거래 {total_rows:,}건 신규 저장")


def cmd_geocode_repair(args):
    """한도 초과로 오염됐을 수 있는 캐시 항목을 버린다."""
    cache = gc.GeocodeCache()
    before = len(cache)
    dropped, kept = gc.purge_failures(cache)
    print(f"캐시 {before:,}건 → 좌표 있는 {kept:,}건만 남기고 {dropped:,}건 버림")
    if dropped:
        print()
        print("버린 항목은 다음 지오코딩에서 다시 물어봅니다.")
        print("그중 진짜로 없는 주소는 또 실패하지만, 예전에 한도 때문에")
        print("실패로 박힌 것들은 이번에 좌표를 얻습니다. 둘을 구분할 방법이")
        print("캐시에 남아 있지 않아 통째로 다시 묻습니다.")
    else:
        print("버릴 것이 없습니다 — 오염된 항목이 없습니다.")


def cmd_geocode_staged(args):
    """2단계 지오코딩 — 법정동을 먼저, 영업소 반경 안만 지번으로.

    좌표 없는 거래가 329만 건인데 브이월드 하루 한도는 4,000건입니다.
    그대로면 822번 돌려야 합니다. **전국을 다 붙일 필요가 없습니다** —
    거리 밴드에 들어갈 수 있는 것에만 지번 좌표가 필요합니다.
    """
    from .transform.spatial import umd_near_tollgates

    wanted = [] if args.all else (settings().get("land_use_filter") or [])
    where = "1=1"
    if wanted:
        # 용도지역이 **비어 있는 거래도 통과**시킨다. 공장·창고(InduTrade)
        # API 는 용도지역을 주지 않으므로, LIKE 조건만 걸면 공장 거래가
        # 통째로 지오코딩 대기열에서 빠진다 — 좌표가 안 붙으니 지도에도
        # 표에도 안 나오고, '공장 거래가 원래 적구나' 로 읽힌다.
        # 걸러야 할 것은 '조건에 안 맞는 땅' 이지 '물어볼 칸이 없는 물건'
        # 이 아니다.
        cond = " OR ".join(f"land_use LIKE '%{w}%'" for w in wanted)
        where += f" AND ({cond} OR land_use IS NULL OR land_use = '')"

    with db.connect() as con:
        pairs_df = con.execute(
            f"SELECT DISTINCT sigungu, umd FROM trade WHERE {where} "
            f"AND umd IS NOT NULL"
        ).fetchdf()
        tgs = con.execute(
            "SELECT lat, lon FROM tollgate WHERE lat IS NOT NULL"
        ).fetchdf()

    if pairs_df.empty:
        print("대상 거래가 없습니다.")
        return
    print(f"1단계 — 법정동 {len(pairs_df):,}개 (거래 건수와 무관합니다)")
    pairs = [(r.sigungu, r.umd) for r in pairs_df.itertuples()]
    cache = gc.GeocodeCache()
    umd_coords = gc.geocode_umd(pairs, cache=cache, limit=args.umd_limit)

    if not umd_coords:
        print("법정동 좌표를 하나도 얻지 못했습니다. 여기서 멈춥니다.")
        return

    umd_points = pd.DataFrame(
        [{"sigungu": k[0], "umd": k[1], "lat": v[0], "lon": v[1]}
         for k, v in umd_coords.items()])

    print(f"\n2단계 — 영업소 반경 안 법정동만 지번으로 올립니다")
    if tgs.empty:
        print("  영업소 좌표가 없어 반경을 못 가립니다. 1단계까지만 반영합니다.")
        near = umd_points.iloc[0:0]
    else:
        max_km = float(settings()["spatial"]["max_link_km"])
        near = umd_near_tollgates(umd_points, tgs, max_km=max_km)

    parcel_coords = {}
    if not near.empty:
        keys = set(zip(near["sigungu"], near["umd"]))
        with db.connect() as con:
            todo = con.execute(
                f"SELECT DISTINCT sigungu, umd, jibun FROM trade "
                f"WHERE {where} AND lat IS NULL AND jibun IS NOT NULL"
            ).fetchdf()
        rows = [(r.sigungu, r.umd, r.jibun) for r in todo.itertuples()
                if (r.sigungu, r.umd) in keys]
        print(f"  반경 안 거래 주소 {len(rows):,}개 "
              f"(전체 {len(todo):,} 중 {len(rows) / max(len(todo), 1):.1%})")
        parcel_coords = gc.geocode_parcel(rows, cache=cache, limit=args.limit)

    # 지번이 있으면 지번을, 없으면 법정동 중심점을 쓴다.
    with db.connect() as con:
        if parcel_coords:
            fine = pd.DataFrame(
                [{"sigungu": k[0], "umd": k[1], "jibun": k[2],
                  "lat": v[0], "lon": v[1], "geocode_level": "parcel"}
                 for k, v in parcel_coords.items() if v[0] is not None])
            con.register("_fine", fine)
            con.execute("""
                UPDATE trade SET lat = g.lat, lon = g.lon,
                                 geocode_level = g.geocode_level
                FROM _fine g
                WHERE trade.sigungu IS NOT DISTINCT FROM g.sigungu
                  AND trade.umd IS NOT DISTINCT FROM g.umd
                  AND trade.jibun IS NOT DISTINCT FROM g.jibun
            """)
            con.unregister("_fine")
            print(f"  지번단위 {len(fine):,}개 주소를 반영했습니다")

        # **반경 안 법정동에만** 거친 좌표를 쓴다.
        #
        # 예전에는 전국 법정동 전부에 썼다. 그러면 영업소에서 100km 떨어진
        # 거래에도 좌표가 붙고, 그 거래가 전부 공간 조인 대상이 된다.
        # run 17 이 그 조인에서 러너째 죽었다 — 좌표 있는 거래가 수백만
        # 건으로 불어났기 때문이다.
        #
        # 반경 밖 거래는 어느 밴드에도 못 들어가므로 좌표를 붙일 이유가
        # 없다. 붙이면 비용만 늘고 쓰이지는 않는다.
        coarse = (near[["sigungu", "umd", "lat", "lon"]]
                  if not near.empty else umd_points.iloc[0:0])
        coarse = coarse.assign(geocode_level="umd")
        print(f"  거친 좌표를 쓸 법정동 {len(coarse):,}개 "
              f"(전체 {len(umd_points):,} 중 반경 안만)")
        con.register("_coarse", coarse)
        # **이미 지번 좌표가 있는 행은 건드리지 않는다.** 거친 좌표로
        # 덮으면 정밀도가 조용히 내려간다.
        con.execute("""
            UPDATE trade SET lat = g.lat, lon = g.lon, geocode_level = 'umd'
            FROM _coarse g
            WHERE trade.lat IS NULL
              AND trade.sigungu IS NOT DISTINCT FROM g.sigungu
              AND trade.umd IS NOT DISTINCT FROM g.umd
        """)
        con.unregister("_coarse")

        breakdown = con.execute("""
            SELECT coalesce(geocode_level, '미해결') AS level, count(*) AS n
            FROM trade GROUP BY 1 ORDER BY n DESC
        """).fetchdf()
    print("\n거래 기준 좌표 정밀도")
    print(breakdown.to_string(index=False))
    print("\n※ umd 는 법정동 중심점이라 오차 ±1~2km 입니다. 근거리 밴드에서는")
    print("   settings.yaml 의 require_parcel_bands 로 걸러집니다.")


def cmd_geocode(args):
    # 분석에 쓰지 않을 용도지역까지 좌표를 찍으면 일일 한도만 태운다.
    # 권역을 넓히면 대기열이 백만 건 단위가 되므로 여기서 걸러야 한다.
    wanted = [] if args.all else (settings().get("land_use_filter") or [])
    where = "lat IS NULL"
    if wanted:
        # 용도지역이 빈 거래도 포함한다 (geocode-staged 의 같은 이유).
        cond = (" OR ".join(f"land_use LIKE '%{w}%'" for w in wanted)
                + " OR land_use IS NULL OR land_use = ''")
        where += f" AND ({cond})"

    with db.connect() as con:
        if wanted:
            total = con.execute(
                "SELECT count(DISTINCT (sigungu, umd, jibun)) FROM trade WHERE lat IS NULL"
            ).fetchone()[0]
        todo = con.execute(
            f"SELECT DISTINCT sigungu, umd, jibun FROM trade WHERE {where}"
        ).fetchdf()
        if wanted:
            print(f"  용도지역 {wanted} 만 지오코딩합니다 — 대기 {len(todo):,} "
                  f"(전체 {total:,} 중). --all 로 전부 처리할 수 있습니다.")
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
    print("   근거리 밴드 분석에서는 settings.yaml 의 require_parcel_bands 로 걸러집니다.")


LINK_CHUNK = 200_000


def cmd_link(args):
    """거래 ↔ 영업소 공간 조인.

    결과를 **청크마다 DB 에 흘려 넣는다.** 예전에는 전부 메모리에 쌓아
    두었다가 한 번에 넣었는데, 좌표 있는 거래가 수백만 건이 되자 러너가
    메모리 부족으로 통째로 죽었다(run 17). 러너가 죽으면 if: always() 인
    캐시 저장 단계조차 안 돌아서, 그 앞의 수집·지오코딩 4시간 30분이
    같이 사라진다.
    """
    with db.connect() as con:
        total = con.execute(
            "SELECT count(*) FROM trade WHERE lat IS NOT NULL").fetchone()[0]
        # no_traffic 을 함께 넘긴다. 연결은 전부 만들되, 패널이 쓸 대표
        # 영업소(is_nearest)는 교통량이 있는 곳 중에서 고르게 하기 위해서다.
        # 안 그러면 마도 같은 미공개 영업소를 지도에 띄우는 순간 그 주변
        # 거래가 패널에서 통째로 빠진다 (spatial.link_trades_to_tollgates).
        tgs = con.execute("""
            SELECT t.tollgate_id, t.lat, t.lon,
                   (v.tollgate_id IS NULL) AS no_traffic
            FROM tollgate t
            LEFT JOIN (SELECT DISTINCT tollgate_id FROM traffic) v
                   ON v.tollgate_id = t.tollgate_id
            WHERE t.lat IS NOT NULL
        """).fetchdf()
        if not total or tgs.empty:
            print("조인 결과 없음 (좌표 있는 거래 또는 영업소가 없습니다)")
            return

        con.execute("DELETE FROM trade_tollgate_link")
        n, seen, done = 0, set(), 0
        for off in range(0, total, LINK_CHUNK):
            block = con.execute(
                "SELECT trade_id, lat, lon FROM trade WHERE lat IS NOT NULL "
                f"ORDER BY trade_id LIMIT {LINK_CHUNK} OFFSET {off}").fetchdf()
            if block.empty:
                break
            links = spatial.link_trades_to_tollgates(block, tgs)
            done += len(block)
            if len(links):
                n += db.upsert(con, "trade_tollgate_link", links)
                seen.update(links["trade_id"].unique().tolist())
            print(f"  {done:,}/{total:,}  누적 {n:,}쌍")
    print(f"공간 조인 {n:,}쌍 ({len(seen):,}건 거래가 영업소 반경 내)"
          if n else "조인 결과 없음")


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

    # 추이 비교 차트가 용도지역별로 갈라 보려면 거래 단위 자료가 필요하다.
    # 패널은 이미 밴드×연도로 접어버린 뒤라 되돌릴 수 없다.
    priced = getattr(pn.build_panel, "last_priced", None)
    if priced is not None and len(priced):
        pp = PROCESSED / "trades_priced.parquet"
        priced.to_parquet(pp, index=False)
        print(f"보정 거래 {len(priced):,}행 → {pp}")


def cmd_analyze(args):
    path = PROCESSED / "panel.parquet"
    if not path.exists():
        sys.exit("panel.parquet 이 없습니다. 먼저 `panel` 을 실행하세요.")
    panel = pd.read_parquet(path)
    col = f"volume_{args.volume}" if args.volume != "total" else "volume_total"

    print(f"\n=== 표본 점검 (패널 {len(panel):,}행) ===")
    health = correlation.panel_health(panel, col)
    print(health.to_string(index=False))
    print("  패널행이 많아도 셀당 최소 거래건수를 못 채우면 가격지수가 결측이라"
          " 회귀에 못 들어갑니다.")

    print("\n=== L1 수준 상관 (참고용, 교란 있음) ===")
    lvl = correlation.level_correlation(panel, col)
    print(lvl.to_string(index=False) if len(lvl)
          else "  밴드×종류마다 30행을 넘는 칸이 없습니다 — 위 표의 '수준분석가능' 을 보세요.")

    print(f"\n=== L2/L3 거리밴드별 탄력성 ({col}, 1년 시차) ===")
    elast = correlation.elasticity_by_band(panel, col)
    print(elast.to_string(index=False) if len(elast) else "  추정할 칸이 없습니다.")
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
    from .webexport import WEB_DATA
    made = sorted(f.name for f in WEB_DATA.glob("*.json"))
    print(f"public/app/data/ 에 {len(made)}개 파일 생성: {', '.join(made)}")
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


def cmd_rank(args):
    """지시3 — IC 를 교통량 순으로 세우고 주변 지가를 같은 기준으로 비교."""
    from .analyze import cross
    panel_path = PROCESSED / "panel.parquet"
    if not panel_path.exists():
        sys.exit("panel.parquet 이 없습니다. `panel` 을 먼저 실행하세요.")
    panel = pd.read_parquet(panel_path)
    with db.connect(read_only=True) as con:
        tgs = con.execute(
            "SELECT tollgate_id, name, sido, sigungu, lat, lon "
            "FROM tollgate WHERE lat IS NOT NULL").fetchdf()
    cross.report(panel, tgs, year=args.year, kind=args.kind,
                 volume_col=f"volume_{args.volume}", top=args.top)


def cmd_events(args):
    """지시2 — 신규 개통 영업소 주변 지가를 개통 전후로 비교 (이중차분)."""
    from .analyze import events
    with db.connect(read_only=True) as con:
        trades = con.execute("SELECT * FROM trade WHERE lat IS NOT NULL").fetchdf()
        links = con.execute("SELECT * FROM trade_tollgate_link").fetchdf()
    if trades.empty or links.empty:
        sys.exit("거래 또는 공간조인이 비어 있습니다. status 로 확인하세요.")
    kept = trades[~trades["is_share_deal"].fillna(False)
                  & ~trades["is_cancelled"].fillna(False)]
    priced = pn.hedonic_adjust(pn.filter_land_use(kept))
    events.report(priced, links, kind=args.kind)


def cmd_kosis_fetch(args):
    """확인된 통계표를 받아 region_*.csv 로 저장한다."""
    from .collect import kosis

    spec = kosis.TABLES.get(args.table)
    if spec is None:
        sys.exit(f"모르는 표 이름: {args.table} (가능: {list(kosis.TABLES)})")
    print(f"{spec['name']}  orgId={spec['orgId']} tblId={spec['tblId']}")
    print(f"  기간 {args.start}~{args.end}")
    rows = kosis.fetch_table(spec["orgId"], spec["tblId"], args.start, args.end)
    if not rows:
        sys.exit("받은 행이 없습니다. 위 응답 앞부분을 보고 파라미터를 맞추세요.")

    df = pd.DataFrame(rows)
    print(f"\n  {len(df):,}행 · 칸 {len(df.columns)}개")
    for c in df.columns:
        print(f"    - {c}")
    out = ROOT / "data" / "raw" / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n{out}")

    # 시군구코드·연도가 실제로 읽히는지 여기서 바로 본다. 안 읽히면
    # 파일만 받아놓고 나중에 알게 된다.
    from .collect.h3_files import REGION_COLS, _pick
    for want in ("sigungu_cd", "sigungu_nm", "year", "population", "item_nm"):
        got = _pick(df, REGION_COLS[want])
        mark = "✅" if got else "⚠"
        print(f"  {mark} {want} ← {got or '못 찾음'}")

    # **C1 이 법정동 코드인지 KOSIS 자체 코드인지 확인합니다.**
    # KOSIS 시도 코드는 법정동과 달랐습니다(부산 21 vs 26). 확인 없이
    # 조인하면 절반이 조용히 안 붙습니다.
    code_col = _pick(df, REGION_COLS["sigungu_cd"])
    name_col = _pick(df, REGION_COLS["sigungu_nm"])
    if code_col is not None:
        vals = df[code_col].astype(str).str.strip()
        print(f"\n  지역코드({code_col}) 정체 확인")
        print(f"    고유값 {vals.nunique():,}개 · 자릿수 분포 "
              f"{vals.str.len().value_counts().head(5).to_dict()}")
        sample = df[[code_col] + ([name_col] if name_col else [])].drop_duplicates()
        print(f"    표본 12개:")
        for r in sample.head(12).itertuples(index=False):
            print(f"      {r}")
        print("    → 5자리이고 41xxx(경기)·11xxx(서울) 모양이면 법정동 코드입니다.")
        print("       2자리나 다른 모양이면 KOSIS 자체 코드라 이름으로 맞춰야 합니다.")


def cmd_kosis_find(args):
    """통계표를 이름으로 찾고, 현재 시도 코드를 확인한다."""
    from .collect import kosis

    print("=" * 70)
    print("KOSIS 의 시도 목록")
    print("=" * 70)
    # **KOSIS 코드와 법정동 코드는 다른 체계입니다.** 나란히 놓고 다르다고
    # 표시하면 의미 없는 경고가 됩니다 — 실제로 한 번 그렇게 찍었습니다.
    #
    #   부산  KOSIS 21 · 법정동 26
    #   경기  KOSIS 31 · 법정동 41
    #
    # 코드는 못 맞춥니다. 대신 **개수와 이름**을 봅니다. 시도가 하나 줄고
    # 통합 이름이 보이면 행정구역 개편이 있었다는 뜻이고, 그러면 우리
    # 법정동 접두사 목록이 낡았다는 신호입니다.
    try:
        rows = kosis.sido_codes()
        for code, name in rows:
            print(f"  {code:8s} {name}")
        print(f"\n  KOSIS 시도 {len(rows)}개 · 우리 법정동 접두사 {len(SIDO_PREFIX)}개")
        merged = [n for _, n in rows if "통합" in n]
        if merged:
            print(f"  ⚠ 통합으로 보이는 시도: {merged}")
            print("     법정동 코드도 새로 났을 가능성이 큽니다. KOSIS 코드는")
            print("     체계가 달라 그대로 못 씁니다 — discover-sigungu 의")
            print("     --find-new-sido 로 실제 코드를 찾아야 합니다.")
        elif len(rows) != len(SIDO_PREFIX):
            print(f"  ⚠ 개수가 다릅니다. 개편 여부를 확인하세요.")
    except Exception as exc:                          # noqa: BLE001
        print(f"  실패: {exc}")

    for term in args.terms.split(","):
        term = term.strip()
        if not term:
            continue
        print()
        print("=" * 70)
        print(f"'{term}' 검색")
        print("=" * 70)
        try:
            rows = kosis.search(term)
        except Exception as exc:                      # noqa: BLE001
            print(f"  실패: {exc}")
            continue
        print(f"  {len(rows)}건")
        for r in rows[:args.top]:
            org = r.get("ORG_ID", "")
            tbl = r.get("TBL_ID", "")
            nm = str(r.get("TBL_NM", ""))[:60]
            span = f"{r.get('STRT_PRD_DE','')}~{r.get('END_PRD_DE','')}"
            path = str(r.get("MT_ATITLE", ""))[:40]
            print(f"    orgId={org:5s} tblId={tbl:20s} {span:12s} {nm}")
            print(f"        {path}")


def cmd_kosis_diagnose(args):
    """KOSIS 가 실제로 어떻게 답하는지 사실만 확인한다 (추측 금지)."""
    from .collect import kosis
    kosis.diagnose()


def cmd_kosis_browse(args):
    """KOSIS 목록을 훑어 시군구 인구·사업체 통계표를 찾는다.

    orgId·tblId 를 추측해서 적어 넣으면 틀린 표의 숫자를 받아놓고도 맞는 줄
    압니다. 목록에서 찾아 눈으로 확인한 뒤에 씁니다.
    """
    from .collect import kosis

    vw = kosis.VIEWS.get(args.view, args.view)
    print(f"KOSIS 목록 훑기 — 뷰 {args.view}({vw}) · 시작 {args.parent} · 깊이 {args.depth}")
    print(f"  ★ 표시는 이름에 {kosis.WANTED} 가 들어간 것입니다\n")
    tables = kosis.walk(str(args.parent), vw, depth=args.depth)
    print(f"\n찾은 표 {len(tables)}개")
    hits = [t for t in tables
            if any(w in kosis._label(t) for w in kosis.WANTED)]
    if hits:
        print(f"\n이름이 맞는 것 {len(hits)}개 — 여기서 고르시면 됩니다:")
        for t in hits:
            print(f"  {kosis._label(t)}")
            print(f"      {kosis._ident(t)}")
    else:
        print("\n이름이 맞는 표가 없습니다. --parent 를 바꾸거나 --view 를 "
              "지방지표_지역(MT_GTITLE02) 로 해보세요.")


def cmd_fetch_urban_dev(args):
    """전국도시개발사업정보 표준데이터를 받아 zones_housing.csv 로 저장한다.

    받은 칸을 그대로 저장한다. 우리 이름으로 접는 일은 load-h3 가 한다 —
    두 군데서 하면 어긋났을 때 어느 쪽이 틀렸는지 알 수 없다.
    """
    from .collect import urban_dev

    df = urban_dev.fetch_all(max_pages=args.max_pages)
    if df.empty:
        sys.exit("받은 자료가 없습니다. 위 로그의 응답 모양을 확인하세요.")
    out = ROOT / "data" / "raw" / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n{out}  {len(df):,}행 · {len(df.columns)}칸")
    # 지정일로 쓸 만한 칸이 실제로 왔는지 여기서 바로 말한다. 없으면
    # 이벤트로 못 쓰므로, 파일을 받아놓고 몇 주 뒤에 알게 되면 안 된다.
    from .collect.h3_files import ZONE_COLS, _pick

    got = _pick(df, ZONE_COLS["designated_date"])
    if got:
        print(f"  ✅ 지정일로 쓸 칸: {got}")
    else:
        print(f"  ⚠ 지정일로 쓸 칸을 못 찾았습니다.")
        print(f"     찾는 이름: {ZONE_COLS['designated_date']}")
        print(f"     받은 칸:   {list(df.columns)}")
        print(f"     날짜처럼 보이는 칸이 있으면 그 이름을 후보에 넣으면 됩니다.")


def cmd_load_h3(args):
    """가설3 자료 적재 — 산업단지·택지지구 지정, 시군구 인구·사업체."""
    zones = h3_files.load_zones(args.zones)
    region = h3_files.load_region(args.region)
    if zones.empty and region.empty:
        sys.exit("실을 파일이 없습니다. data/raw/zones_*.csv 또는 region_*.csv 를 "
                 "넣으세요 (docs/hypothesis-3-data.md 참고).")
    with db.connect() as con:
        nz = db.upsert(con, "zone_event", zones) if len(zones) else 0
        nr = db.upsert(con, "region_year", region) if len(region) else 0
        if nz:
            # 좌표가 있는 개발사건만 거래와 이어 붙인다. 좌표 없는 건을
            # 시군구 중심으로 대충 찍으면 반경 밴드가 통째로 거짓이 된다.
            zz = con.execute(
                "SELECT zone_id, lat, lon FROM zone_event WHERE lat IS NOT NULL"
            ).fetchdf()
            trades = con.execute(
                "SELECT trade_id, lat, lon FROM trade WHERE lat IS NOT NULL").fetchdf()
            if len(zz) and len(trades):
                links = spatial.link_trades_to_tollgates(
                    trades, zz.rename(columns={"zone_id": "tollgate_id"}))
                links = links.rename(columns={"tollgate_id": "zone_id"})
                con.execute("DELETE FROM trade_zone_link")
                n = db.upsert(con, "trade_zone_link", links)
                print(f"거래 ↔ 개발사건 {n:,}쌍 연결")
            else:
                print("좌표 있는 개발사건이 없어 공간 조인을 건너뜁니다.")
    print(f"개발사건 {nz:,}건 · 지역지표 {nr:,}행 저장")


def cmd_hypotheses(args):
    """세 가설을 한 자리에서 판정한다 (H1 개통 · H2 교통량 · H3 인구·산단)."""
    from .analyze import events, hypotheses
    path = PROCESSED / "panel.parquet"
    if not path.exists():
        sys.exit("panel.parquet 이 없습니다. 먼저 `panel` 을 실행하세요.")
    panel = pd.read_parquet(path)

    with db.connect(read_only=True) as con:
        trades = con.execute("SELECT * FROM trade WHERE lat IS NOT NULL").fetchdf()
        links = con.execute("SELECT * FROM trade_tollgate_link").fetchdf()
        region = con.execute("SELECT * FROM region_year").fetchdf()
        zones = con.execute("SELECT * FROM zone_event").fetchdf()
        zlinks = con.execute("""
            SELECT l.tollgate_id, z.zone_id
            FROM trade_zone_link z
            JOIN trade_tollgate_link l USING (trade_id)
            WHERE l.is_nearest
            GROUP BY 1, 2
        """).fetchdf()

    # 개통 이벤트 표본은 events 가 만든 것을 그대로 쓴다. 두 곳에서 따로
    # 만들면 같은 가설에 다른 표본을 쓰게 된다.
    event_df, pre_ok = None, None
    if not trades.empty and not links.empty:
        kept = trades[~trades["is_share_deal"].fillna(False)
                      & ~trades["is_cancelled"].fillna(False)]
        priced = pn.hedonic_adjust(pn.filter_land_use(kept))
        event_df = events.build(priced, links, kind=args.kind)
        if len(event_df) and event_df["treated"].nunique() > 1:
            try:
                es = events.event_study(event_df)
                pre = [(es.pvalues[n]) for n in es.params.index
                       if n.startswith("treated:C(rel") and "T.-" in n]
                pre_ok = None if not pre else not any(p < 0.1 for p in pre)
            except Exception as exc:               # noqa: BLE001
                print(f"  사전추세 검정 실패: {exc}")

    years = sorted(int(y) for y in panel["year"].dropna().unique())
    pressure = hypotheses.zone_pressure(zones, zlinks, years)

    verdicts = hypotheses.report(
        panel, event_df, region, pressure,
        volume_col=f"volume_{args.volume}", kind=args.kind, pre_trend_ok=pre_ok)
    verdicts.to_csv(PROCESSED / "verdicts.csv", index=False)


def cmd_gaps(args):
    """영업소가 어느 단계에서 새는지 — 패널이 얇을 때 원인을 가른다."""
    from .analyze import gaps
    with db.connect(read_only=True) as con:
        gaps.report(con)


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


def cmd_progress(args):
    """전국 수집이 전체의 몇 %까지 왔는지. 며칠에 걸쳐 받으므로 이게 있어야
    몇 번을 더 돌려야 하는지 알 수 있다."""
    months = _months(args.start, args.end)
    try:
        targets = rg.sigungu_codes(args.region.split(",")) if args.region else {}
    except KeyError as exc:
        print(f"  {exc}")
        return
    kinds = args.kind.split(",") if args.kind else settings()["trade_kinds"]
    planned = len(kinds) * len(targets) * len(months)

    with db.connect(read_only=False) as con:
        con.execute(db.COLLECT_LOG)
        rows = con.execute("""
            SELECT kind, count(*) AS 완료,
                   count(*) FILTER (WHERE status = 'ok') AS 자료있음,
                   sum(n_rows) AS 거래건수
            FROM collect_log WHERE status <> 'error'
            GROUP BY kind ORDER BY kind
        """).fetchdf()
        errs = con.execute(
            "SELECT count(*) FROM collect_log WHERE status = 'error'").fetchone()[0]

    print(f"\n=== 수집 진행률 ===")
    print(f"  대상: {len(kinds)}종 × 시군구 {len(targets):,} × {len(months):,}개월"
          f" = {planned:,} 셀")
    if rows.empty:
        print("  아직 받은 것이 없습니다.")
        return
    print(rows.to_string(index=False))
    done = int(rows["완료"].sum())
    pct = done / planned if planned else 0
    print(f"  완료 {done:,} / {planned:,} ({pct:.1%})"
          + (f" · 재시도 대기 {errs:,}" if errs else ""))
    if planned > done:
        left = planned - done
        print(f"  남은 {left:,}셀 — 한 번에 {args.per_run:,}셀씩이면"
              f" {-(-left // max(1, args.per_run))}번 더 돌리면 됩니다.")


def cmd_doctor(args):
    from .doctor import run
    raise SystemExit(run())


def main(argv=None):
    parser = argparse.ArgumentParser(prog="redt", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="수집 전 점검 — 키·네트워크·저장경로").set_defaults(func=cmd_doctor)

    p = sub.add_parser("progress", help="전국 수집이 전체의 몇 %까지 왔는지")
    p.add_argument("--start", default="2006-01")
    p.add_argument("--end", default="2025-12")
    p.add_argument("--region", default="nationwide")
    p.add_argument("--kind", default="land,factory")
    p.add_argument("--per-run", type=int, default=35000,
                   help="한 번 실행에서 처리하는 셀 수 (남은 횟수 계산용)")
    p.set_defaults(func=cmd_progress)

    p = sub.add_parser("tollgates", help="영업소 마스터 수집")
    p.add_argument("--path", help="API 대신 사용할 CSV 경로")
    p.set_defaults(func=cmd_tollgates)

    p = sub.add_parser("fill-tollgates",
                       help="마스터에 없는 영업소(민자 등) 좌표를 이름으로 보충")
    p.add_argument("--limit", type=int, help="앞에서 N개만 (시험용)")
    p.add_argument("--skip-regions", action="store_true",
                   help="시도·시군구 역지오코딩을 건너뜁니다")
    p.set_defaults(func=cmd_fill_tollgates)

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
    sub.add_parser("probe-landprice",
                   help="표준지공시지가 API 탐침 — 좌표·연도·용도지역이 오는지"
                   ).set_defaults(func=cmd_probe_landprice)

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
    # 6은 브라우저가 한 호스트에 여는 연결 수와 같은 수준이라 공공 API 에
    # 무리가 아니면서 대기 시간을 여섯 배 가까이 줄인다. 차단당하면 낮추면 된다.
    p.add_argument("--max-cells", type=int, default=0,
                   help="이번 실행에서 처리할 최대 셀 수 (0=제한없음). "
                        "하루 API 한도에 맞춰 나눠 돌 때 씁니다")
    p.add_argument("--workers", type=int, default=6,
                   help="동시 요청 수 (기본 6). 차단당하면 낮추세요")
    p.set_defaults(func=cmd_trades)

    p = sub.add_parser("find-new-sido",
                       help="개편으로 새로 난 시도 접두사 찾기 (싼 탐침)")
    p.add_argument("--lo", default="10")
    p.add_argument("--hi", default="69")
    p.add_argument("--probe-ymd", default="202403")
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(func=cmd_find_new_sido)

    p = sub.add_parser("discover-sigungu",
                       help="전국 시군구 코드를 훑어서 찾는다 (한 번만)")
    p.add_argument("--sido", help="시도 접두 2자리, 쉼표구분 (기본: 전국 18개)")
    p.add_argument("--probe-ymd", default="202403")
    p.add_argument("--extra-ymd", default="202310,202206",
                   help="거래가 드문 군을 놓치지 않으려고 더 보는 달")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--refresh", action="store_true", help="이미 찾아둔 것을 무시하고 다시")
    p.set_defaults(func=cmd_discover_sigungu)

    p = sub.add_parser("regions", help="파일럿 권역 / 시군구 코드 확인")
    p.add_argument("--verify", action="store_true", help="각 코드로 시험 조회 (API 키 필요)")
    p.add_argument("--probe-ymd", default="202401", help="검증에 쓸 계약년월 YYYYMM")
    p.set_defaults(func=cmd_regions)

    p = sub.add_parser(
        "geocode-repair",
        help="좌표 없이 캐시에 박힌 항목을 지워 다시 물어보게 한다")
    p.set_defaults(func=cmd_geocode_repair)

    p = sub.add_parser("geocode-staged",
                       help="2단계 지오코딩 (법정동 먼저 → 영업소 반경 안만 지번)")
    p.add_argument("--umd-limit", type=int, default=None,
                   help="이번 실행에서 법정동 중심점을 몇 개까지 부를지")
    p.add_argument("--limit", type=int, default=4000,
                   help="이번 실행에서 지번 단위를 몇 건까지 부를지 (일일 한도)")
    p.add_argument("--all", action="store_true",
                   help="용도지역 필터 없이 전부")
    p.set_defaults(func=cmd_geocode_staged)

    p = sub.add_parser("geocode", help="지번 → 좌표")
    p.add_argument("--limit", type=int, help="이번 실행에서 신규 호출 상한")
    p.add_argument("--all", action="store_true",
                   help="용도지역 필터를 무시하고 전부 지오코딩")
    p.set_defaults(func=cmd_geocode)

    sub.add_parser("link", help="거래-영업소 공간 조인").set_defaults(func=cmd_link)
    sub.add_parser("panel", help="분석 패널 생성").set_defaults(func=cmd_panel)

    p = sub.add_parser("analyze", help="상관·탄력성 분석")
    p.add_argument("--volume", default="total", choices=["total", "freight", "passenger", "mid"])
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("sweep-codes", help="시군구 코드 범위를 훑어 유효한 것 찾기")
    p.add_argument("--prefix", required=True, help="앞 3자리 (예: 415)")
    p.add_argument("--probe-ymd", default="202506")
    p.set_defaults(func=cmd_sweep_codes)

    p = sub.add_parser("load-traffic",
                       help="정리해둔 연간 교통량 CSV 를 DB 에 싣기")
    p.add_argument("--pattern", default="tcs_annual_*.csv",
                   help="data/raw 안에서 찾을 파일 패턴")
    p.set_defaults(func=cmd_load_traffic)

    p = sub.add_parser("rank", help="지시3 — IC 교통량 순위 대비 주변 지가 (횡단 비교)")
    p.add_argument("--year", type=int, help="기준연도 (기본: 자료가 있는 최신 연도)")
    p.add_argument("--kind", default="land", choices=["land", "factory"])
    p.add_argument("--volume", default="total",
                   choices=["total", "freight", "passenger", "mid"])
    p.add_argument("--top", type=int, default=25, help="표에 찍을 상위 개수")
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("events", help="지시2 — 신규 개통 영업소 전후 지가 (이중차분)")
    p.add_argument("--kind", default="land", choices=["land", "factory"])
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("kosis-fetch", help="확인된 KOSIS 표 받기 (→ region_*.csv)")
    p.add_argument("--table", default="population",
                   help="population · households")
    p.add_argument("--start", default="2006")
    p.add_argument("--end", default="2025")
    p.add_argument("--out", default="region_population.csv")
    p.set_defaults(func=cmd_kosis_fetch)

    p = sub.add_parser("kosis-find",
                       help="이름으로 통계표 찾기 + 현재 시도 코드 확인")
    p.add_argument("--terms", default="주민등록인구,전국사업체조사")
    p.add_argument("--top", type=int, default=15)
    p.set_defaults(func=cmd_kosis_find)

    p = sub.add_parser("kosis-diagnose",
                       help="KOSIS 응답 진단 (parentId 가 먹히는지·검색이 되는지)")
    p.set_defaults(func=cmd_kosis_diagnose)

    p = sub.add_parser("kosis-browse",
                       help="KOSIS 목록 훑기 (인구·사업체 통계표 ID 찾기)")
    p.add_argument("--parent", default="A",
                   help="시작 목록 ID. 모르면 A 부터 시작해 보세요.")
    p.add_argument("--view", default="주제별",
                   help="주제별 · 기관별 · 지방지표_주제 · 지방지표_지역, 또는 코드 직접")
    p.add_argument("--depth", type=int, default=2)
    p.set_defaults(func=cmd_kosis_browse)

    p = sub.add_parser("fetch-urban-dev",
                       help="전국도시개발사업정보 표준데이터 받기 (→ zones_housing.csv)")
    p.add_argument("--out", default="zones_housing.csv")
    p.add_argument("--max-pages", type=int, default=60)
    p.set_defaults(func=cmd_fetch_urban_dev)

    p = sub.add_parser("load-h3", help="가설3 자료 적재 (산업단지·택지·인구 CSV)")
    p.add_argument("--zones", default="zones_*.*")
    p.add_argument("--region", default="region_*.*")
    p.set_defaults(func=cmd_load_h3)

    p = sub.add_parser("hypotheses",
                       help="세 가설 판정 (H1 개통 · H2 교통량 · H3 인구·산단)")
    p.add_argument("--kind", default="land", choices=["land", "factory"])
    p.add_argument("--volume", default="total",
                   choices=["total", "freight", "passenger", "mid"])
    p.set_defaults(func=cmd_hypotheses)

    p = sub.add_parser("score", help="영업소별 투자 스크리닝 스코어")
    p.add_argument("--band", default=None,
                   help="기본값은 settings.yaml 의 spatial.primary_band")
    p.add_argument("--volume", default="freight",
                   choices=["total", "freight", "passenger", "mid"])
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("export-web", help="웹 화면용 JSON 생성")
    p.add_argument("--band", default=None,
                   help="기본값은 settings.yaml 의 spatial.primary_band")
    p.add_argument("--volume", default="freight",
                   choices=["total", "freight", "passenger", "mid"])
    p.set_defaults(func=cmd_export_web)

    p = sub.add_parser("serve-api", help="매물 API + 화면 서버")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_serve_api)

    sub.add_parser("gaps",
                   help="영업소 누락 진단 — 명단·좌표·거래 중 어디서 새는지"
                   ).set_defaults(func=cmd_gaps)
    sub.add_parser("status", help="적재 현황").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
