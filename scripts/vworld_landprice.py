"""개별공시지가·토지특성을 브이월드 WFS 로 실제로 받아 본다.

서버가 유효한 typename 을 직접 알려줬다.

  getIndvdLandPriceWFS       dt_d150   개별공시지가
  getLandCharacteristicsWFS  dt_d194   토지특성

확인할 것은 셋이다 (docs/land-price-fallback.md).
  1. 좌표가 함께 오는가  → 오면 지오코딩 대기열이 사라진다
  2. 연도별로 되는가      → 변화량을 보므로 한 해로는 못 쓴다
  3. 용도지역이 있는가    → 계획관리·생산관리·자연녹지 필터를 그대로 쓴다

  python scripts/vworld_landprice.py [bbox]
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
DOMAIN = "sado-toji.vercel.app"

# 화성 향남 일대. 계획관리·공장이 실제로 많은 곳이라 0건이면 코드 문제다.
BBOX = "126.87,37.06,126.93,37.11"

TARGETS = [
    ("getIndvdLandPriceWFS", "dt_d150", "개별공시지가"),
    ("getLandCharacteristicsWFS", "dt_d194", "토지특성"),
]

YEARS = ["2018", "2020", "2022", "2024", "2025"]


def fetch(url: str, params: dict) -> str:
    target = f"{url}?{urllib.parse.urlencode(params)}"
    relayed = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": target})
    req = urllib.request.Request(relayed, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return f"__ERR__ {type(exc).__name__} {exc}"


def why(body: str) -> str:
    m = re.search(r'"resultMsg"\s*:\s*"([^"]*)"', body)
    if m:
        code = re.search(r'"resultCode"\s*:\s*"([^"]*)"', body)
        return f"{code.group(1) if code else ''} {m.group(1)}".strip()
    m = re.search(r'<ServiceException[^>]*code="([^"]*)"[^>]*>([^<]*)', body)
    if m:
        return f"{m.group(1)} {m.group(2).strip()}"
    if body.startswith("__ERR__"):
        return body[:90]
    return ""


def tag(el) -> str:
    return el.tag.split("}")[-1]


def parse_features(body: str) -> list[dict]:
    """GML/WFS 응답에서 피처의 필드와 값을 뽑는다."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    feats = []
    for member in root.iter():
        if tag(member) not in ("featureMember", "member"):
            continue
        for node in member:
            row: dict[str, str] = {}
            for child in node.iter():
                if child is node:
                    continue
                name = tag(child)
                if list(child):          # 도형처럼 자식이 더 있는 것
                    if name in ("Point", "Polygon", "MultiPolygon", "MultiSurface",
                                "Surface", "LineString"):
                        row["__geom__"] = name
                    continue
                text = (child.text or "").strip()
                if text:
                    row.setdefault(name, text)
            if row:
                feats.append(row)
    return feats


# 우리가 답을 얻어야 하는 것
NEEDLE = {
    "좌표": ("__geom__", "posList", "coordinates", "pos", "lon", "lat", "x", "y"),
    "연도": ("year", "stdr", "기준"),
    "용도지역": ("prpos", "spfc", "use", "lndcgr", "jimok", "zone"),
    "가격": ("pblntf", "price", "amt", "pc"),
}


def judge(fields: list[str]) -> None:
    low = {f: f.lower() for f in fields}
    for label, needles in NEEDLE.items():
        hit = [f for f in fields if any(n.lower() in low[f] for n in needles)]
        print(f"    {label:6s} {'○ ' + ', '.join(hit[:4]) if hit else '✗'}")


def call(op: str, typename: str, extra: dict | None = None) -> tuple[list[dict], str]:
    params = {
        "typename": typename,
        "bbox": BBOX,
        "maxFeatures": "3",
        "resultType": "results",
        "srsName": "EPSG:4326",
        "domain": DOMAIN,
        **(extra or {}),
    }
    body = fetch(f"https://api.vworld.kr/ned/wfs/{op}", params)
    msg = why(body)
    if msg:
        return [], msg
    feats = parse_features(body)
    if not feats:
        return [], re.sub(r"\s+", " ", body[:200])
    return feats, ""


def main() -> None:
    if not RELAY or not TOKEN:
        sys.exit("RELAY_URL / RELAY_TOKEN 이 필요합니다.")
    global BBOX
    if len(sys.argv) > 1:
        BBOX = sys.argv[1]
    print(f"bbox {BBOX} (화성 향남 일대)\n")

    for op, typename, label in TARGETS:
        print(f"===== {label}  {op}  typename={typename} =====")
        feats, msg = call(op, typename)
        if msg:
            print("  ", msg)
            print()
            continue
        fields = sorted({k for f in feats for k in f})
        print(f"  피처 {len(feats)}개 · 필드 {len(fields)}개")
        print("  필드:", ", ".join(fields))
        judge(fields)
        print("  표본 1건:")
        for k, v in list(feats[0].items())[:24]:
            print(f"    {k:24s} {v[:60]}")

        # 연도별로 되는지. 변화량을 보므로 이게 안 되면 쓸 수 없다.
        print("  연도별:")
        for y in YEARS:
            f2, m2 = call(op, typename, {"stdrYear": y})
            print(f"    {y}  {len(f2)}건" + (f"  {m2[:70]}" if m2 else ""))
        print()


if __name__ == "__main__":
    main()
