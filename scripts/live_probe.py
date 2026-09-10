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

# 그 자리를 덮는 타일. 배율마다 좌표가 다르다.
TILES = [(15, 27969, 12753), (17, 111877, 51013)]

PNG = b"\x89PNG\r\n\x1a\n"


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as exc:                                # noqa: BLE001
        print(f"    실패: {type(exc).__name__}: {exc}")
        return 0, b""


def tiles() -> int:
    bad = 0
    print("  필지 경계선 타일 (배율 15 이상에서만 그린다)")
    for z, x, y in TILES:
        code, body = get(f"{BASE}/api/tile?layer=cadastral&z={z}&x={x}&y={y}")
        ok = code == 200 and body.startswith(PNG)
        print(f"    z={z:<3} http={code} {len(body):>6}B  {'✓ 그림' if ok else '✗'}")
        if not ok:
            bad += 1
            print("      " + " ".join(body[:200].decode("utf-8", "replace").split()))
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
    return 0


def main() -> int:
    print(f"BASE={BASE}\n")
    bad = tiles() + parcel()
    print()
    if bad:
        print(f"::error::라이브에서 {bad}건이 어긋납니다")
        return 1
    print("라이브 확인 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
