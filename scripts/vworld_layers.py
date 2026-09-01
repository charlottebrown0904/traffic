"""브이월드가 어떤 레이어를 열어두었는지 WFS 표준으로 직접 묻는다.

포털·브이월드 페이지는 자바스크립트로 그려져 레이어 이름이 긁히지 않았다.
그런데 WFS 에는 서버가 가진 레이어 목록을 통째로 돌려주는 표준 요청
GetCapabilities 가 있다. 페이지를 긁을 이유가 없다 — 서버에 물으면 된다.

  python scripts/vworld_layers.py [찾을말 ...]
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")

# 중계기가 key 를 끼워 넣으므로 이쪽에서는 비워 보낸다.
CANDIDATES = [
    ("https://api.vworld.kr/req/wfs", {"SERVICE": "WFS", "REQUEST": "GetCapabilities",
                                       "VERSION": "2.0.0"}),
    ("https://api.vworld.kr/req/wfs", {"SERVICE": "WFS", "REQUEST": "GetCapabilities",
                                       "VERSION": "1.1.0"}),
    ("https://api.vworld.kr/req/wfs", {"SERVICE": "WFS", "REQUEST": "GetCapabilities"}),
]


def fetch(url: str, params: dict) -> str:
    target = f"{url}?{urllib.parse.urlencode(params)}"
    relayed = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": target})
    req = urllib.request.Request(relayed, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return f"__ERR__ {type(exc).__name__} {exc}"


def tag(el) -> str:
    return el.tag.split("}")[-1]


def feature_types(xml_text: str) -> list[tuple[str, str]]:
    """(Name, Title) 목록. 네임스페이스가 버전마다 달라 태그 이름만 본다."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        if tag(el) != "FeatureType":
            continue
        name = title = ""
        for child in el:
            if tag(child) == "Name":
                name = (child.text or "").strip()
            elif tag(child) == "Title":
                title = (child.text or "").strip()
        if name:
            out.append((name, title))
    return out


def main() -> None:
    if not RELAY or not TOKEN:
        sys.exit("RELAY_URL / RELAY_TOKEN 이 필요합니다.")
    needles = sys.argv[1:] or ["공시지가"]

    for url, params in CANDIDATES:
        label = params.get("VERSION", "버전없음")
        body = fetch(url, params)
        if body.startswith("__ERR__"):
            print(f"[{label}] {body[:160]}")
            continue
        types = feature_types(body)
        print(f"[{label}] 길이 {len(body):,} · 레이어 {len(types)}개")
        if not types:
            # 오류 응답이면 무엇이라 하는지 그대로 본다. 추측하지 않는다.
            print("   본문 앞부분:", re.sub(r"\s+", " ", body[:400]))
            continue

        hits = [(n, t) for n, t in types
                if any(k in n or k in t for k in needles)]
        print(f"   '{' / '.join(needles)}' 걸린 것: {len(hits)}개")
        for n, t in hits[:40]:
            print(f"     {n:34s} {t}")
        if not hits:
            print("   전체 앞 40개:")
            for n, t in types[:40]:
                print(f"     {n:34s} {t}")
        return   # 되는 버전 하나면 충분하다

    print("\nGetCapabilities 가 되는 버전이 없습니다. 위 오류 문구를 먼저 보세요.")


if __name__ == "__main__":
    main()
