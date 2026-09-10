"""필지 경계선 타일이 왜 배율마다 똑같은가 — 재서 답한다.

2026-09-10 실측. /api/tile?layer=cadastral 이 z=14·15·17 에서 전부
같은 1,784B PNG(md5 29e79cc2)를 돌려줬다. 배율이 다르면 덮는 땅이
4배씩 달라지므로 선의 양도 달라야 한다. 같다는 것은 그림이 좌표를
안 보고 있다는 뜻이다.

여기서 세 갈래를 나눈다.

  ① 우리 쪽 문제인가  — 같은 길로 부르는 **용도지역**도 배율마다
     같은가. 다르면 bbox 계산과 라우팅은 멀쩡하다.
  ② 빈 그림인가      — PNG 를 뜯어 크기와 알파를 본다. 전부 투명
     하면 브이월드가 '그릴 것이 없다' 고 답한 것이다.
  ③ 이름이 틀린가    — WMS GetCapabilities 로 브이월드가 실제로
     여는 지적 레이어 이름을 받아 본다.

**로직을 워크플로에 쓰지 않는다.** 중첩 heredoc 으로 YAML 을 두 번
깨뜨렸다. 파이썬 파일이면 문법을 바로 잰다.
"""
from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import struct
import sys
import urllib.parse
import urllib.request
import zlib

BASE = os.environ.get("BASE", "https://toji.fyi")
TOKEN = os.environ.get("TOKEN", "")
TIMEOUT = 45

# 안성 한 점을 덮는 타일. 배율마다 좌표가 다르다.
TILES = [(14, 13984, 6376), (15, 27969, 12753), (17, 111877, 51013)]

PNG = b"\x89PNG\r\n\x1a\n"
MERC_EDGE = 20037508.342789244

# 키가 응답에 실려 올 수 있다 — 로그로 나가기 전에 지운다.
HIDE = re.compile(r'(?i)((?:key|apikey|servicekey)=)[^&"\s<]+')


def show(text: str, n: int = 420) -> str:
    return " ".join(HIDE.sub(r"\1(가림)", text)[:n].split())


def get(url: str, headers: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as exc:                                # noqa: BLE001
        print(f"    실패: {type(exc).__name__}: {exc}")
        return 0, b""


# ── ② PNG 를 뜯는다 ────────────────────────────────────────────
def png_facts(body: bytes) -> str:
    """폭·높이와 '전부 투명한가'. 라이브러리 없이 표준 PNG 만 읽는다."""
    if not body.startswith(PNG):
        return "PNG 아님"
    w = h = None
    bits = color = None
    idat = b""
    i = 8
    while i + 8 <= len(body):
        ln = struct.unpack(">I", body[i:i + 4])[0]
        kind = body[i + 4:i + 8]
        data = body[i + 8:i + 8 + ln]
        if kind == b"IHDR":
            w, h, bits, color = struct.unpack(">IIBB", data[:10])
        elif kind == b"IDAT":
            idat += data
        elif kind == b"IEND":
            break
        i += 12 + ln
    if w is None:
        return "IHDR 없음"
    note = f"{w}×{h} bits={bits} color={color}"
    # color 6 = RGBA. 알파만 본다. 그 밖의 꼴은 판정하지 않는다.
    if color != 6 or bits != 8:
        return note + " (알파 판정 안 함)"
    try:
        raw = zlib.decompress(idat)
    except zlib.error as exc:
        return note + f" (풀지 못함: {exc})"
    stride = w * 4
    opaque = 0
    prev = bytearray(stride)
    pos = 0
    for _ in range(h):
        if pos >= len(raw):
            break
        ft = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        # PNG 필터를 되돌린다. 안 되돌리면 알파가 엉뚱한 값이 된다.
        for xi in range(stride):
            a = line[xi - 4] if xi >= 4 else 0
            b = prev[xi]
            c = prev[xi - 4] if xi >= 4 else 0
            if ft == 1:
                line[xi] = (line[xi] + a) & 0xFF
            elif ft == 2:
                line[xi] = (line[xi] + b) & 0xFF
            elif ft == 3:
                line[xi] = (line[xi] + ((a + b) >> 1)) & 0xFF
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[xi] = (line[xi] + pr) & 0xFF
        opaque += sum(1 for xi in range(3, stride, 4) if line[xi] != 0)
        prev = line
    total = w * h
    pct = 100.0 * opaque / total if total else 0.0
    verdict = "완전히 투명 — 아무것도 안 그렸습니다" if opaque == 0 \
        else f"칠해진 화소 {opaque:,}개 ({pct:.2f}%)"
    return f"{note} · {verdict}"


# ── ① 우리 길이 멀쩡한가 ──────────────────────────────────────
def our_tiles(layer: str) -> list[str]:
    print(f"  /api/tile?layer={layer}")
    seen = []
    for z, x, y in TILES:
        code, body = get(f"{BASE}/api/tile?layer={layer}&z={z}&x={x}&y={y}")
        ink = hashlib.md5(body).hexdigest()[:8]
        seen.append(ink)
        print(f"    z={z:<3} http={code} {len(body):>6}B  {ink}")
        if layer == "cadastral":
            print(f"           {png_facts(body)}")
    same = len(set(seen)) == 1
    print(f"    → 배율마다 {'같은 그림입니다' if same else '다른 그림입니다'}")
    return seen


# ── ③ 브이월드가 실제로 여는 이름 ────────────────────────────
def bbox(z: int, x: int, y: int) -> str:
    size = (MERC_EDGE * 2) / 2 ** z
    min_x = -MERC_EDGE + x * size
    max_y = MERC_EDGE - y * size
    return ",".join(str(v) for v in (min_x, max_y - size, min_x + size, max_y))


def relay(target: str) -> tuple[int, bytes]:
    url = f"{BASE}/api/relay?target={urllib.parse.quote(target, safe='')}"
    return get(url, {"x-relay-token": TOKEN})


def capabilities() -> None:
    print("  WMS GetCapabilities — 그 레이어를 어떤 조건으로 여는가")
    if not TOKEN:
        print("    건너뜀 — 중계기 토큰이 없습니다")
        return
    code, body, _ = relay_bytes("https://api.vworld.kr/req/wms?"
                                "SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0")
    text = body.decode("utf-8", "replace")
    print(f"    http={code} {len(body):,}B")
    if code != 200:
        print("      " + show(text))
        return
    pairs = re.findall(r"<Name>([^<]+)</Name>\s*<Title>([^<]*)</Title>", text)
    hits = [(n, t) for n, t in pairs
            if "cbnd" in n.lower() or "지적" in t or "필지" in t]
    print(f"    레이어 {len(pairs):,}개 중 지적 후보 {len(hits)}개")
    for n, t in hits[:25]:
        print(f"      {n}  —  {t}")

    # 그 레이어를 감싸는 <Layer> 블록을 통째로 꺼낸다. 축척 제한
    # (MinScaleDenominator) 이나 좌표계 목록이 거기 적혀 있다.
    m = re.search(r"<Layer[^>]*>(?:(?!</?Layer\b).)*?"
                  r"<Name>lp_pa_cbnd_bubun</Name>.*?</Layer>", text, re.S)
    if not m:
        print("      그 이름을 감싸는 <Layer> 블록을 못 찾았습니다")
        return
    block = m.group(0)
    print(f"    <Layer> 블록 {len(block):,}B — 요점만 적습니다")
    for tag in ("CRS", "SRS", "MinScaleDenominator", "MaxScaleDenominator",
                "Style", "BoundingBox", "EX_GeographicBoundingBox"):
        found = re.findall(rf"<{tag}[^>]*>([^<]*)</{tag}>|<{tag}\b([^/>]*)/>",
                           block)
        vals = [(" ".join((a or b).split()))[:110] for a, b in found]
        vals = [v for v in vals if v]
        if vals:
            print(f"      {tag}: {', '.join(vals[:8])}"
                  + (" …" if len(vals) > 8 else ""))


def relay_bytes(target: str) -> tuple[int, bytes, str]:
    """중계기는 바이너리를 base64 로 감싸 준다 (api/relay.js). 벗겨 준다."""
    url = f"{BASE}/api/relay?target={urllib.parse.quote(target, safe='')}"
    code, body = get(url, {"x-relay-token": TOKEN})
    if body[:8] == PNG:
        return code, body, "png"
    text = body.decode("utf-8", "replace")
    if text[:20].startswith("iVBORw0KGgo"):
        try:
            return code, base64.b64decode(text), "png(base64)"
        except Exception:                                    # noqa: BLE001
            pass
    return code, body, "text"


def wms(layers: str, box: str, *, version: str = "1.3.0",
        crs: str = "EPSG:3857", styles: str = "", size: int = 256) -> str:
    """GetMap 한 장을 부르고, 칠해진 화소가 몇 개인지로 답한다."""
    axis = "CRS" if version == "1.3.0" else "SRS"
    q = (f"SERVICE=WMS&REQUEST=GetMap&VERSION={version}"
         f"&LAYERS={layers}&STYLES={styles}&{axis}={crs}"
         f"&BBOX={box}&WIDTH={size}&HEIGHT={size}"
         "&FORMAT=image/png&TRANSPARENT=true&EXCEPTIONS=XML")
    code, body, kind = relay_bytes("https://api.vworld.kr/req/wms?" + q)
    if kind == "text":
        return f"http={code} {len(body)}B  " + show(
            body.decode("utf-8", "replace"), 160)
    return f"http={code} {len(body)}B  {png_facts(body)}"


# 배율 15·17·19 의 그 자리를 덮는 네모. 축척 제한이 걸려 있으면
# 더 깊이 들어가야 선이 나온다 — 그것을 배제하려고 셋을 잰다.
DEEPER = [(15, 27969, 12753), (17, 111877, 51013), (19, 447508, 204053)]


def variants() -> None:
    """무엇을 바꾸면 선이 나오는가. 한 번에 여러 꼴을 재 본다."""
    print("  브이월드 WMS 직접 (중계기 경유) — 칠해진 화소로 판정합니다")
    if not TOKEN:
        print("    건너뜀 — 중계기 토큰이 없습니다")
        return
    z, x, y = DEEPER[0]
    box3857 = bbox(z, x, y)

    print("   · 레이어 이름을 바꿔 본다 (배율 15)")
    for name in ("lp_pa_cbnd_bubun", "lp_pa_cbnd_bonbun", "dt_d002"):
        print(f"     {name:<20} {wms(name, box3857)}")

    print("   · 더 깊이 들어가 본다 (축척 제한이 있는가)")
    for zz, xx, yy in DEEPER:
        print(f"     z={zz:<3} {wms('lp_pa_cbnd_bubun', bbox(zz, xx, yy))}")

    print("   · 좌표계와 판(version)을 바꿔 본다 (배율 15)")
    # WMS 1.3.0 의 EPSG:4326 은 축 순서가 위도,경도다. 3857 네모를
    # 위경도로 되돌려 그 순서로 넣는다.
    lon1, lat1, lon2, lat2 = deg_box(z, x, y)
    print(f"     1.1.1 SRS=3857     {wms('lp_pa_cbnd_bubun', box3857, version='1.1.1')}")
    print(f"     1.3.0 CRS=4326     "
          f"{wms('lp_pa_cbnd_bubun', f'{lat1},{lon1},{lat2},{lon2}', crs='EPSG:4326')}")
    print(f"     1.1.1 SRS=4326     "
          f"{wms('lp_pa_cbnd_bubun', f'{lon1},{lat1},{lon2},{lat2}', version='1.1.1', crs='EPSG:4326')}")
    print(f"     1.3.0 CRS=5179     {wms('lp_pa_cbnd_bubun', box3857, crs='EPSG:5179')}")


def deg_box(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """타일 좌표를 위경도 네모로. (서, 남, 동, 북)"""
    n = 2 ** z
    lon1 = x / n * 360.0 - 180.0
    lon2 = (x + 1) / n * 360.0 - 180.0
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    lat2 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon1, lat1, lon2, lat2


def main() -> int:
    print(f"BASE={BASE}\n")
    print("① 우리 길이 멀쩡한가 — 용도지역을 대조군으로 씁니다")
    zoning = our_tiles("zoning")
    cad = our_tiles("cadastral")
    print()
    print("② 브이월드가 그림을 주긴 하는가")
    variants()
    print()
    print("③ 이름이 맞는가")
    capabilities()
    print()

    zoning_varies = len(set(zoning)) > 1
    cad_varies = len(set(cad)) > 1
    print("판정:")
    if zoning_varies and not cad_varies:
        print("  용도지역은 배율마다 다른데 지적도만 같습니다 —")
        print("  bbox·라우팅·캐시는 멀쩡하고 **지적 레이어 쪽** 문제입니다.")
    elif not zoning_varies:
        print("  용도지역도 배율마다 같습니다 — 우리 쪽(bbox 또는 캐시)입니다.")
    else:
        print("  지적도도 배율마다 다릅니다 — 재현되지 않았습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
