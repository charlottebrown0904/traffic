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
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
# 브이월드 콘솔에 등록된 서비스 주소. 배포 주소가 바뀌면
# 콘솔에도 더해야 한다 (2026-09-08 사도 토지 → 토지 고고).
DOMAIN = os.environ.get("VWORLD_DOMAIN", "toji-gogo.vercel.app")

# 화성 향남 일대. 계획관리·공장이 실제로 많은 곳이라 0건이면 코드 문제다.
BBOX = "126.87,37.06,126.93,37.11"

TARGETS = [
    ("getIndvdLandPriceWFS", "dt_d150", "개별공시지가"),
    ("getLandCharacteristicsWFS", "dt_d194", "토지특성"),
]

YEARS = ["2018", "2020", "2022", "2024", "2025"]

# 앞선 실행에서 실제로 나온 필지들. 화성·평택 두 곳을 섞었다.
PNUS = [
    "4122025923100080085",   # 평택 — 2024년부터만 나왔던 필지
    "4122025923100100010",
    "4122025923100130006",
    "4159134036200190003",   # 화성
    "4159134036200210001",
    "4159134036100350003",
]


def fetch(url: str, params: dict) -> str:
    """오류 응답이어도 본문을 돌려준다.

    urlopen 은 500 에서 예외를 던지는데, 그 예외 객체 안에 본문이 들어
    있다. 그것을 읽지 않고 상태 코드만 적으면 서버가 무엇이 잘못됐다고
    말하는지 영영 못 본다. typename 을 알려준 것도 오류 본문이었다.
    """
    target = f"{url}?{urllib.parse.urlencode(params)}"
    relayed = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": target})
    req = urllib.request.Request(relayed, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return body if body.strip() else f"__ERR__ HTTP {exc.code} (본문 없음)"
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
    """WFS 응답에서 피처의 필드와 값을 뽑는다. GeoJSON 과 GML 둘 다 받는다."""
    stripped = body.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(body)
        except ValueError:
            return []
        out = []
        for feat in payload.get("features", []):
            row = dict(feat.get("properties") or {})
            geom = feat.get("geometry") or {}
            if geom.get("type"):
                row["__geom__"] = geom["type"]
                coords = geom.get("coordinates")
                # 좌표가 실제로 값이 있는지까지 봐야 한다. 형만 있고 비어
                # 있으면 지오코딩이 필요 없다는 말을 할 수 없다.
                flat = json.dumps(coords)[:60] if coords else ""
                if flat:
                    row["__coords__"] = flat
            out.append({k: str(v) for k, v in row.items() if v not in (None, "")})
        return out
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


# 되는 조합. output=application/json 이 결정적이었다. 나머지 표기는
# 중계기(Vercel)를 통과하지 못하고 FUNCTION_INVOCATION_FAILED 로 죽는다.
BASE_PARAMS = {
    "typename": None,          # 호출 때 채운다
    "bbox": None,
    "maxFeatures": "3",
    "resultType": "results",
    "srsName": "EPSG:4326",
    "output": "application/json",
    "domain": DOMAIN,
}

# 500 은 인자 문제다. 무엇이 다른지 하나씩 갈라 본다.
VARIANTS = [({}, "기본")]


def call(op: str, typename: str, extra: dict | None = None) -> tuple[list[dict], str]:
    params = {**BASE_PARAMS, "typename": typename, "bbox": BBOX, **(extra or {})}
    params = {k: v for k, v in params.items() if v is not None}
    body = fetch(f"https://api.vworld.kr/ned/wfs/{op}", params)
    msg = why(body)
    if msg:
        return [], msg
    feats = parse_features(body)
    if not feats:
        return [], re.sub(r"\s+", " ", body[:220])
    return feats, ""


def attr_years(pnu: str) -> None:
    """한 필지의 연도별 공시지가를 속성 API 로 받아 본다.

    WFS 는 stdrYear 를 무시하고 현재 스냅샷만 준다(확인됨). 변화량을
    보려면 시계열이 필요하고, 국가중점데이터의 속성 조회는 보통 한
    필지의 연도별 목록을 돌려준다. 그것이 사실인지 확인한다.
    """
    print(f"\n===== 속성 조회로 연도별이 오는가  pnu={pnu} =====")
    # 몇 년치가 실제로 있는지가 이 축의 성패를 가른다. 연도 FE 를 넣는
    # 패널 회귀에 두세 해로는 못 들어간다. 전 구간을 훑는다.
    found: list[str] = []
    probes = [({}, "연도 없이")]
    probes += [({"stdrYear": str(y)}, f"{y}") for y in range(2010, 2027)]
    for extra, label in probes:
        params = {"pnu": pnu, "format": "json", "numOfRows": "200", "pageNo": "1",
                  "domain": DOMAIN, **extra}
        body = fetch("https://api.vworld.kr/ned/data/getIndvdLandPriceAttr", params)
        msg = why(body)
        if msg:
            print(f"  [{label:14s}] {msg[:110]}")
            continue
        try:
            payload = json.loads(body)
        except ValueError:
            head = re.sub(r"\s+", " ", body[:150])
            print(f"  [{label:14s}] JSON 아님: {head}")
            continue
        rows = _rows(payload)
        years = [(r.get("stdrYear") or r.get("stdr_year") or "?",
                  r.get("pblntfPclnd") or r.get("pblntf_pclnd") or "?") for r in rows]
        if label == "연도 없이":
            print(f"  [연도 없이] {len(rows)}건  " +
                  ", ".join(f"{y}:{v}" for y, v in years[:14]))
        elif rows:
            found.append(label)
    print(f"  → 확보 연도 {len(found)}개: "
          + (", ".join(found) if found else "없음"))


def _rows(payload) -> list[dict]:
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
            if isinstance(value, dict):
                got = _rows(value)
                if got:
                    return got
    return []


def main() -> None:
    if not RELAY or not TOKEN:
        sys.exit("RELAY_URL / RELAY_TOKEN 이 필요합니다.")
    global BBOX
    if len(sys.argv) > 1:
        BBOX = sys.argv[1]
    print(f"bbox {BBOX} (화성 향남 일대)\n")

    for op, typename, label in TARGETS:
        print(f"===== {label}  {op}  typename={typename} =====")
        feats, msg = None, None
        for extra, vlabel in VARIANTS:
            f, m = call(op, typename, extra)
            print(f"  [{vlabel:14s}] " + (f"피처 {len(f)}개" if f else m[:120]))
            if f and feats is None:
                feats, msg = f, ""
        if not feats:
            print("   되는 조합이 없습니다.\n")
            continue
        fields = sorted({k for f in feats for k in f})
        print(f"  피처 {len(feats)}개 · 필드 {len(fields)}개")
        print("  필드:", ", ".join(fields))
        judge(fields)
        print("  표본 1건:")
        for k, v in list(feats[0].items())[:24]:
            print(f"    {k:24s} {v[:60]}")

        # 연도별로 되는지. 건수만 세면 안 된다 — 서버가 stdrYear 를 무시하고
        # 같은 자료를 돌려줘도 건수는 똑같이 나온다. 같은 필지의 값이 해마다
        # 실제로 달라지는지까지 봐야 '연도별로 된다' 고 말할 수 있다.
        print("  연도별 (같은 필지의 공시지가가 실제로 달라지는가):")
        seen: dict[str, dict[str, str]] = {}
        for y in YEARS:
            f2, m2 = call(op, typename, {"stdrYear": y})
            if m2:
                print(f"    {y}  {m2[:80]}")
                continue
            for row in f2:
                pnu = row.get("pnu", "")
                if pnu:
                    seen.setdefault(pnu, {})[y] = (
                        row.get("pblntf_pclnd") or row.get("stdr_year") or "-")
            got = f2[0] if f2 else {}
            print(f"    {y}  {len(f2)}건  응답연도={got.get('stdr_year', '?')}"
                  f"  값={got.get('pblntf_pclnd', '?')}")

        for pnu, byyear in list(seen.items())[:3]:
            vals = [byyear.get(y, "-") for y in YEARS]
            verdict = "값이 해마다 다름 ○" if len(set(vals) - {"-"}) > 1 else "전부 같음 ✗"
            print(f"    {pnu}  {' / '.join(vals)}   {verdict}")
        print()

    # WFS 가 현재 스냅샷만 준다는 것이 확인됐다. 시계열은 다른 데서 와야 한다.
    #
    # 필지 하나로 판단하면 안 된다. 2024년부터만 나온 그 필지는 그해에
    # 신설·분할됐을 수 있고(2024→2025 값이 152% 뛰었다), 그러면 API 한계가
    # 아니라 그 필지의 사정이다. 여러 곳을 봐야 갈린다.
    for pnu in PNUS:
        attr_years(pnu)


if __name__ == "__main__":
    main()
