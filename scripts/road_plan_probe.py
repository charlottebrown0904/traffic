"""고속도로 **공사·신설 계획**을 지도에 그릴 수 있는가 (2026-09-16 지시).

  "현 계획도로처럼 고속도로 공사 및 신규 IC 추가, 계획에 대해서 표시할 수
   있는 방법을 찾아주세요."

우리가 지금 그리는 계획도로는 `lt_c_upisuq151` — **도시계획시설 도로**다.
도시계획시설은 시·군이 결정하는 것이라, 나라가 놓는 **고속국도**는 여기에
안 들어온다. 그래서 다른 층을 찾아야 한다.

브이월드 목록(177개)에서 도로·교통에 걸린 것이 22개다. 그중 계획·공사가
들어 있을 만한 넷을 두드린다. **속성에 무엇이 오는가**가 전부다 —
개통예정연도나 공사중 표시가 칸으로 오면 그릴 수 있고, 안 오면 못 한다.

  lt_c_upisuq152   도시계획(교통시설)   철도·정류장·주차장이 여기 있을 것
  lt_l_moctlink    교통링크             ITS 표준링크. 도로등급이 있으면 고속국도를 가른다
  lt_l_n3a0020000  도로중심선           수치지도. 건설중 표시가 있는가
  lt_l_sprd        도로명주소도로       완공 도로만일 것 — 대조군

그리고 **이미 가진 층에서 건질 것**을 확인한다: `lt_c_upisuq151` 의
`pmi_nam` 에 '도시고속도로' 가 있다. 고속화도로의 계획선은 이미 우리
손에 있다는 뜻이고, 그렇다면 갈래 하나만 더 만들면 된다.

  python scripts/road_plan_probe.py
"""
from __future__ import annotations

import os
import sys
import urllib.parse

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
WFS = "https://api.vworld.kr/req/wfs"

# 두드릴 자리. **고속도로 공사가 실제로 있는 곳**이라야 '빈 층' 과
# '그 자리에 없음' 을 가른다. 수도권제2순환(화성~오산)·세종포천(안성)·
# 서울양평(양평) 언저리.
SPOTS = [
    ("화성 동탄", 127.00, 37.15, 127.20, 37.28),
    ("안성 서운", 127.20, 36.95, 127.40, 37.10),
    ("양평 강상", 127.45, 37.44, 127.65, 37.58),
]

LAYERS = [
    ("lt_c_upisuq152", "도시계획(교통시설)"),
    ("lt_l_moctlink", "교통링크(ITS 표준링크)"),
    ("lt_l_n3a0020000", "도로중심선(수치지도)"),
    ("lt_l_sprd", "도로명주소도로 — 대조군"),
    ("lt_c_upisuq151", "도시계획(도로) — 이미 쓰는 층"),
]

# 이 말이 칸 값에 있으면 '계획·공사' 를 담고 있다는 뜻이다.
PLAN_WORDS = ("계획", "공사", "예정", "건설", "미개통", "신설", "확장", "개통")


def call(params: dict, timeout: int = 60):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    target = f"{WFS}?{urllib.parse.urlencode(params)}"
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": target})


def features(name: str, bbox: str, limit: int = 1000):
    resp = call({
        "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0",
        "TYPENAME": name, "BBOX": bbox, "SRSNAME": "EPSG:4326",
        "OUTPUT": "application/json", "MAXFEATURES": str(limit),
        "RESULTTYPE": "results", "DOMAIN": "https://toji.fyi/",
    })
    try:
        body = resp.json()
    except Exception:                                  # noqa: BLE001
        return None, resp.text[:160]
    return (body or {}).get("features") or [], None


def main() -> None:
    print("=" * 72)
    print("고속도로 계획·공사를 담은 층이 있는가")
    print("=" * 72)
    for name, label in LAYERS:
        print(f"\n[{name}] {label}")
        keys: set[str] = set()
        vals: dict[str, set[str]] = {}
        total = 0
        for spot, w, s, e, n in SPOTS:
            feats, err = features(name, f"{w},{s},{e},{n}")
            if feats is None:
                print(f"   {spot:10s} ✗ {err}")
                continue
            total += len(feats)
            print(f"   {spot:10s} {len(feats)}건")
            for f in feats:
                p = f.get("properties") or {}
                keys |= set(p)
                for k, v in p.items():
                    vals.setdefault(k, set()).add(str(v))
        if not total:
            print("   → 세 자리 모두 0건. 이 층으로는 못 그린다.")
            continue
        print(f"   속성 열쇠 {len(keys)}개: {sorted(keys)}")
        # 계획·공사를 뜻하는 말이 **값 안에** 있는가 — 이것이 핵심이다.
        hits = []
        for k in sorted(vals):
            vs = vals[k]
            if len(vs) <= 20 and any(any(w in v for w in PLAN_WORDS) for v in vs):
                hits.append((k, sorted(vs)[:20]))
        if hits:
            print("   ★ 계획·공사로 읽히는 칸:")
            for k, vs in hits:
                print(f"      {k}: {vs}")
        else:
            print("   계획·공사로 읽히는 칸: 없음")
        # 갈래가 될 만한 칸(값이 2~20가지)을 전부 적는다.
        for k in sorted(vals):
            vs = vals[k]
            if 1 < len(vs) <= 20:
                print(f"      {k}: {sorted(vs)[:20]}")

    # ── 이미 가진 층에서 건질 것 ──────────────────────────────────
    print("\n" + "=" * 72)
    print("우리가 이미 받는 계획도로 안에 '도시고속도로' 가 얼마나 있나")
    print("=" * 72)
    for spot, w, s, e, n in SPOTS:
        feats, err = features("lt_c_upisuq151", f"{w},{s},{e},{n}", 1000)
        if feats is None:
            print(f"   {spot:10s} ✗ {err}")
            continue
        from collections import Counter                # noqa: PLC0415
        c = Counter(str((f.get("properties") or {}).get("pmi_nam"))
                    for f in feats)
        hi = c.get("도시고속도로", 0)
        print(f"   {spot:10s} 전체 {len(feats):4d}건 · 도시고속도로 {hi}건")
        if hi:
            ex = [f for f in feats
                  if (f.get("properties") or {}).get("pmi_nam") == "도시고속도로"][:2]
            for f in ex:
                p = f.get("properties") or {}
                print(f"      보기: {p.get('atr_nam')} · {p.get('exc_nam')} "
                      f"· 연장 {p.get('dgm_lt')}m · {p.get('sig_nam')}")


if __name__ == "__main__":
    main()
