"""새로 붙인 교통량 연도를 이웃 해와 대조한다.

받은 자료를 그냥 믿지 않는다. 단위가 다르거나 열이 밀리거나 집계 방식이
어긋나도 파일은 멀쩡히 읽히고, 회귀에서는 계수 크기만 달라져 눈에 안 띈다.
그래서 **붙이기 전에** 세 가지를 본다.

  1. 전국 **월평균**의 연간 비  0.8~1.25 밖이면 의심.
                         연 합계로 견주면 안 된다 — 2010년은 10월 원본이 없어
                         11개월뿐이라, 연 합계로는 이듬해가 12.9% 늘어난 것처럼
                         보인다. 월평균으로는 2.9% 다.
  2. 영업소별 비 중앙값  1.0 근처여야 한다. 전국 합만 맞고 중앙값이 어긋나면
                         일부 영업소만 이상한 것이다.
  3. 차종 구성           1종이 80% 안팎. 여기가 틀어지면 열이 밀린 것이다.

비가 크게 어긋난 영업소는 대부분 '연중 개통' 이라 관측월수가 12개월이 안
된다. 그건 정상이므로 걸러내고, **12개월 다 있으면서 크게 변한 곳만**
따로 보여준다. 그게 진짜 확인이 필요한 것이다.

  python scripts/verify_tcs_year.py 2015 2016
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAW = Path("data/raw")
LO, HI = 0.80, 1.25          # 전국 합의 연간 비가 이 밖이면 의심
ODD_LO, ODD_HI = 0.5, 2.0    # 영업소별로 이 밖이면 들여다본다


def load(year: int) -> pd.DataFrame:
    p = RAW / f"tcs_annual_{year}.csv"
    if not p.exists():
        sys.exit(f"{p} 가 없습니다. convert_tcs_daily.py 를 먼저 돌리세요.")
    return pd.read_csv(p, encoding="utf-8-sig")


def observed(year: int) -> int:
    """그 해에 실제로 자료가 있는 달 수. 12가 아닐 수 있다."""
    p = RAW / f"tcs_monthly_{year}.csv"
    if not p.exists():
        return 12
    m = pd.read_csv(p, encoding="utf-8-sig", usecols=["연월"])
    return int(m["연월"].nunique())


def months(year: int) -> pd.Series:
    p = RAW / f"tcs_monthly_{year}.csv"
    if not p.exists():
        return pd.Series(dtype=int)
    m = pd.read_csv(p, encoding="utf-8-sig", usecols=["영업소코드", "연월"])
    return m.groupby("영업소코드")["연월"].nunique()


def main() -> int:
    if len(sys.argv) < 3:
        sys.exit("사용법: verify_tcs_year.py <새연도> <기준연도>")
    new_y, ref_y = int(sys.argv[1]), int(sys.argv[2])
    new, ref = load(new_y), load(ref_y)
    fail = []

    def check(ok: bool, msg: str) -> None:
        print(("  통과  " if ok else "  실패  ") + msg)
        if not ok:
            fail.append(msg)

    print(f"=== {new_y} 를 {ref_y} 와 대조 ===")

    # 달 수가 다르면 연 합계끼리 비교하면 안 된다. 2010년은 10월 원본이
    # 없어 11개월뿐인데, 연 합계로 보면 이듬해가 12.9% 늘어난 것처럼 보인다.
    # 실제로는 2.9% 다. **관측한 달 수로 나눠 월평균끼리 비교한다.**
    #
    # 파이프라인 자체는 이미 일평균(avg_daily)을 쓰므로 영향이 없다.
    # 틀린 것은 이 대조 절차였다.
    mn_new, mn_ref = observed(new_y), observed(ref_y)
    if mn_new != 12 or mn_ref != 12:
        print(f"  관측 달 수: {new_y} {mn_new}개월 · {ref_y} {mn_ref}개월"
              f" — 월평균으로 견줍니다")

    tn = new.groupby("영업소코드")["교통량"].sum() / mn_new
    tr = ref.groupby("영업소코드")["교통량"].sum() / mn_ref
    ratio = tr.sum() / tn.sum()
    check(LO <= ratio <= HI,
          f"전국 월평균 {tn.sum():,.0f} → {tr.sum():,.0f} (비 {ratio:.3f})")

    j = pd.concat([tn.rename("new"), tr.rename("ref")], axis=1).dropna()
    med = (j["ref"] / j["new"]).median()
    check(LO <= med <= HI,
          f"영업소별 비 중앙값 {med:.3f} (두 해 모두 있는 {len(j)}개)")

    def share(d: pd.DataFrame) -> pd.Series:
        s = d.groupby("차종")["교통량"].sum()
        return s / s.sum()

    sn, sr = share(new), share(ref)
    gap = (sn - sr).abs().max()
    check(gap < 0.03,
          f"차종 구성 최대 차이 {gap:.3f}  "
          + " ".join(f"{k}:{sn[k]:.3f}→{sr.get(k, float('nan')):.3f}" for k in sn.index))

    mn = months(new_y)
    check(int((mn == mn_new).sum()) > 0,
          f"그 해 모든 달({mn_new}개월)이 있는 영업소 {int((mn == mn_new).sum())}개 / "
          f"덜 있는 영업소 {int((mn < mn_new).sum())}개")

    # 연중 개통을 걸러내고, 그 해 내내 있으면서 크게 변한 곳만 본다
    j["비"] = j["ref"] / j["new"]
    odd = j[(j["비"] < ODD_LO) | (j["비"] > ODD_HI)]
    partial = set(mn[mn < mn_new].index)
    real = odd[~odd.index.isin(partial)]
    print(f"\n비가 {ODD_LO}~{ODD_HI} 밖인 영업소 {len(odd)}개 "
          f"— 그중 {len(odd) - len(real)}개는 연중 개통(관측 {mn_new}개월 미만)")
    if len(real):
        print(f"  ⚠ 그 해 내내({mn_new}개월) 있으면서 크게 변한 곳 — 확인이 필요합니다")
        print(real.assign(관측월수=mn.reindex(real.index)).round(2).to_string())
    else:
        print("  12개월 다 있으면서 크게 변한 곳은 없습니다.")

    print()
    if fail:
        print(f"실패 {len(fail)}건 — 붙이기 전에 원인을 확인하세요.")
        return 1
    print("대조 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
