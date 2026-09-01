"""도로공사 포털의 '영업소별 일별 교통량' 원본을 연도별 집계로 바꾼다.

포털에서 받는 파일은 확장자가 .zip 이지만 실제로는 **gzip** 이고, 안에는
cp949 로 쓰인 CSV 가 하나 들어 있다. 한 달치가 5만 행쯤 된다.

  집계일자 · 영업소코드 · 입출구구분코드 · TCS하이패스구분코드
  · 고속도로운영기관구분코드 · 영업형태구분코드 · 1종~6종교통량 · 총교통량

집계 규칙 — 입출구·TCS/하이패스·기관·영업형태를 **모두 합친다**.
2026-01 서울(101) 1종을 이 방식으로 12개월 환산하면 58.5M 이 나오는데,
기존 연간 파일의 2025년 값이 56.6M 이다. 입구만/출구만 합치면 절반인
29M 이 되어 전혀 맞지 않는다. 연간 파일이 양방향 합계라는 근거다.

총교통량 컬럼은 싣지 않는다. 차종 합과 중복이라 그대로 두면 두 배가 된다.

  python scripts/convert_tcs_daily.py data/raw/ex/*.zip -o data/raw/tcs_annual.csv
"""
from __future__ import annotations

import argparse
import gzip
import io
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

CLASSES = [f"{i}종교통량" for i in range(1, 7)]
# 영업소명은 일별 원본에 없다. 대표님이 직접 합치신 2025 엑셀에만 이름이
# 들어 있어 그것만 이름 대조에 쓴다. 교통량 값은 쓰지 않는다 —
# 다른 해와 집계가 어긋나 있다 (data/raw/PROVENANCE.md).
NAME_SOURCE = Path("data/raw/legacy_tcs_annual_2025_from_xlsx.csv")


# 2020년 이전 파일에는 머리글 줄이 없다. 컬럼 순서는 같으므로 이름만 얹는다.
COLUMNS = ["집계일자", "영업소코드", "입출구구분코드", "TCS하이패스구분코드",
           "고속도로운영기관구분코드", "영업형태구분코드",
           *[f"{i}종교통량" for i in range(1, 7)], "총교통량"]


def read_one(path: Path) -> pd.DataFrame:
    """gzip(.zip 로 위장) 이든 맨 csv 든 읽는다.

    파일마다 생김새가 다르다. 2021년 이후는 따옴표 친 머리글이 있고,
    2020년 이전은 머리글 없이 값부터 시작한다. 머리글 없는 파일을 그냥
    읽으면 첫 줄(실제 데이터)이 컬럼 이름이 되어 하루치가 조용히 사라지고,
    '집계일자' 를 찾지 못해 뒤에서 KeyError 가 난다.
    """
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    head = raw[:200].decode("cp949", errors="replace")
    has_header = "집계일자" in head

    if has_header:
        df = pd.read_csv(io.BytesIO(raw), encoding="cp949")
        df.columns = [c.strip() for c in df.columns]
    else:
        df = pd.read_csv(io.BytesIO(raw), encoding="cp949", header=None)
        # 줄 끝 쉼표 때문에 빈 열이 하나 더 붙는다
        df = df.iloc[:, :len(COLUMNS)]
        if df.shape[1] != len(COLUMNS):
            sys.exit(f"{path.name}: 열이 {df.shape[1]}개입니다 "
                     f"({len(COLUMNS)}개를 기대). 형식이 또 다릅니다.")
        df.columns = COLUMNS
    return df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]


def parse_dates(col: pd.Series) -> pd.Series:
    """집계일자를 읽는다. 파일마다 형식이 다르다.

    2023-01 은 "20230101", 2023-02 부터는 "2023-02-01" 이었다. 형식을 지정하지
    않고 to_datetime 에 넘기면 판다스가 20230101 을 **정수**로 보고 'epoch 이후
    나노초' 로 해석해 1970-01-01 을 돌려준다. 오류가 아니라 조용히 틀린 값이
    나오므로 errors="coerce" 로도 잡히지 않는다. 실제로 2023년 1월 한 달이
    통째로 1970년으로 넘어가 있었다.

    그래서 반드시 문자열로 바꾼 뒤, 형식을 명시해 두 가지를 차례로 시도한다.
    """
    raw = col.astype(str).str.strip()
    out = pd.to_datetime(raw, format="%Y-%m-%d", errors="coerce")
    out = out.fillna(pd.to_datetime(raw, format="%Y%m%d", errors="coerce"))
    return out


def names() -> dict[int, str]:
    """영업소명은 일별 파일에 없다. 기존 연간 파일에서 가져온다."""
    if not NAME_SOURCE.exists():
        return {}
    ann = pd.read_csv(NAME_SOURCE, encoding="utf-8-sig")
    return dict(zip(ann["영업소코드"].astype(int), ann["영업소명"].astype(str)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--monthly-out", help="생략하면 out 의 annual 을 monthly 로 바꿔 씁니다")
    args = ap.parse_args()

    frames, months = [], defaultdict(set)
    for p in sorted(Path(f) for f in args.files):
        df = read_one(p)
        df["집계일자"] = parse_dates(df["집계일자"])
        bad = df["집계일자"].isna().sum()
        if bad:
            print(f"  ⚠ {p.name}: 날짜를 읽지 못한 {bad:,}행을 버립니다")
            df = df.dropna(subset=["집계일자"])
        df["연도"] = df["집계일자"].dt.year
        # 형식을 잘못 읽으면 1970년 같은 값이 조용히 섞인다. 여기서 멈춘다 —
        # 이런 행이 집계까지 흘러가면 한 해가 통째로 사라진 줄도 모르게 된다.
        odd = df.loc[~df["연도"].between(1990, 2100), "연도"].unique()
        if len(odd):
            sys.exit(f"{p.name}: 말이 안 되는 연도 {sorted(int(y) for y in odd)} 가 "
                     f"나왔습니다. 날짜 형식을 확인하세요.")
        for y, m in df.groupby("연도")["집계일자"]:
            months[int(y)] |= set(m.dt.month.unique())
        df["영업소코드"] = pd.to_numeric(
            df["영업소코드"].astype(str).str.strip(), errors="coerce")
        df = df.dropna(subset=["영업소코드"])
        for c in CLASSES:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        df["연월"] = df["집계일자"].dt.strftime("%Y-%m")
        frames.append(df[["연도", "연월", "영업소코드", *CLASSES]])
        print(f"  {p.name}  {len(df):,}행")

    if not frames:
        print("읽은 파일이 없습니다.")
        return 1

    allrows = pd.concat(frames)
    name_map = names()

    def fold(keys: list[str]) -> pd.DataFrame:
        wide = allrows.groupby(keys, as_index=False)[CLASSES].sum()
        long = wide.melt(id_vars=keys, value_vars=CLASSES,
                         var_name="차종", value_name="교통량")
        long["차종"] = long["차종"].str.replace("교통량", "", regex=False)
        long["영업소코드"] = long["영업소코드"].astype(int)
        long["영업소명"] = long["영업소코드"].map(name_map).fillna("")
        cols = ["영업소코드", "영업소명"] + [k for k in keys if k != "영업소코드"] \
               + ["차종", "교통량"]
        return long[cols].sort_values([k for k in keys] + ["차종"])

    long = fold(["연도", "영업소코드"])
    monthly = fold(["연월", "영업소코드"])

    print()
    for y in sorted(months):
        ms = sorted(int(m) for m in months[y])
        mark = "" if len(ms) == 12 else f"  ← {len(ms)}개월뿐 (온전한 해가 아님)"
        print(f"  {y}년: {len(ms)}개월 {ms}{mark}")
    if any(len(v) != 12 for v in months.values()):
        print("  ⚠ 온전하지 않은 해가 있습니다. 연도끼리 비교하려면 같은 달만"
              " 모아야 합니다 — 12개월과 7개월을 나란히 두면 안 됩니다.")

    missing = int((long["영업소명"] == "").sum())
    if missing:
        codes = [int(c) for c in
                 sorted(long.loc[long['영업소명'] == '', '영업소코드'].unique())[:5]]
        print(f"  ⚠ 영업소명을 못 찾은 {missing:,}행 (코드 예: {codes})")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    long.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n{out}  {len(long):,}행 · 영업소 {long['영업소코드'].nunique()}개"
          f" · 연도 {[int(y) for y in sorted(long['연도'].unique())]}")

    # 월별도 함께 낸다. 원본이 일별이라 공짜로 나오고, 화면의 월별/연별
    # 전환과 계절성 통제에 쓴다. 연별만 남기면 나중에 원본을 다시 받아야 한다.
    mout = Path(args.monthly_out) if args.monthly_out else Path(
        str(out).replace("annual", "monthly"))
    if mout == out:
        mout = out.with_name(out.stem + "_monthly" + out.suffix)
    monthly.to_csv(mout, index=False, encoding="utf-8-sig")
    print(f"{mout}  {len(monthly):,}행 · 월 {monthly['연월'].nunique()}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
