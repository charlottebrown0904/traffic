"""브이월드가 어떤 레이어를 열어두었는지 WFS 표준으로 직접 묻는다.

포털·브이월드 페이지는 자바스크립트로 그려져 레이어 이름이 긁히지 않았다.
그런데 WFS 에는 서버가 가진 레이어 목록을 통째로 돌려주는 표준 요청
GetCapabilities 가 있다. 페이지를 긁을 이유가 없다 — 서버에 물으면 된다.

  python scripts/vworld_layers.py [찾을말 ...]

첫 인자가 `zoning` 이면 용도지역을 지도에 깔 경로를 갈라 본다
(scripts/vworld_zoning.py). 워크플로를 새로 만들지 않고 여기에 얹은
이유는, **workflow_dispatch 가 기본 브랜치에 있는 워크플로만 부르기
때문**이다. 새 워크플로를 이 브랜치에 올려도 GitHub 가 404 를 준다.
이 워크플로(vworld-layers.yml)는 main 에 있고, 체크아웃은 부른
브랜치를 하므로 이 파일의 새 코드가 그대로 돈다.

  python scripts/vworld_layers.py zoning
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
# 웹사이트 유형 키는 등록된 도메인에서 온 요청인지를 본다. 중계기가 Referer 를
# 실어 보내도록 고쳤고, 브이월드가 따로 받는 domain 파라미터도 같이 시험한다.
DOMAIN = "sado-toji.vercel.app"
BASE = {"SERVICE": "WFS", "REQUEST": "GetCapabilities"}

CANDIDATES = [
    # 일반 WFS. 177개가 오지만 공시지가는 여기 없다.
    ("https://api.vworld.kr/req/wfs", {**BASE, "VERSION": "2.0.0"}),
    # 국가중점데이터는 /ned 아래에 따로 있다. 대표님 키에 '국가중점 API' 가
    # 켜져 있고, 공시지가가 바로 그 국가중점데이터다.
    ("https://api.vworld.kr/ned/wfs", {**BASE, "VERSION": "2.0.0"}),
    ("https://api.vworld.kr/ned/wfs", {**BASE, "VERSION": "1.1.0"}),
    ("https://api.vworld.kr/ned/wfs", dict(BASE)),
]

# 목록이 안 나오면 오퍼레이션 이름을 직접 두드려 본다. 국가중점데이터는
# 데이터셋마다 오퍼레이션이 따로 있고 GetCapabilities 를 안 주기도 한다.
# 이름을 알아듣는지 못 알아듣는지는 응답이 갈라준다.
#   "잘못된 URL 입니다"(URL_TYPE) → 그런 오퍼레이션이 없다
#   500 또는 파라미터 오류        → 이름은 맞고 인자에서 걸렸다
NED_OPS = [
    # 개별공시지가 — 앞선 시험에서 이름을 알아들었다(500)
    "getIndvdLandPriceWFS", "getIndvdLandPriceAttr",
    # 토지특성 — 역시 알아들었다. 용도지역이 여기 들어 있을 수 있다
    "getLandCharacteristicsWFS", "getLandCharacteristicsAttr",
    # 표준지 — 아래 이름들은 아직 못 찾았다
    "getStdrLandPriceWFS", "getStandardLandPriceWFS", "getStdLandPriceWFS",
    "getPblntfLandPriceWFS", "getLandPriceWFS", "getStdLandWFS",
    "getStdrLandPriceAttr", "getPblntfPcWFS",
]

# 화성 향남 일대. 계획관리·공장이 실제로 많은 곳이다.
BBOX = "126.87,37.06,126.93,37.11"
PARAM_SETS = [
    ({"typename": "", "bbox": BBOX, "maxFeatures": "3", "resultType": "results",
      "srsName": "EPSG:4326", "output": "application/json", "domain": DOMAIN,
      "stdrYear": "2024"}, "bbox+연도"),
    ({"pnu": "4159025329106740000", "format": "json", "numOfRows": "3",
      "pageNo": "1", "domain": DOMAIN, "stdrYear": "2024"}, "pnu+연도"),
]


def why(body: str) -> str:
    """응답에서 서버가 하는 말만 뽑는다. 원문을 그대로 흘리면 안 읽힌다."""
    m = re.search(r'"resultMsg"\s*:\s*"([^"]*)"', body)
    if m:
        code = re.search(r'"resultCode"\s*:\s*"([^"]*)"', body)
        return f"{code.group(1) if code else ''} {m.group(1)}".strip()
    m = re.search(r'<ServiceException[^>]*code="([^"]*)"[^>]*>([^<]*)', body)
    if m:
        return f"{m.group(1)} {m.group(2).strip()}"
    if body.startswith("__ERR__"):
        return body[:90]
    if "FeatureCollection" in body or '"features"' in body:
        return f"★ 자료 옴 ({len(body):,}바이트)"
    return re.sub(r"\s+", " ", body[:110])


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


def _zoning_mode() -> bool:
    """`zoning` 으로 불렀으면 용도지역 경로 탐침으로 넘긴다."""
    if len(sys.argv) < 2 or sys.argv[1] != "zoning":
        return False
    import vworld_zoning
    raise SystemExit(vworld_zoning.main())


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


# 키가 죽은 것인지, WFS 에만 권한이 없는 것인지 갈라야 다음 수가 정해진다.
# 지오코더는 이미 쓰고 있으므로 그것으로 키의 생사를 확인한다.
def key_alive() -> None:
    print("[대조] 지오코더로 키 생사 확인")
    body = fetch("https://api.vworld.kr/req/address",
                 {"service": "address", "request": "getcoord", "version": "2.0",
                  "crs": "EPSG:4326", "type": "PARCEL",
                  "address": "경기도 화성시 향남읍 발안리 1"})
    if body.startswith("__ERR__"):
        print("   ", body[:200])
        return
    snippet = re.sub(r"\s+", " ", body[:300])
    print("   ", snippet)
    if '"status":"OK"' in body or "NOT_FOUND" in body:
        print("   → 키는 살아 있습니다. WFS 쪽 권한·도메인 문제입니다.")
    elif "INCORRECT_KEY" in body or "AUTH" in body.upper():
        print("   → 키 자체가 거부됩니다.")


def main() -> None:
    _zoning_mode()          # `zoning` 이면 여기서 갈라져 나간다
    if not RELAY or not TOKEN:
        sys.exit("RELAY_URL / RELAY_TOKEN 이 필요합니다.")
    needles = sys.argv[1:] or ["공시지가"]
    key_alive()
    print()

    for url, params in CANDIDATES:
        label = params.get("VERSION", "버전없음")
        if "DOMAIN" in params or "domain" in params:
            label += "+domain"
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
        if hits:
            return   # 찾았으면 끝
        # 목록은 왔지만 찾는 것이 없다. 다음 후보(/ned 등)를 마저 봐야 한다.
        # 첫 성공에서 멈추면 정작 필요한 곳을 시도조차 못 한다.
        print("   (여기엔 없음 — 다음 후보로)")

    print("\nGetCapabilities 로는 못 찾았습니다. 오퍼레이션을 직접 두드려 봅니다.\n")
    for op in NED_OPS:
        base = ("https://api.vworld.kr/ned/wfs" if op.endswith("WFS")
                else "https://api.vworld.kr/ned/data")
        for params, plabel in PARAM_SETS:
            q = dict(params)
            if "typename" in q:
                q["typename"] = op[3:-3] if op.endswith("WFS") else op[3:]
            body = fetch(f"{base}/{op}", q)
            print(f"  {base.rsplit('/', 1)[1]}/{op:28s} [{plabel}] {why(body)}")
            if "★" in why(body):
                print("    " + re.sub(r"\s+", " ", body[:600]))
                return


if __name__ == "__main__":
    main()
