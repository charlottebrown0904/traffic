"""고속도로 공사현황을 **실제로 불러** 지도에 그릴 수 있는지 본다.

엔드포인트(2026-09-16, 사용자가 확인해 준 명세):

  https://data.ex.co.kr/openapi/safeDriving/hiwayCnstnPrss
  key · type(json) · cmcnCstrClssCd(C02 시공 / C03 준공) ·
  numOfRows · pageNo · pagingYN

  routeName 노선명 · sectionName 구간명 · bizMgmtName 명칭 ·
  cnstnExtns 공사연장 · cnstnTerm 공사기간 · cmcnDate 준공날짜 ·
  cnstnStpntAddr 공사시점주소 · cnstnEnpntAddr 공사종점주소 ·
  cmcnCstrClss 준공시공구분 · cnsof 사업단

**여기서 갈린다.** 명세에 주소 칸이 있다고 그릴 수 있는 것은 아니다.
주소가 '경기도 화성시' 처럼 시·군까지만 오면 점이 시청에 찍히고, 그러면
구간이 아니라 거짓말이 된다. 그래서 세 가지를 잰다.

  1. 시공(C02)이 몇 건인가 — 한 자리 수면 화면에 층을 만들 값이 없다
  2. 주소가 **얼마나 깊은가** (시군구 / 읍면동 / 리 / 지번)
  3. 실제로 지오코딩되는가, 그리고 두 점 사이 거리가 **공사연장과 맞는가**
     — 이 검산이 핵심이다. 안 맞으면 엉뚱한 곳을 찍은 것이다.

  python scripts/road_work_probe.py
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.parse

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
EX = "https://data.ex.co.kr/openapi/safeDriving/hiwayCnstnPrss"
VW = "https://api.vworld.kr/req/address"


def relay(url: str, timeout: int = 60):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": url})


def fetch(cls_cd: str | None, rows: int = 100, page: int = 1):
    q = {"key": "__via_relay__", "type": "json",
         "numOfRows": str(rows), "pageNo": str(page), "pagingYN": "Y"}
    if cls_cd:
        q["cmcnCstrClssCd"] = cls_cd
    r = relay(f"{EX}?{urllib.parse.urlencode(q)}")
    try:
        return r.json(), None
    except Exception:                                  # noqa: BLE001
        return None, f"{r.status_code} {r.text[:200]}"


def depth(addr: str) -> str:
    """주소가 어디까지 적혀 있나. 지번이 있으면 점을 정확히 찍는다."""
    a = (addr or "").strip()
    if not a:
        return "빈칸"
    if re.search(r"\d+(-\d+)?\s*(번지)?$", a):
        return "지번"
    if re.search(r"(리|동)\s*$", a):
        return "리·동"
    if re.search(r"(읍|면)\s*$", a):
        return "읍·면"
    if re.search(r"(시|군|구)\s*$", a):
        return "시군구"
    return f"기타({a[-6:]})"


def geocode(addr: str):
    q = {"service": "address", "request": "getcoord", "version": "2.0",
         "crs": "EPSG:4326", "type": "PARCEL", "format": "json",
         "address": addr, "key": "__via_relay__"}
    try:
        r = relay(f"{VW}?{urllib.parse.urlencode(q)}")
        d = r.json()
        pt = (((d or {}).get("response") or {}).get("result") or {}).get("point")
        if pt:
            return float(pt["y"]), float(pt["x"])
    except Exception:                                  # noqa: BLE001
        pass
    return None


def km(a, b) -> float:
    la1, lo1 = a
    la2, lo2 = b
    dla = math.radians(la2 - la1)
    dlo = math.radians(lo2 - lo1)
    h = (math.sin(dla / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2))
         * math.sin(dlo / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def rows_of(body) -> list[dict]:
    if not isinstance(body, dict):
        return []
    for k in ("list", "hiwayCnstnPrssLists", "result", "items"):
        v = body.get(k)
        if isinstance(v, list):
            return v
    # 모르면 리스트인 값을 아무거나 집는다 — 이름이 바뀌어도 살아남게.
    for v in body.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def main() -> None:
    print("=" * 72)
    print("고속도로 공사현황 — 몇 건이고 주소가 얼마나 깊은가")
    print("=" * 72)

    body, err = fetch(None, rows=1)
    if err:
        sys.exit(f"  ✗ 못 불렀다: {err}")
    print(f"  머리: { {k: v for k, v in body.items() if not isinstance(v, list)} }")

    got = {}
    for cd, label in (("C02", "시공(공사중)"), ("C03", "준공(끝남)"), (None, "전체")):
        body, err = fetch(cd, rows=100)
        if err:
            print(f"  {label:14s} ✗ {err}")
            continue
        rs = rows_of(body)
        total = body.get("count") or body.get("totalCount") or "?"
        print(f"  {label:14s} 이 쪽 {len(rs):3d}건 · 전체 {total}")
        got[cd or "ALL"] = rs

    work = got.get("C02") or got.get("ALL") or []
    if not work:
        sys.exit("  시공 건이 하나도 없다 — 여기서 멈춘다")

    print(f"\n  칸 이름: {sorted(work[0])}")
    print("\n  보기 다섯:")
    for r in work[:5]:
        print(f"    {r.get('routeName')} · {r.get('sectionName')}")
        print(f"      명칭 {r.get('bizMgmtName')} · 연장 {r.get('cnstnExtns')}"
              f" · 기간 {r.get('cnstnTerm')} · 준공 {r.get('cmcnDate')}")
        print(f"      시점 {r.get('cnstnStpntAddr')}")
        print(f"      종점 {r.get('cnstnEnpntAddr')}")

    # ── 주소가 얼마나 깊은가 ─────────────────────────────────────
    print("\n" + "=" * 72)
    print("주소 깊이 — 지번까지 오면 점을 정확히 찍는다")
    print("=" * 72)
    from collections import Counter                    # noqa: PLC0415
    c = Counter()
    for r in work:
        c[depth(r.get("cnstnStpntAddr"))] += 1
        c[depth(r.get("cnstnEnpntAddr"))] += 1
    for k, v in c.most_common():
        print(f"    {k:10s} {v}개")

    # ── 진짜로 지오코딩되고, 거리가 공사연장과 맞는가 ────────────
    print("\n" + "=" * 72)
    print("지오코딩 + 검산 — 두 점 사이 거리가 공사연장과 맞는가")
    print("=" * 72)
    ok = bad = miss = 0
    for r in work[:12]:
        s = geocode(r.get("cnstnStpntAddr") or "")
        e = geocode(r.get("cnstnEnpntAddr") or "")
        name = f"{r.get('routeName')} {r.get('sectionName')}"[:34]
        if not s or not e:
            miss += 1
            print(f"    {name:36s} ✗ 좌표 못 얻음 (시점 {bool(s)} 종점 {bool(e)})")
            continue
        d = km(s, e)
        try:
            ext = float(re.sub(r"[^0-9.]", "", str(r.get("cnstnExtns") or "")) or 0)
        except ValueError:
            ext = 0
        # 직선거리는 실제 연장보다 짧다(길은 굽는다). 0.5~1.2배면 맞는 것으로 본다.
        good = ext > 0 and 0.5 <= d / ext <= 1.2
        ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
        print(f"    {name:36s} 직선 {d:6.1f}km · 연장 {ext:6.1f}km"
              f" · 비 {d / ext if ext else 0:4.2f} {'✓' if good else '✗'}")
    print(f"\n    맞음 {ok} · 어긋남 {bad} · 좌표 못 얻음 {miss}")


if __name__ == "__main__":
    main()
