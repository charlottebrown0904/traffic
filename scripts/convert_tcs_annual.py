"""도로공사 '영업소별 교통량' 연간 집계 엑셀을 로더가 읽는 long 형식으로 바꾼다.

포털에서 받은 원본은 머리글이 3줄이고 차종이 가로로 펼쳐져 있다.
  전체순위 | 영업소코드 | 영업소명 | 총교통량 | 1종교통량 ... 6종교통량

이것을 (영업소 × 연도 × 차종) 한 행씩으로 편다. 총교통량은 차종 합과 중복이므로
싣지 않는다 — 그대로 두면 합계가 두 배가 된다.

  python scripts/convert_tcs_annual.py <엑셀> <연도> <출력csv>
"""
from __future__ import annotations

import sys

import pandas as pd

CLASSES = {
    "1종교통량": "1종",
    "2종교통량": "2종",
    "3종교통량": "3종",
    "4종교통량": "4종",
    "5종교통량": "5종",
    "6종교통량": "6종",
}


def load(path: str) -> pd.DataFrame:
    # 머리글 3줄 중 실제 컬럼명은 세 번째 줄에 있다.
    df = pd.read_excel(path, sheet_name=0, header=2)
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    return df.dropna(subset=["영업소코드"]).copy()


def convert(df: pd.DataFrame, year: int) -> pd.DataFrame:
    for col in ["영업소코드", "총교통량", *CLASSES]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["영업소코드"])

    # 차종 합과 총교통량이 어긋나는 행은 원본이 이상한 것이므로 알린다.
    total = df[list(CLASSES)].sum(axis=1)
    bad = (total - df["총교통량"]).abs() > 1
    if bad.any():
        print(f"  ⚠ 차종합 ≠ 총교통량 인 영업소 {int(bad.sum())}건")
        print(df.loc[bad, ["영업소코드", "영업소명", "총교통량"]].to_string(index=False))

    long = df.melt(
        id_vars=["영업소코드", "영업소명"],
        value_vars=list(CLASSES),
        var_name="차종",
        value_name="교통량",
    )
    long["차종"] = long["차종"].map(CLASSES)
    long["연도"] = year
    long["영업소코드"] = long["영업소코드"].astype(int).astype(str)
    long = long.dropna(subset=["교통량"])
    return long[["영업소코드", "영업소명", "연도", "차종", "교통량"]]


def main() -> None:
    src, year, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    df = load(src)
    print(f"  원본 영업소 {len(df):,}곳")
    long = convert(df, year)
    long.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"  → {out}  {len(long):,}행 (영업소 {long['영업소코드'].nunique():,} × 차종 6)")
    print(f"  총 통행 {int(long['교통량'].sum()):,}")


if __name__ == "__main__":
    main()
