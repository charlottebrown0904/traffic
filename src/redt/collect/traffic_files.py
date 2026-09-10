"""포털에서 받아 정리해둔 연간 교통량 CSV 를 DB 에 싣는다.

실시간 API 는 과거 연도를 주지 않는다(docs/traffic-api-findings.md). 그래서
포털의 일별 원본을 받아 scripts/convert_tcs_daily.py 로 접어두었는데, 그것을
traffic 테이블에 넣는 단계가 없어서 패널이 비어 있었다. 수집은 다 됐는데
'패널을 만들 재료가 부족합니다' 만 나왔다.

영업소 코드는 양쪽 표기가 달라 redt.ids 로 접어서 맞춘다. 맞춘 뒤에도
영업소 마스터와 짝이 안 맞는 비율이 높으면 크게 알린다 — 조인이 어긋난 채
분석까지 흘러가면 '표본이 없는 것' 과 구분할 수 없다.
"""
from __future__ import annotations

import calendar
from pathlib import Path

import pandas as pd

from ..config import RAW
from ..ids import canon_series

SOURCE = "tcs"


def observed_days() -> pd.DataFrame:
    """영업소×연도별로 실제 관측된 날 수.

    패널은 연 합계가 아니라 **일평균**을 쓴다. 관측일수가 해마다 다르면
    교통량이 아니라 집계 범위가 변한 것을 β 로 잡아내기 때문이다. 그래서
    월별 파일에서 그 해에 실제로 자료가 있는 달을 세어 날 수로 환산한다.

    연중 개통한 영업소는 그 해 관측 달이 적으므로 여기서 자동으로 걸러진다
    — 12월 한 달만 있는 영업소를 365일로 나누면 교통량이 1/12 로 보인다.

    **다만 개통한 달 자체는 이 함수가 못 바로잡는다.** 자료에 나타난 달은
    무조건 온전한 달(28~31일)로 세기 때문이다. 그 문제는 daily_average()
    가 다룬다 — 그쪽 주석에 실측을 적어 두었다.
    """
    cells = monthly_cells()
    if cells.empty:
        return pd.DataFrame(columns=["tollgate_id", "year", "days"])
    per_month = cells.drop_duplicates(["tollgate_id", "year", "month"])
    return (per_month.groupby(["tollgate_id", "year"], as_index=False)["days"].sum())


def monthly_cells() -> pd.DataFrame:
    """월별 원본을 영업소 × 연월 × 차종 으로 편다.

    연간 파일과 **정확히 같은 값**이다 — 52,674 칸을 맞춰 봤더니 차이가
    한 칸도 없었다 (2026-09-10 실측). 그래서 일평균은 월별에서 내고 연
    합계는 연간 파일에서 그대로 두어도 어긋나지 않는다.
    """
    frames = []
    for path in sorted(Path(RAW).glob("tcs_monthly_*.csv")):
        df = pd.read_csv(path, encoding="utf-8-sig",
                         usecols=["영업소코드", "연월", "차종", "교통량"])
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["tollgate_id", "ym", "year", "month",
                                     "vehicle_type", "volume", "days"])
    raw = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "tollgate_id": canon_series(raw["영업소코드"]),
        "ym": raw["연월"].astype(str),
        "vehicle_type": pd.to_numeric(
            raw["차종"].astype(str).str.extract(r"(\d+)")[0], errors="coerce"),
        "volume": pd.to_numeric(raw["교통량"], errors="coerce"),
    })
    out = out.dropna(subset=["tollgate_id", "vehicle_type", "volume"])
    out["year"] = out["ym"].str[:4].astype(int)
    out["month"] = out["ym"].str[-2:].astype(int)
    out["vehicle_type"] = out["vehicle_type"].astype(int)
    out["days"] = [calendar.monthrange(y, m)[1]
                   for y, m in zip(out["year"], out["month"])]
    return out


# 꼬리 달이 잘렸다고 볼 기준. 전국 일평균이 앞선 달들의 이만큼도 안 되면
# 그 달은 아직 다 안 채워진 것으로 본다.
TAIL_SHORT = 0.6


def _months_to_drop(cells: pd.DataFrame) -> tuple[set, str | None]:
    """일평균을 낼 때 빼야 할 (영업소, 연월) 과 잘린 꼬리 달.

    ## 왜 개통한 달을 빼는가 (2026-09-10 실측)

    월별 파일은 '그 달에 자료가 있다' 만 말하고 **며칠부터 있었는지는
    말하지 않는다.** 그래서 6월 30일에 문을 연 영업소도 6월을 30일로
    세게 되고, 하루치 통행량이 30일로 나뉜다.

    실측이 이것을 그대로 보여 줬다. 첫 달이 자료 시작(2003-01)이 아닌
    영업소 253곳 중 **185곳(73%)** 의 첫 달 일평균이 둘째 달의 절반에도
    못 미쳤고, 75곳은 10% 에도 못 미쳤다.

        북용인   2024-12      7.2 →  15,196.9 대/일   첫 달 총 224대
        인제     2017-06     49.7 →   4,285.5 대/일   첫 달 총 1,491대
        서양양   2017-06     13.8 →   1,002.3 대/일   첫 달 총 415대

    인제·서양양은 서울양양고속도로가 열린 달이다. 6월 한 달치가 아니라
    **개통 당일치**가 들어 있는 것이다.

    ## 왜 날 수를 추정하지 않는가

    '첫 달 총 ÷ 둘째 달 일평균' 으로 며칠인지 되짚어 봤더니 인제는
    0.35일, 북용인은 0.015일이 나왔다. 하루도 안 된다 — 개통 당일 몇
    시간치이거나 시운전 기록이다. 이런 값으로 나눗셈의 분모를 만들면
    잘못을 다른 잘못으로 덮는 것이 된다.

    **그래서 추정하지 않고 뺀다.** 잴 수 없는 달을 빼고 나머지로 낸다.
    12월에 문을 연 영업소는 그 해 일평균이 아예 안 나오는데, 그것이
    사실이다 — 없는 값을 지어내는 것보다 낫다. 연 합계(volume)는
    그대로 두므로 '그 해에 몇 대가 지났나' 는 남는다.

    닫는 달도 같다. 다만 **자료가 여기서 끝난 것**과 영업소가 문을 닫은
    것은 다르므로, 자료의 마지막 달까지 살아 있는 영업소는 안 건드린다.
    """
    if cells.empty:
        return set(), None
    first_ym = cells["ym"].min()
    last_ym = cells["ym"].max()

    # 꼬리 달이 잘렸는가. 자료를 달 중간에 받으면 마지막 달이 모두에게
    # 짧다 — 그러면 그 해 전체가 조용히 내려앉는다.
    per_ym = (cells.groupby("ym", as_index=False)
              .agg(volume=("volume", "sum"), days=("days", "first")))
    per_ym["per_day"] = per_ym["volume"] / per_ym["days"]
    tail = None
    if len(per_ym) >= 4:
        recent = per_ym.sort_values("ym")
        edge = recent.iloc[-1]
        base = recent.iloc[-4:-1]["per_day"].median()
        if base > 0 and edge["per_day"] < base * TAIL_SHORT:
            tail = str(edge["ym"])

    span = cells.groupby("tollgate_id")["ym"].agg(["min", "max"])
    drop = set()
    for tid, row in span.iterrows():
        # 자료 지평의 첫 달은 개통달이 아니다 — 그전부터 있던 영업소다.
        if row["min"] != first_ym:
            drop.add((tid, row["min"]))
        # 자료 끝까지 살아 있으면 닫은 것이 아니다.
        if row["max"] != last_ym:
            drop.add((tid, row["max"]))
    if tail:
        for tid in span.index:
            drop.add((tid, tail))
    return drop, tail


def daily_average() -> pd.DataFrame:
    """영업소 × 연도 × 차종 일평균. **잴 수 있는 달로만** 낸다.

    빠지는 달은 _months_to_drop() 이 정한다 (개통달·폐쇄달·잘린 꼬리달).
    남는 달이 없으면 그 칸은 빠진다 — avg_daily 가 NULL 이 되고,
    webexport 가 'avg_daily IS NOT NULL' 로 거르므로 화면에는 그 해가
    없는 것으로 나온다. **0 으로 나오지 않는다**: 0 은 '차가 안 다녔다'
    는 뜻인데 사실은 '못 쟀다' 이고, 둘을 섞으면 신설 IC 가 통행량
    최하위로 지도에 박힌다.
    """
    cells = monthly_cells()
    if cells.empty:
        return pd.DataFrame(columns=["tollgate_id", "year", "vehicle_type",
                                     "avg_daily", "obs_days"])
    drop, tail = _months_to_drop(cells)
    if tail:
        print(f"  마지막 달 {tail} 이 아직 다 안 채워진 것으로 보여 뺍니다 "
              "(그대로 두면 그 해 전체가 내려앉습니다)")
    keep = cells[~pd.Series(list(zip(cells["tollgate_id"], cells["ym"])),
                            index=cells.index).isin(drop)]
    lost = cells["ym"].count() - keep["ym"].count()
    if lost:
        print(f"  개통·폐쇄한 달 {len(drop):,}칸을 일평균에서 뺍니다 "
              "(며칠부터 열었는지 월별 자료가 말해주지 않습니다)")
    agg = keep.groupby(["tollgate_id", "year", "vehicle_type"], as_index=False).agg(
        vol=("volume", "sum"), obs_days=("days", "sum"))
    agg = agg[agg["obs_days"] > 0]
    agg["avg_daily"] = agg["vol"] / agg["obs_days"]
    return agg.drop(columns=["vol"])


def load_files(pattern: str = "tcs_annual_*.csv") -> pd.DataFrame:
    """data/raw 의 연간 CSV 를 모아 traffic 테이블 모양으로 만든다."""
    frames = []
    for path in sorted(Path(RAW).glob(pattern)):
        if path.name.startswith("legacy_"):
            continue                       # 출처가 다른 파일 (PROVENANCE.md)
        df = pd.read_csv(path, encoding="utf-8-sig")
        need = {"영업소코드", "연도", "차종", "교통량"}
        missing = need - set(df.columns)
        if missing:
            print(f"  ⚠ {path.name}: 컬럼 없음 {sorted(missing)} — 건너뜁니다")
            continue
        frames.append(df)
        print(f"  {path.name}  {len(df):,}행")

    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "tollgate_id": canon_series(raw["영업소코드"]),
        "year": pd.to_numeric(raw["연도"], errors="coerce"),
        # '1종' → 1. 숫자를 못 읽으면 버린다 — 0(전체)으로 두면 차종별 합계와
        # 겹쳐 교통량이 두 배가 된다.
        "vehicle_type": pd.to_numeric(
            raw["차종"].astype(str).str.extract(r"(\d+)")[0], errors="coerce"),
        "direction": "all",
        "volume": pd.to_numeric(raw["교통량"], errors="coerce"),
        "source": SOURCE,
        "unit_type": "tollgate",
        "match_km": 0.0,
    })

    before = len(out)
    out = out.dropna(subset=["tollgate_id", "year", "vehicle_type", "volume"])
    if len(out) < before:
        print(f"  ⚠ 값을 읽지 못한 {before - len(out):,}행 제외")
    out["year"] = out["year"].astype(int)
    out["vehicle_type"] = out["vehicle_type"].astype(int)
    out["volume"] = out["volume"].astype("int64")

    # 일평균은 **월별 파일에서** 낸다 (2026-09-10). 연 합계를 날 수로
    # 나누는 길은 개통한 달을 온전한 달로 세어, 개통 당일치가 30일로
    # 나뉘었다 — 인제 2017년이 49.7대/일, 다음 달이 4,285대/일이었다.
    # daily_average() 가 잴 수 없는 달을 빼고 낸다.
    #
    # volume(연 합계)은 손대지 않는다. 그것은 '그 해에 몇 대가 지났나'
    # 라는 사실이고, 개통 첫 달이라고 해서 틀린 값이 아니다.
    avg = daily_average()
    if avg.empty:
        print("  ⚠ 월별 파일이 없어 일평균을 낼 수 없습니다. 365일로 나눕니다 "
              "— 연중 개통한 영업소가 과소평가됩니다.")
        out["avg_daily"] = out["volume"] / 365.0
        return out

    out = out.merge(avg, on=["tollgate_id", "year", "vehicle_type"], how="left")
    # **못 잰 칸은 비워 둔다.** 0 으로 채우면 '차가 안 다녔다' 가 되고,
    # 그러면 이제 막 열린 IC 가 통행량 최하위로 지도에 박힌다.
    blank = out["avg_daily"].isna().sum()
    if blank:
        gates = out.loc[out["avg_daily"].isna(), "tollgate_id"].nunique()
        print(f"  일평균을 못 낸 {blank:,}칸 (영업소 {gates}곳) — 그 해에 잴 수 "
              "있는 달이 없습니다. 연 합계는 그대로 남습니다.")
    short = avg[avg["obs_days"] < 350]
    if len(short):
        print(f"  잰 날이 350일 미만인 영업소×연도×차종 {len(short):,}칸 "
              "(연중 개통·폐쇄. 그 달을 빼고 나머지로 냈습니다)")
    return out.drop(columns=["obs_days"])


def report_match(traffic: pd.DataFrame, tollgate_ids: set[str]) -> float:
    """영업소 마스터와 얼마나 짝이 맞는지. 낮으면 조인이 어긋난 것이다."""
    codes = set(traffic["tollgate_id"].unique())
    if not codes:
        return 0.0
    matched = codes & tollgate_ids
    rate = len(matched) / len(codes)
    print(f"  영업소 짝맞춤 {len(matched)}/{len(codes)} ({rate:.0%})")
    if rate < 0.5:
        missing = sorted(codes - tollgate_ids)[:10]
        print(f"  ⚠ 절반도 못 맞췄습니다. 마스터에 없는 코드 예: {missing}")
        print("    영업소 마스터가 일부만 받아졌거나(P2-6a) 코드 표기가 다릅니다."
              " 이대로 두면 패널이 조용히 비거나 표본이 크게 줄어듭니다.")
    return rate
