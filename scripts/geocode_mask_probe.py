"""가려진 지번으로 얻은 '지번단위' 좌표가 진짜인가 — 탐침.

## 왜 묻는가

국토부는 토지 실거래의 지번을 일부만 준다 ('1**', '산1**').
`collect/geocode.py` 의 `geocode_with_fallback` 은 그 주소로 브이월드를
부르고, **좌표가 오기만 하면 'parcel' 로 적는다.**

    if lat is not None:
        return lat, lon, "parcel"

브이월드가 "안성시 대덕면 1**" 에 무엇을 돌려주는지는 아무도 확인한 적이
없다. 그런데 내보낸 표본을 세어 보면 2006~2023 의 지번은 **100% 가려져
있는데** 그 해들의 20~29% 가 'parcel' 로 적혀 있다. 둘 중 하나다.

  (가) 브이월드가 가려진 번호를 무시하고 **동 중심점**을 준다
       → 그 20~29% 는 사실 umd 다. 이름이 거짓말을 하고 있고,
         `require_parcel_bands` 로 거른 분석이 오염돼 있다.
  (나) 브이월드가 **아무 필지나** 골라 준다
       → 더 나쁘다. 엉뚱한 땅의 좌표가 '정확' 이라는 표를 달고 있다.
  (다) 브이월드가 정말로 맞힌다
       → 그러면 지금이 맞고, 이 탐침은 그것을 확인해 준다.

## 어떻게 가르는가

**같은 법정동 안에서 서로 다른 가려진 지번 여럿**을 물어 본다.

  · 답이 다 **같은 좌표**면 (가) — 번호를 안 보고 동만 본 것이다.
  · 답이 **제각각**이면 (나) 또는 (다). 그때는 동 중심점과의 거리를 본다.
    동 중심에서 수 km 떨어진 값이 나오면 무언가를 고르기는 한 것이고,
    그것이 맞는 필지인지는 **우리가 확인할 길이 없다** — 가려진 번호로는
    정답을 모르기 때문이다. 그 경우 'parcel' 이라고 부르면 안 된다.

대조군으로 **온전한 지번**(2024~25 에만 있다)도 같이 물어 본다. 그쪽이
제각각 나오면 지오코더 자체는 멀쩡하다는 뜻이다.

    python scripts/geocode_mask_probe.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redt.collect.geocode import build_address, geocode_one   # noqa: E402

# 한 법정동 안의 가려진 지번들. 실제 내보낸 표본에서 본 꼴 그대로다.
CASES = [
    ("가려진 지번 · 같은 동", "안성시", "대덕면 소현리",
     ["1**", "2**", "3**", "4**", "1***"]),
    ("가려진 지번 · 같은 동", "화성시", "장안면 사랑리",
     ["1**", "5**", "8**", "산1**"]),
    ("온전한 지번 · 대조군", "안성시", "대덕면 소현리",
     ["100", "200", "300", "400"]),
]


def dist_m(a, b) -> float:
    import math
    if None in a or None in b:
        return float("nan")
    dlat = (a[0] - b[0]) * 111_320
    dlon = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


def main() -> int:
    print("=" * 70)
    print(" 가려진 지번으로 얻은 'parcel' 좌표가 진짜인가")
    print("=" * 70)

    verdicts = []
    for label, sigungu, umd, jibuns in CASES:
        print(f"\n── {label} — {sigungu} {umd}")
        base = geocode_one(build_address(None, sigungu, umd, None), "PARCEL")
        print(f"   동 중심점: {base}")
        got = {}
        for j in jibuns:
            addr = build_address(None, sigungu, umd, j)
            lat, lon = geocode_one(addr, "PARCEL")
            got[j] = (lat, lon)
            d = dist_m((lat, lon), base) if lat is not None else float("nan")
            mark = "✗ 못 얻음" if lat is None else f"동 중심에서 {d:>8.0f} m"
            print(f"   {j:<8s} → {str((lat, lon)):<34s} {mark}")

        vals = [v for v in got.values() if v[0] is not None]
        uniq = {(round(a, 6), round(b, 6)) for a, b in vals}
        if not vals:
            v = "좌표를 하나도 못 얻었다 — 이 경우 fallback 이 umd 로 내려간다"
        elif len(uniq) == 1:
            same_as_base = base[0] is not None and dist_m(vals[0], base) < 1
            v = ("(가) **번호를 안 본다.** 서로 다른 지번이 한 좌표로 몰렸다"
                 + (" — 그리고 그것이 동 중심점이다" if same_as_base else ""))
        else:
            v = f"(나)/(다) 제각각이다 — 서로 다른 좌표 {len(uniq)}개"
        print(f"   판정: {v}")
        verdicts.append((label, v))

    print("\n" + "=" * 70)
    print(" 정리")
    print("=" * 70)
    for label, v in verdicts:
        print(f"  {label:24s} {v}")
    print("""
 읽는 법
   가려진 쪽이 (가) 이고 온전한 쪽이 제각각이면 → 지오코더는 멀쩡하고
   **우리 이름표가 틀린 것**이다. 가려진 지번으로 얻은 좌표를 'parcel'
   이라 부르면 안 되고, umd 로 내려 적어야 한다.

   가려진 쪽도 제각각이면 → 브이월드가 무언가를 고르고 있다. 가려진
   번호로는 정답을 모르므로 **맞는지 확인할 길이 없다.** 확인 못 하는
   것을 '정확' 이라고 부르지 않는다.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
