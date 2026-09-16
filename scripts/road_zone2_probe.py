"""B 를 확인하고 A 에 쓸 칸 이름을 확보한다 (2026-09-16).

지시: "B는 이미 있습니다. B확인하고 A 진행해 주세요."

활용신청이 이미 되어 있다면 `NO_OPENAPI_SERVICE_ERROR`(returnReasonCode
12)는 **키 문제가 아니다.** 그 코드는 '해당 서비스가 없음' 이고, 키 문제는
따로 30(SERVICE_KEY_IS_NOT_REGISTERED)로 온다. 즉 **내가 적은 주소가
틀렸다.** 지난번에는 오류 본문을 190자로 잘라 찍어서 그것을 못 봤다.

이번에는 셋을 한다.

  B-1  오류 본문을 **통째로** 찍는다. 서버가 무엇이 틀렸는지 말해 준다.
  B-2  WFS 이름(typename)을 여럿 두드린다. F251 은 내가 고른 값이다.
  A-1  **getLandUseAttr 응답을 통째로** 찍어 칸 이름을 확보한다.
       '포함/접함' 이 어느 칸에 어떤 값으로 오는지 눈으로 봐야 A 를
       짤 수 있다. 추측하면 오늘처럼 또 틀린다.

그리고 **대조군을 함께 묻는다.** 받은 캡처의 도면에서 빨간 도로구역 안팎
지번을 골랐다. 안쪽만 '도로구역' 이 나오고 바깥은 안 나와야 맞는 것이다.

  python scripts/road_zone2_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
NED = "https://api.vworld.kr/ned/data/getLandUseAttr"
DOMAIN = os.environ.get("VWORLD_DOMAIN", "https://toji.fyi")

# 천안 북면 양곡리 = 4413133030. 일반 지번은 1, 산은 2.
UMD = "4413133030"
BOX = (36.835, 127.262, 36.862, 127.290)


def pnu(bon: int, bu: int = 0, san: bool = False) -> str:
    return f"{UMD}{'2' if san else '1'}{bon:04d}{bu:04d}"


# 받은 캡처의 도면에서 고른 지번들. 빨간 도로구역 안팎이 섞여 있다.
SPOTS = [
    ("361-7 전  (캡처에서 고른 필지)", pnu(361, 7)),
    ("361-4 전  (동쪽 바깥으로 보임)", pnu(361, 4)),
    ("468-5 답  (도로구역 안으로 보임)", pnu(468, 5)),
    ("산13-3 임 (산, 도로구역 가장자리)", pnu(13, 3, san=True)),
    ("359 전    (남동쪽 바깥, 대조군)", pnu(359, 0)),
]


def relay(url: str, params: dict | None = None, timeout: int = 60):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    target = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": target})


def bar(t: str) -> None:
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


def b_check() -> None:
    bar("B · 오류 본문을 통째로 본다 — 서버가 무엇이 틀렸는지 말해 준다")
    s, w, n, e = BOX
    tries = [
        ("NED WFS · F251", "https://api.vworld.kr/ned/wfs/getLandUseWFS",
         {"typename": "F251", "bbox": f"{w},{s},{e},{n}",
          "srsname": "EPSG:4326", "maxFeatures": "5",
          "key": "__via_relay__", "domain": DOMAIN}),
        ("NED WFS · 이름 없이", "https://api.vworld.kr/ned/wfs/getLandUseWFS",
         {"bbox": f"{w},{s},{e},{n}", "srsname": "EPSG:4326",
          "maxFeatures": "5", "key": "__via_relay__", "domain": DOMAIN}),
        ("NED WFS · GetCapabilities",
         "https://api.vworld.kr/ned/wfs/getLandUseWFS",
         {"service": "WFS", "request": "GetCapabilities",
          "key": "__via_relay__", "domain": DOMAIN}),
        ("NSDI attr (1611000)",
         "https://apis.data.go.kr/1611000/nsdi/LandUseService/attr/getLandUseAttr",
         {"pnu": SPOTS[0][1], "format": "json", "numOfRows": "10",
          "pageNo": "1"}),
        ("NSDI attr (1613000)",
         "https://apis.data.go.kr/1613000/nsdi/LandUseService/attr/getLandUseAttr",
         {"pnu": SPOTS[0][1], "format": "json", "numOfRows": "10",
          "pageNo": "1"}),
        ("NSDI 목록 확인 (서비스 뿌리)",
         "https://apis.data.go.kr/1611000/nsdi/LandUseService", None),
    ]
    for label, url, params in tries:
        try:
            r = relay(url, params)
        except Exception as err:                       # noqa: BLE001
            print(f"  {label:<26} 못 불렀다 — {type(err).__name__}")
            continue
        body = " ".join((r.text or "").split())
        print(f"  {label:<26} {r.status_code} · {len(r.text or ''):>6}B")
        # **자르지 않는다.** 지난번에 잘라서 까닭을 못 봤다.
        print(f"    {body[:700]}")
        print()


def a_fields() -> None:
    bar("A · getLandUseAttr 를 통째로 찍는다 — 칸 이름을 눈으로 확보한다")
    print("  '포함/접함' 이 어느 칸에 어떤 값으로 오는지 봐야 A 를 짠다.")
    print("  추측하면 오늘처럼 또 틀린다.")
    first = True
    for label, code in SPOTS:
        try:
            r = relay(NED, {"pnu": code, "format": "json",
                            "numOfRows": "100", "pageNo": "1",
                            "key": "__via_relay__", "domain": DOMAIN})
            obj = r.json()
        except Exception as err:                       # noqa: BLE001
            print(f"\n  {label:<30} 못 읽었다 — {type(err).__name__}")
            continue
        rows = (((obj or {}).get("landUses") or {}).get("field")) or []
        if first and rows:
            print()
            print("  ── 첫 줄을 통째로 (칸 이름 확인용) ──")
            print("  " + json.dumps(rows[0], ensure_ascii=False, indent=2)
                  .replace("\n", "\n  "))
            first = False
        print()
        print(f"  {label}  · PNU {code} · {len(rows)}줄")
        for row in rows:
            name = row.get("prposAreaDstrcCodeNm") or "?"
            # 저촉 칸이 무엇인지 모르므로 **관련 있어 보이는 칸을 다 찍는다.**
            extra = " ".join(f"{k}={v}" for k, v in row.items()
                             if k not in ("prposAreaDstrcCodeNm", "ldCode",
                                          "ldCodeNm", "mnnmSlno", "regstrSeCode",
                                          "regstrSeCodeNm", "lastUpdtDt"))
            print(f"    {name:<24}{extra[:90]}")


def main() -> None:
    b_check()
    a_fields()
    bar("무엇을 보고 판단하나")
    print("  · 오류 본문이 이름을 탓하면 → 이름만 바꾸면 면이 열린다")
    print("  · 오류 본문이 키를 탓하면 → 활용신청 쪽을 다시 봐야 한다")
    print("  · 도로구역이 안쪽 지번에만 나오면 → A 의 거르개가 맞는 것이다")
    print("  · 바깥 지번에도 나오면 → 저촉 칸으로 한 번 더 걸러야 한다")


if __name__ == "__main__":
    main()
