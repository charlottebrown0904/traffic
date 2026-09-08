"""토지의 **도로접·모양**을 알 수 있는 자료가 있는가.

사장님 지시(2026-09-07): "토지의 경우 개발 가능 지, 모양, 도로 접등의
사유로 가격 변동이 많으니 (…) 실거래 내용에 도로접하거나 토지의 모양등을
알 수 있는 지도 확인해 주세요."

**기억으로 답하지 않는다.** 이 저장소는 레이어 이름을 세 번 틀렸고
(api/tile.js), 공시지가 원천도 추측으로 시작했다가 헛돌았다. 두 곳에
실제로 무엇이 오는지 받아서 필드를 통째로 찍는다.

  1. 실거래 토지 API (15126466)  — 우리가 안 읽고 버리는 칸이 있는가
  2. 브이월드 토지특성 WFS(dt_d194) — 도로접면·형상이 오는가

2번이 핵심이다. docs/land-price-fallback.md 가 이 WFS 로 공시지가·용도
지역·지목·면적·좌표가 온다고 적었지만, 도로접면과 형상은 **적혀 있지
않다.** 안 오는 것인지 그때 안 적은 것인지는 받아 봐야 안다.

  python scripts/land_shape_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vworld_landprice import fetch, parse_features, why    # noqa: E402

# 브이월드 콘솔에 등록된 서비스 주소. 배포 주소가 바뀌면
# 콘솔에도 더해야 한다 (2026-09-08 사도 토지 → 토지 고고).
DOMAIN = os.environ.get("VWORLD_DOMAIN", "toji-gogo.vercel.app")
NED = "https://api.vworld.kr/ned/wfs/getLandCharacteristicsWFS"
RTMS = ("https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade"
        "/getRTMSDataSvcLandTrade")

# 화성 향남 일대. 계획관리·공장이 실제로 많은 곳이라 0건이면 코드 문제다.
BBOX = "126.87,37.06,126.93,37.11"

# 찾는 것. 이름이 무엇으로 오는지 모르므로 **뜻으로** 훑는다.
WANTED = {
    "도로접면": ("road", "도로"),
    "형상": ("frm", "형상", "shape"),
    "지세·고저": ("hg", "고저", "지세", "tpgrph"),
    "토지이용상황": ("use_sittn", "이용상황"),
    "맹지 여부": ("맹지",),
}


def hits(name: str, value: str) -> list[str]:
    """이 칸이 우리가 찾는 것 중 무엇에 걸리는가."""
    hay = f"{name} {value}".lower()
    return [label for label, needles in WANTED.items()
            if any(n.lower() in hay for n in needles)]


def show(title: str, rows: list[dict]) -> None:
    print(f"\n{'=' * 66}\n{title}\n{'=' * 66}")
    if not rows:
        print("  피처가 없습니다.")
        return
    row = rows[0]
    print(f"  칸 {len(row)}개 (첫 피처 기준)\n")
    found: dict[str, str] = {}
    for k, v in sorted(row.items()):
        got = hits(k, v)
        mark = f"   ← {'·'.join(got)}" if got else ""
        for label in got:
            found.setdefault(label, f"{k} = {v}")
        print(f"    {k:<26} {str(v)[:44]}{mark}")

    print("\n  찾던 것:")
    for label in WANTED:
        print(f"    {label:<14} {found.get(label, '**없음**')}")


def probe_ned() -> None:
    body = fetch(NED, {
        "key": os.environ.get("VWORLD_KEY", ""),
        "domain": DOMAIN,
        "typename": "dt_d194",
        "bbox": BBOX,
        "srsName": "EPSG:4326",
        # GML 로 요청하면 중계기가 죽는다 (docs/land-price-fallback.md).
        "output": "application/json",
        "maxFeatures": "3",
        "resultType": "results",
    })
    reason = why(body)
    if reason:
        print(f"\n  ⚠ 토지특성 WFS 응답: {reason}")
    show("2. 브이월드 토지특성 WFS (dt_d194)", parse_features(body))


def probe_rtms() -> None:
    """실거래 토지 API 가 주는 칸을 **하나도 빼지 않고** 본다.

    우리 파서(collect/rtms.py)는 아는 이름만 골라 담는다. 그래서 API 가
    도로접·형상을 주고 있어도 조용히 버려졌을 수 있다.
    """
    # 한 조합만 시도했다가 'OK · totalCount 0' 을 받고 아무것도 못 봤다.
    # 그 시군구·그 달에 거래가 없었을 뿐인데 'API 에 없다' 로 읽힐 뻔했다.
    # 거래가 실제로 있을 만한 곳·달을 몇 개 돌려 **하나라도 걸리게** 한다.
    combos = [("41500", "202405"),   # 이천시 (남이천 IC 가 있는 곳)
              ("41500", "202310"),
              ("41590", "202305"),   # 화성시
              ("41220", "202404"),   # 평택시
              ("11680", "202404")]   # 서울 강남 — 거래가 없을 리 없다
    body, used = "", None
    for code, ym in combos:
        body = fetch(RTMS, {
            "serviceKey": os.environ.get("DATA_GO_KR_KEY", ""),
            "LAWD_CD": code, "DEAL_YMD": ym,
            "pageNo": "1", "numOfRows": "3",
        })
        if "<item>" in body:
            used = (code, ym)
            break
        print(f"    {code}/{ym} — 거래 0건, 다음 조합을 봅니다")
    if used:
        print(f"\n  {used[0]}/{used[1]} 에서 받았습니다")
    reason = why(body)
    if reason:
        print(f"\n  ⚠ 실거래 API 응답: {reason}")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        print("\n  실거래 응답이 XML 이 아닙니다. 받은 것 앞머리:")
        print("   ", body[:300].replace("\n", " "))
        return
    items = root.findall(".//item")
    rows = [{c.tag: (c.text or "").strip() for c in it if (c.text or "").strip()}
            for it in items]
    if not rows:
        # **실패를 삼키지 않는다.** 첫 실행에서 '피처가 없습니다' 만 찍고
        # 끝나 원인을 알 수 없었다. 응답이 오류인지 진짜 0건인지는
        # 본문을 봐야 갈린다.
        print("\n  item 이 0개입니다. 응답에서 무엇이 왔는지 봅니다:")
        for tag in ("resultCode", "resultMsg", "returnReasonCode",
                    "returnAuthMsg", "errMsg", "totalCount"):
            got = root.find(f".//{tag}")
            if got is not None:
                print(f"    {tag} = {(got.text or '').strip()}")
        print("    본문 앞머리:", body[:300].replace("\n", " "))
    show("1. 실거래 토지 API (15126466) — 원본 칸 전부", rows)


if __name__ == "__main__":
    print("토지의 도로접·모양을 알 수 있는가 — 두 원천을 받아서 확인")
    probe_rtms()
    probe_ned()
    print("\n※ '없음' 이면 그 원천에는 없다는 뜻입니다. 다른 길을 찾아야 합니다.")
