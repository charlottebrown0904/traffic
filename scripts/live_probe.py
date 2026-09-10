"""라이브가 진짜로 무엇을 주는지 잰다 — 흉내가 아니라.

2026-09-10 에 필지 조회가 라이브에서 통째로 400 이었는데 아무도
몰랐다. 검사는 흉내낸 응답만 보고, 사람은 눌러 보기 전에는 모른다.
여기서 진짜로 재면 사람 눈보다 먼저 잡힌다.

**로직을 워크플로 안에 쓰지 않는다.** 셸 안에 파이썬을 겹쳐 넣다가
YAML 을 두 번 깨뜨렸다. 파이썬 파일이면 문법을 바로 잰다.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get("BASE", "https://toji.fyi")
TIMEOUT = 40

# 안성 한 점. 필지가 확실히 있는 자리라 '없어서 안 나온다' 와
# '고장나서 안 나온다' 가 안 섞인다.
LAT, LON = 37.0080, 127.2797

# 그 자리를 덮는 칸. 경계선은 배율 16 부터 그린다 — 그보다 얕으면
# 한 칸에 든 필지가 상한에 걸려 선이 군데군데 빠진다.
TILES = [(16, 55938, 25506), (17, 111877, 51013), (18, 223754, 102027)]


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as exc:                                # noqa: BLE001
        print(f"    실패: {type(exc).__name__}: {exc}")
        return 0, b""


def lines() -> int:
    """경계선을 **도형으로** 받는가. 그림이 아니다 (2026-09-10 전환).

    옛 길(layer=cadastral 타일)은 배율 18 아래로 완전히 투명한 PNG 를
    줬는데, 크기만 재던 검사가 '✓ 그림' 으로 통과시켰다. 이제는 필지가
    **몇 개** 왔는지를 센다 — 0 개면 화면에 아무 선도 안 그려진다.
    """
    bad = 0
    print(f"  필지 경계선 (mode=parcels · 배율 {TILES[0][0]} 이상)")
    for z, x, y in TILES:
        code, body = get(f"{BASE}/api/tile?mode=parcels&z={z}&x={x}&y={y}")
        try:
            d = json.loads(body.decode("utf-8", "replace"))
        except Exception:                                    # noqa: BLE001
            d = None
        n = len((d or {}).get("geoms") or [])
        ok = code == 200 and n > 0
        print(f"    z={z:<3} http={code} {len(body):>7,}B  필지 {n:>3}개  "
              f"{'✓' if ok else '✗'}")
        if not ok:
            bad += 1
            if d is None:
                print("      " + " ".join(
                    body[:200].decode("utf-8", "replace").split()))
            else:
                print("      필지가 0개입니다 — 화면에 아무 선도 안 그려집니다.")
    return bad


def parcel() -> int:
    print("  필지 조회 (mode=parcel · 안성 한 점)")
    code, body = get(f"{BASE}/api/tile?mode=parcel&lat={LAT}&lon={LON}")
    print(f"    http={code} {len(body):>6}B")
    if code != 200:
        print("      " + " ".join(body[:200].decode("utf-8", "replace").split()))
        return 1
    try:
        d = json.loads(body)
    except ValueError as exc:
        print(f"    ✗ JSON 이 아닙니다: {exc}")
        return 1
    p, g = d.get("parcel"), d.get("geom")
    if not p:
        print(f"    ✗ 필지가 없습니다 — {str(d)[:160]}")
        return 1
    print(f"    ✓ {p.get('jimok')} · {p.get('land_use')} · "
          f"{p.get('area_m2')}㎡ · 공시지가 {p.get('official_price')}")
    if not g:
        print("    ✗ 윤곽(geom)이 없습니다 — 화면이 테두리를 못 그립니다")
        return 1
    pts = json.dumps(g).count("[") - 2
    print(f"    ✓ 윤곽 {g.get('type')} · 꼭짓점 약 {pts}개")
    # 겹친 지구·구역 (요구사항 2026-09-10). 라이브에서 실제로 오는지.
    # 안성 그 필지는 아무 규제도 안 걸릴 수 있어 **개수만 적고** 실패로
    # 세지 않는다 — 0개가 곧 고장은 아니다. 다만 칸 자체가 없으면
    # 서버가 그것을 아예 안 싣는 것이므로 그때는 잡는다.
    if "zones" not in d:
        print("      ✗ zones 칸이 없습니다 — 서버가 구역을 안 싣습니다")
        return 1
    zs = d.get("zones") or []
    print(f"    ✓ 겹친 지구·구역 {len(zs)}개"
          + ("".join(f"\n        · {z.get('label')}"
                     f"{' ' + str(z.get('detail')) if z.get('detail') else ''}"
                     for z in zs) if zs else " (이 필지에는 걸린 것이 없음)"))
    return 0


def main() -> int:
    print(f"BASE={BASE}\n")
    bad = lines() + parcel()
    print()
    if bad:
        print(f"::error::라이브에서 {bad}건이 어긋납니다")
        return 1
    print("라이브 확인 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
