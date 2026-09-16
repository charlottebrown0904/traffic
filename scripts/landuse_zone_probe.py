"""토지이용계획에 어떤 구분자가 실제로 오나 — 세어서 답한다 (2026-09-16).

  "그럼 농업진흥구역, 준보전산지, 보전산지 같은 구분자도 데이터베이스에
   있는 건가요?"

**우리 데이터베이스에는 없다.** 부를 때마다 토지이음(LURIS)이 주는
것이고, 우리는 그것을 쌓아 두지 않는다. 지금 필지 카드가 '가축사육제한
구역' 하나만 보여 주는 까닭도 그것이다 — 브이월드 층 몇 개만 따로 묻고
있다.

그러면 **부르면 무엇이 오나.** 천안 북면 양곡리 한 필지에서 이미 이만큼
나왔다: 준보전산지 · 임업용산지 · 농림지역 · 영농여건불리농지 ·
계획관리지역 · 성장관리계획구역 · 가축사육제한구역 · 도로구역 ·
접도구역 · 소하천구역 · 소하천예정지 · 대로2류.

농업진흥구역은 그 표본에 그 지역지구가 없는 필지들이라 안 나왔을 뿐이다.
**없다고 단정하지 않는다** — 오늘 그런 식으로 여러 번 틀렸다. 농업진흥
지역이 실제로 있는 평야와 보전산지가 있는 산간을 함께 두드려, 나오는
구분자를 **코드와 함께 전부 센다.**

  python scripts/landuse_zone_probe.py
"""
from __future__ import annotations

import os
import sys
import urllib.parse
from collections import Counter

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
WFS = "https://api.vworld.kr/ned/wfs/getLandUseWFS"
DOMAIN = os.environ.get("VWORLD_DOMAIN", "https://toji.fyi")
TYPE = "dt_d154"

# 자리를 고르는 기준: **찾는 것이 있을 만한 곳**이라야 '없다' 와 '그 자리에
# 없다' 가 안 헷갈린다. 오늘 안성에서 그 실수를 했다.
SPOTS = [
    ("김제 만경 (평야 — 농업진흥지역)", 35.867, 126.865),
    ("당진 합덕 (평야 — 농업진흥지역)", 36.766, 126.804),
    ("홍천 내면 (산간 — 보전산지)", 37.783, 128.440),
    ("천안 북면 양곡리 (이미 아는 곳)", 36.848, 127.275),
    ("서울 강남 (도시 — 대조군)", 37.498, 127.028),
]
HALF = 0.006          # 한 변 1.3km 남짓


def relay(params: dict, timeout: int = 90):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    target = f"{WFS}?{urllib.parse.urlencode(params)}"
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": target})


def main() -> None:
    bar = "=" * 72
    print(bar)
    print("토지이용계획(dt_d154)에 어떤 구분자가 오나 — 코드와 함께 센다")
    print(bar)
    print("  우리 DB 에는 없다. 부를 때마다 오는 것이다.")
    print()
    total = Counter()
    for name, lat, lon in SPOTS:
        p = {
            "typename": TYPE,
            "bbox": f"{lon - HALF},{lat - HALF},{lon + HALF},{lat + HALF}",
            "srsname": "EPSG:4326", "format": "json",
            "output": "application/json", "maxFeatures": "300",
            "key": "__via_relay__", "domain": DOMAIN,
        }
        try:
            feats = relay(p).json().get("features") or []
        except Exception as err:                       # noqa: BLE001
            print(f"  {name:<30} 못 받았다 — {type(err).__name__}")
            continue
        here = Counter()
        for f in feats:
            src = (f or {}).get("properties") or {}
            codes = str(src.get("prpos_area_dstrc_code_list") or "").split(",")
            names = str(src.get("prpos_area_dstrc_nm_list") or "").split(",")
            # **이름은 쉼표를 품을 수 있다.** 그래서 코드 수와 이름 수가
            # 다르면 이름 쪽은 세지 않는다 — 자리가 밀린 값을 세면
            # 없는 구분자를 지어내게 된다.
            fit = len(codes) == len(names)
            for i, code in enumerate(codes):
                code = code.strip()
                if not code:
                    continue
                label = names[i].strip() if fit else "(이름 못 맞춤)"
                here[f"{code}  {label}"] += 1
        total.update(here)
        print(f"  ── {name} · 필지 {len(feats)}개 · 구분자 {len(here)}가지")
        for k, v in here.most_common(14):
            print(f"       {k[:52]:<54}{v}")
        print()
    print(bar)
    print("다 합쳐서 — 구분자 코드별")
    print(bar)
    for k, v in total.most_common(60):
        print(f"  {k[:56]:<58}{v}")
    print()
    print(bar)
    print("찾던 것이 나왔나")
    print(bar)
    joined = " ".join(total)
    for want in ("농업진흥구역", "농업보호구역", "준보전산지", "임업용산지",
                 "공익용산지", "보전산지", "농림지역", "개발제한구역"):
        print(f"  {want:<10}{'나왔다' if want in joined else '이 표본에는 없다'}")


if __name__ == "__main__":
    main()
