"""지번 → 필지 (PNU) 길 탐침 (2026-09-11).

브이월드 지오코더(req/address)는 주소 DB 기반이라 **건물 없는 땅의 지번을
못 찾는다** (실측: 곤지암읍 건업리 140-25 NOT_FOUND, 140 → 140-1 로 뭉갬).
땅을 보는 서비스라 그 길로는 부족하다. 대안 둘을 브이월드 입으로 확인한다:

  A. WFS 연속지적도(lp_pa_cbnd_bubun)를 **pnu 로 걸러** 받을 수 있나
     (CQL_FILTER · FILTER(OGC) · FEATUREID). 되면 법정동코드 + 지번으로
     PNU 를 만들어 도형을 바로 받는다.
  B. 검색 API(req/search, category=parcel)가 지번을 PNU·좌표로 주나.

서울 중계기(api/relay)를 거친다 — 키는 중계기에만 있고, 응답 안의 키는
로그로 나가기 전에 지운다 (parcel_probe.py 와 같은 꼴).
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE", "https://toji.fyi")
TOKEN = os.environ.get("TOKEN", "")
# 건업리 (places.json 의 중심점). 여기 한 칸의 pnu 앞 10자리가 법정동코드다.
LAT = float(os.environ.get("LAT", "37.4028"))
LON = float(os.environ.get("LON", "127.39476"))
QUERY = os.environ.get("QUERY", "경기도 광주시 곤지암읍 건업리 140-25")
BON = os.environ.get("BON", "140")
BU = os.environ.get("BU", "25")
HALF = 0.0006

HIDE = re.compile(r'(?i)((?:key|apikey|servicekey)=)[^&"\s<]+')


def show(text: str, n: int = 600) -> str:
    return " ".join(HIDE.sub(r"\1(가림)", text)[:n].split())


def relay(target: str) -> tuple[int, str]:
    url = f"{BASE}/api/relay?target={urllib.parse.quote(target, safe='')}"
    req = urllib.request.Request(url, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


WFS = "https://api.vworld.kr/req/wfs?"
COMMON = ("SERVICE=WFS&REQUEST=GetFeature&VERSION=1.1.0&SRSNAME=EPSG:4326"
          "&OUTPUT=application/json&TYPENAME=lp_pa_cbnd_bubun&DOMAIN=https://toji.fyi/")


def main() -> int:
    if not TOKEN:
        print("::error::중계기 토큰이 없습니다")
        return 1
    # 0. 이 자리의 필지 몇 개 → 법정동코드
    bbox = f"{LON - HALF},{LAT - HALF},{LON + HALF},{LAT + HALF}"
    code, body = relay(f"{WFS}{COMMON}&BBOX={bbox}&MAXFEATURES=5")
    print(f"── 0. bbox 로 pnu 보기 ── http={code} {len(body)}B")
    pnus = []
    try:
        feats = json.loads(body).get("features", [])
        for f in feats:
            p = f.get("properties", {})
            pnus.append(str(p.get("pnu", "")))
            print("   pnu", p.get("pnu"), "addr", p.get("addr"), "jibun", p.get("jibun"))
    except Exception:  # noqa: BLE001
        print("   ", show(body))
    ld = (pnus[0][:10] if pnus and len(pnus[0]) >= 10 else "")
    print(f"   법정동코드 추정: {ld or '(못 읽음)'}")
    if not ld:
        return 0
    pnu = f"{ld}1{int(BON):04d}{int(BU):04d}"
    print(f"   찾을 PNU: {pnu}")

    cases = [
        ("A1. CQL_FILTER=pnu='…'", f"{WFS}{COMMON}&MAXFEATURES=5&CQL_FILTER={urllib.parse.quote(chr(112)+'nu='+chr(39)+pnu+chr(39))}"),
        ("A2. FILTER (OGC PropertyIsEqualTo)",
         f"{WFS}{COMMON}&MAXFEATURES=5&FILTER=" + urllib.parse.quote(
             "<Filter><PropertyIsEqualTo><PropertyName>pnu</PropertyName>"
             f"<Literal>{pnu}</Literal></PropertyIsEqualTo></Filter>")),
        ("A3. FEATUREID=lp_pa_cbnd_bubun.<pnu>",
         f"{WFS}{COMMON}&FEATUREID=lp_pa_cbnd_bubun.{pnu}"),
        ("A4. 속성 파라미터 pnu=… (비표준)", f"{WFS}{COMMON}&MAXFEATURES=5&pnu={pnu}"),
        ("B1. 검색 API category=parcel",
         "https://api.vworld.kr/req/search?service=search&request=search&version=2.0"
         f"&type=address&category=parcel&format=json&size=5&query={urllib.parse.quote(QUERY)}"),
        ("B2. 검색 API category=road", 
         "https://api.vworld.kr/req/search?service=search&request=search&version=2.0"
         f"&type=address&category=road&format=json&size=5&query={urllib.parse.quote(QUERY)}"),
    ]
    for label, target in cases:
        code, body = relay(target)
        print(f"── {label} ── http={code} {len(body)}B")
        try:
            j = json.loads(body)
            feats = j.get("features")
            if feats is not None:
                print(f"   features {len(feats)}개:",
                      [(f.get('properties', {}).get('pnu'), f.get('properties', {}).get('addr')) for f in feats[:3]])
                continue
            resp = j.get("response", {})
            print("   status", resp.get("status"), "record", resp.get("record"))
            items = (resp.get("result") or {}).get("items") or []
            for it in items[:5]:
                print("   ", {k: it.get(k) for k in ("id", "title", "point", "address") if k in it})
            if resp.get("error"):
                print("   error", resp.get("error"))
        except Exception:  # noqa: BLE001
            print("   ", show(body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
