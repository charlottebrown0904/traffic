"""도시계획시설(KRAS)에서 고속도로 구간을 가려낼 수 있나 (2026-09-16 지시).

  "지금 하나도 맞지 않습니다. 계획은 살려 놓고 실제로 표시는 계획 도로
   처럼 **필지 기준으로 선택**될 수 있도록 방법을 전환바랍니다. 참고로
   토지이음의 이음지도를 보시면 도시 계획시설에 **대로2류**로 표시됩니다."

지금까지 우리가 그린 것은 두 끝을 잇는 선이었다(직선이거나, 노선에
스냅한 것이거나). 어느 쪽이든 **필지와 무관한 선**이라 화면과 안 맞는다.

그런데 그 구간은 이미 도시계획시설에 **면**으로 들어 있다 — 토지이음이
'대로2류(폭 30m~35m)' 로 보여 준 그 빨간 띠다. 면이니까 필지를 따라가고,
누르면 고를 수도 있다. 우리가 계획도로(lt_c_upisuq151)에 이미 쓰는
바로 그 층이다.

**그래서 답해야 할 것은 하나다: 그 대로2류가 고속도로 구간이라는 것을
무엇으로 아나.** 대로2류는 시내 간선도로에도 붙는 이름이라, 그냥 다
그리면 고속도로 층이 아니라 계획도로 층이 된다.

칸을 추측해서 고르지 않는다 — 오늘 그런 식으로 다섯 번 틀렸다. **모든
칸을 받아서** 값을 눈으로 본다.

  python scripts/road_kras_probe.py
"""
from __future__ import annotations

import os
import sys
import urllib.parse
from collections import Counter, defaultdict

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
WFS = "https://api.vworld.kr/req/wfs"
DATA = "https://api.vworld.kr/req/data"
LAYER = "lt_c_upisuq151"

# 받은 캡처 그대로 — 경기도 안성시 서운면 북산리 132-1 언저리.
# 세종포천고속도로 공사 구간이 여기를 지난다.
BOX = (36.96, 127.20, 37.03, 127.32)


def relay(url: str, timeout: int = 120):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": url})


def wfs_all():
    """**keep 을 안 건다.** 우리가 쓰는 네 칸 말고 무엇이 더 오는지 본다."""
    s, w, n, e = BOX
    q = {
        "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
        "TYPENAME": LAYER, "OUTPUT": "application/json",
        "SRSNAME": "EPSG:4326", "MAXFEATURES": "1000",
        "BBOX": f"{s},{w},{n},{e}",
        "key": "__via_relay__", "DOMAIN": "https://toji.fyi",
    }
    try:
        return relay(f"{WFS}?{urllib.parse.urlencode(q)}").json(), None
    except Exception as exc:                            # noqa: BLE001
        return None, f"{type(exc).__name__} {exc}"


def main() -> None:
    print("=" * 72)
    print("도시계획시설(KRAS) — 안성 서운면 북산리 언저리")
    print(f"상자 {BOX}")
    print("=" * 72)

    body, err = wfs_all()
    if err:
        sys.exit(f"  ✗ 못 불렀다: {err}")
    feats = (body or {}).get("features") or []
    print(f"  시설 {len(feats)}개"
          + ("  ← 상한에 걸림" if len(feats) >= 1000 else ""))
    if not feats:
        print(f"  응답: {str(body)[:300]}")
        return

    props = sorted(feats[0].get("properties") or {})
    print(f"\n  칸 이름 ({len(props)}개): {props}")

    # **칸마다 값을 다 찍는다.** 어느 칸이 고속도로를 가려 주는지는
    # 값을 봐야 안다.
    print("\n  칸마다 실제로 오는 값:")
    for k in props:
        c = Counter(str((f.get("properties") or {}).get(k)) for f in feats)
        top = " · ".join(f"{v!r}×{n}" for v, n in c.most_common(6))
        print(f"    {k:10s} ({len(c)}가지) {top[:120]}")

    # '고속' 이 어디 들어 있나
    hit = defaultdict(int)
    for f in feats:
        for k, v in (f.get("properties") or {}).items():
            if "고속" in str(v):
                hit[k] += 1
    print(f"\n  '고속' 이 들어 있는 칸: {dict(hit) or '없음'}")

    # 대로류만 따로 — 토지이음이 '대로2류' 라고 했다
    big = [f for f in feats
           if "대로" in str((f.get("properties") or {}).get("atr_nam") or "")]
    print(f"\n  atr_nam 에 '대로' 가 든 시설 {len(big)}개:")
    for f in big[:10]:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        co = g.get("coordinates") or []
        ring = (co[0][0] if g.get("type") == "MultiPolygon" and co
                else (co[0] if co else []))
        print(f"    {str(p.get('atr_nam')):10s} {str(p.get('exc_nam')):8s}"
              f" {str(p.get('pmi_nam'))[:16]:18s} 꼭짓점 {len(ring)}개")

    print("\n" + "=" * 72)
    print("무엇을 보고 판단하나")
    print("=" * 72)
    print("  · 시설 이름 칸이 있으면 → 이름으로 고속도로를 가려낸다")
    print("  · 없으면 → 우리 고시 구간(두 끝)과 **겹치는 면**만 고른다")
    print("  · 어느 쪽이든 면이라 **필지를 따라가고 누를 수 있다**")


if __name__ == "__main__":
    main()
