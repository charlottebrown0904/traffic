"""영업소 코드가 쪼개지거나 바뀐 지점을 찾는다.

왜 필요한가
-----------
2014-10 에 가락(246)이 월 -1,004k 떨어지면서, 같은 달에 새 코드 둘이
나타났습니다.

    29  가락(개)  +848,698
    596 가락2     +144,572
                   ─────────
    합              993,270   ≈ 246 의 감소분

교통량이 사라진 게 아니라 **코드가 쪼개진 것**입니다. 이걸 모르고 두면
두 가지가 동시에 망가집니다.

  246       -87% 수요 감소로 보인다 → Δln(교통량)에 가짜 급락이 들어간다
  29·596    2014년 신규 개통으로 보인다 → H1 처치군에 잘못 들어간다

뒤엣것이 더 나쁩니다. 그 자리에 원래 IC 가 있었는데 '새로 뚫린 IC' 로
세면, 개통 효과를 재는 표본 자체가 오염됩니다.

어떻게 찾는가
-------------
어떤 달에 **처음 나타난 코드**의 교통량 합과, 같은 달에 **크게 줄어든
코드**의 감소량 합이 비슷하면 승계로 봅니다. 우연히 같은 달에 진짜 개통과
진짜 감소가 겹칠 수 있으므로 단정하지 않고 '의심' 으로 적습니다 —
사람이 확인할 수 있게 근거 숫자를 함께 남깁니다.

  python scripts/tollgate_succession.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAW = Path("data/raw")
OUT = RAW / "tollgate_succession.csv"

DROP_RATIO = 0.5      # 이 비율 아래로 떨어져야 '크게 줄었다'
MATCH_TOL = 0.35      # 신규 합과 감소 합이 이만큼 안에서 맞으면 승계로 본다
MIN_VOLUME = 10_000   # 너무 작은 것은 잡음


def load_monthly() -> pd.DataFrame:
    frames = [pd.read_csv(p, encoding="utf-8-sig",
                          usecols=["영업소코드", "연월", "교통량"])
              for p in sorted(RAW.glob("tcs_monthly_*.csv"))]
    if not frames:
        sys.exit("월별 파일이 없습니다.")
    df = pd.concat(frames)
    return df.groupby(["영업소코드", "연월"], as_index=False)["교통량"].sum()


def names() -> dict[int, str]:
    out = {}
    for p in sorted(RAW.glob("tcs_annual_*.csv")):
        if p.name.startswith("legacy_"):
            continue
        d = pd.read_csv(p, encoding="utf-8-sig", usecols=["영업소코드", "영업소명"])
        out.update(dict(zip(d["영업소코드"], d["영업소명"].astype(str))))
    return out


def _verdict(new_name: str, pred_name: str) -> str:
    """이름이 이어지면 '이름일치', 아니면 '월합만일치'.

    월 합계만 맞는 것으로는 부족합니다. 실제로 2014-10 에 가락 분할과
    동충주 개통이 같은 달에 겹쳐, 동충주가 승계로 잘못 잡혔습니다.
    동충주는 중부내륙 노선의 진짜 신규 IC 입니다.

    이름이 이어지는 것(가락 → 가락(개)·가락2)만 확실하다고 보고, 나머지는
    '월합만일치' 로 적어 사람이 보게 둡니다. H1 처치군에서 빼는 것은
    '이름일치' 뿐입니다 — 진짜 개통을 잘못 빼면 표본만 줄어듭니다.
    """
    a = "".join(ch for ch in str(new_name) if ch.isalnum())
    b = "".join(ch for ch in str(pred_name) if ch.isalnum())
    if not a or not b:
        return "월합만일치"
    return "이름일치" if (b in a or a in b) else "월합만일치"


def main() -> int:
    df = load_monthly()
    piv = df.pivot(index="영업소코드", columns="연월", values="교통량")
    cols = list(piv.columns)
    nm = names()
    rows = []

    # 첫 달과 마지막 달은 앞뒤 3개월을 못 보므로 건너뛴다
    for i in range(3, len(cols) - 2):
        month = cols[i]
        before = piv[cols[i - 3:i]].mean(axis=1)
        after = piv[cols[i:i + 3]].mean(axis=1)

        appeared = piv.index[piv[cols[i - 1]].isna() & piv[month].notna()]
        appeared = [c for c in appeared if after.get(c, 0) >= MIN_VOLUME]
        if not appeared:
            continue

        fell = before[(before >= MIN_VOLUME)
                      & (after.reindex(before.index).fillna(0) < before * DROP_RATIO)]
        if fell.empty:
            continue

        gain = float(after[appeared].sum())
        loss = float((fell - after.reindex(fell.index).fillna(0)).sum())
        if loss <= 0:
            continue
        gap = abs(gain - loss) / max(gain, loss)
        if gap > MATCH_TOL:
            continue

        drops = (fell - after.reindex(fell.index).fillna(0)).sort_values(ascending=False)
        pred = int(drops.index[0])
        pred_name = nm.get(pred, "")
        for code in appeared:
            new_name = nm.get(int(code), "")
            rows.append({
                "신규코드": int(code),
                "신규명": new_name,
                "연월": month,
                "신규교통량": round(float(after[code])),
                "선행코드": pred,
                "선행명": pred_name,
                "선행감소량": round(float(drops.iloc[0])),
                "신규합": round(gain),
                "감소합": round(loss),
                "차이비율": round(gap, 3),
                "판정": _verdict(new_name, pred_name),
            })

    if not rows:
        print("승계로 의심되는 코드 변경이 없습니다.")
        OUT.write_text("신규코드,신규명,연월,신규교통량,선행코드,선행명,"
                       "선행감소량,신규합,감소합,차이비율,판정\n", encoding="utf-8-sig")
        return 0

    out = pd.DataFrame(rows).drop_duplicates(subset=["신규코드", "연월"])
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    sure = out[out["판정"] == "이름일치"]
    maybe = out[out["판정"] != "이름일치"]
    print(f"코드 승계로 잡힌 신규 코드 {len(out)}개 "
          f"(이름까지 이어지는 것 {len(sure)}개)")
    print(out.to_string(index=False))
    print(f"\n→ {OUT}")
    if len(sure):
        print(f"\n이름일치 {len(sure)}개는 H1 처치군에서 뺍니다 — 그 자리에 원래 IC 가")
        print("  있었으므로 '새로 뚫린 IC' 가 아닙니다.")
    if len(maybe):
        print(f"\n월합만일치 {len(maybe)}개는 **빼지 않습니다.** 진짜 개통과 코드 승계가")
        print("  같은 달에 겹쳤을 뿐일 수 있습니다. 진짜 개통을 잘못 빼면 표본만")
        print("  줄어듭니다. 사람이 확인할 수 있게 근거 숫자를 남깁니다:")
        print("  " + " · ".join(f"{int(r.신규코드)} {r.신규명}" for r in maybe.itertuples()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
