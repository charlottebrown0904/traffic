"""공시지가 API 탐침 — 국토교통부_표준지공시지가 (NSDI 계열).

대표님이 2026-09-01 개발계정을 승인받으셨다. 파일을 받아 올리는 길이
아니라 API 로 바로 당겨올 수 있으면 지오코딩 대기열이 통째로 사라진다.

다만 NSDI 계열은 서비스 이름과 오퍼레이션 이름이 데이터셋마다 달라
추측이 위험하다. `ex_api.probe()` 와 같은 방식으로 **실제로 무엇이
되는지** 확인한다. 특히 두 가지를 가른다.

  attr — 속성만. 보통 PNU(19자리)를 요구한다. 필지 목록이 먼저 있어야
         하므로, 그것뿐이면 우리에겐 막다른 길이다.
  wfs  — 공간 질의. bbox 로 영역을 훑을 수 있고 좌표가 함께 온다.
         이쪽이 되면 지오코딩이 필요 없다.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from ..config import keys
from .http import get, polite_sleep

BASE = "https://apis.data.go.kr/1611000/nsdi"

# 서비스 이름 후보. NSDI 는 데이터셋마다 표기가 달라 몇 가지를 시험한다.
SERVICES = [
    "StandardLandPriceService",
    "StdrLandPriceService",
    "StdLandPriceService",
    "NsdiStandardLandPriceService",
    "IndvdLandPriceService",   # 개별공시지가 — 되는지 대조용
]

# (경로, 오퍼레이션 접미사)
SHAPES = [
    ("attr", "Attr"),
    ("wfs", "WFS"),
]

# 화성시 향남 일대. 계획관리·공장이 실제로 많은 곳이라 0건이 나오면
# 코드 문제이지 '그 지역에 없어서' 는 아니다.
SAMPLE_PNU = "4159025329106740000"
SAMPLE_BBOX = "126.87,37.06,126.93,37.11"
SAMPLE_SIGUNGU = "41590"


def _operation(service: str, suffix: str) -> str:
    """StandardLandPriceService + Attr → getStandardLandPriceAttr"""
    stem = re.sub(r"Service$", "", service)
    return f"get{stem}{suffix}"


def _param_sets(shape: str) -> list[tuple[dict, str]]:
    if shape == "wfs":
        return [
            ({"bbox": SAMPLE_BBOX, "crs": "EPSG:4326", "stdrYear": "2024"}, "bbox+연도"),
            ({"bbox": SAMPLE_BBOX, "crs": "EPSG:4326"}, "bbox"),
        ]
    return [
        ({"pnu": SAMPLE_PNU, "stdrYear": "2024"}, "pnu+연도"),
        ({"pnu": SAMPLE_PNU}, "pnu"),
        ({"ldCode": SAMPLE_SIGUNGU, "stdrYear": "2024"}, "시군구+연도"),
        ({"admCode": SAMPLE_SIGUNGU, "stdrYear": "2024"}, "admCode+연도"),
    ]


def _summarize(text: str) -> tuple[int, list[str], str]:
    """응답에서 (건수, 필드명, 메모) 를 뽑는다. JSON·XML 둘 다 받는다."""
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(text)
        except ValueError:
            return 0, [], "JSON 깨짐"
        return _walk_json(payload)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return 0, [], text[:120].replace("\n", " ")
    # 에러 응답이면 메시지를 그대로 보여준다.
    msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg")
    if msg:
        detail = root.findtext(".//returnReasonCode") or ""
        return 0, [], f"{msg} {detail}".strip()
    fields, count = [], 0
    for child in root.iter():
        kids = list(child)
        if len(kids) >= 3 and all(not list(k) for k in kids):
            fields = [_tag(k) for k in kids]
            count += 1
    return count, fields, ""


def _tag(el) -> str:
    return el.tag.split("}")[-1]


def _walk_json(payload) -> tuple[int, list[str], str]:
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return len(value), sorted(value[0].keys()), ""
            if isinstance(value, dict):
                n, f, m = _walk_json(value)
                if n:
                    return n, f, m
    return 0, [], json.dumps(payload, ensure_ascii=False)[:160]


# 우리가 답을 얻어야 하는 것들 (docs/land-price-fallback.md 의 '확인해야 할 것')
WANT_COORD = ("lon", "lat", "x", "y", "geom", "point", "coord", "posit")
WANT_YEAR = ("year", "stdr", "기준")
WANT_ZONE = ("lndcgr", "prpos", "use", "지목", "용도", "jimok", "spfc")


def _answers(fields: list[str]) -> list[str]:
    low = [f.lower() for f in fields]
    out = []
    for label, needles in (("좌표", WANT_COORD), ("연도", WANT_YEAR), ("용도지역", WANT_ZONE)):
        hit = [f for f, l in zip(fields, low) if any(n in l for n in needles)]
        out.append(f"{label} {'○ ' + ','.join(hit[:3]) if hit else '✗'}")
    return out


def probe(verbose: bool = True) -> list[dict]:
    key = keys().require("data_go_kr")
    findings: list[dict] = []

    for service in SERVICES:
        for shape, suffix in SHAPES:
            op = _operation(service, suffix)
            url = f"{BASE}/{service}/{shape}/{op}"
            for params, label in _param_sets(shape):
                row = {"service": service, "shape": shape, "params": label}
                try:
                    resp = get(url, {"serviceKey": key, "format": "xml",
                                     "numOfRows": 5, "pageNo": 1, **params},
                               timeout=25)
                    row["http"] = resp.status_code
                    n, fields, memo = _summarize(resp.text)
                    row.update(n_rows=n, fields=fields, memo=memo)
                    row["result"] = "OK" if n else "0건"
                except Exception as exc:  # noqa: BLE001 — 탐침이라 전부 받아 적는다
                    row["result"] = "실패"
                    row["memo"] = str(exc)[:140]
                findings.append(row)
                polite_sleep(0.25)
                if row.get("result") == "OK":
                    break  # 이 조합이 되면 나머지 파라미터는 볼 필요 없다

    if verbose:
        _report(findings)
    return findings


def _report(findings: list[dict]) -> None:
    print(f"{'서비스':30s} {'형태':5s} {'파라미터':12s} {'결과':5s} 건수  메모")
    print("-" * 100)
    for row in findings:
        print(f"{row['service']:30s} {row['shape']:5s} {row['params']:12s} "
              f"{row.get('result', ''):5s} {str(row.get('n_rows', '')):5s} "
              f"{row.get('memo', '')[:40]}")

    working = [r for r in findings if r.get("result") == "OK"]
    if not working:
        print("\n되는 조합이 없습니다.")
        print("  키가 아직 안 풀렸을 수 있습니다 — 개발계정은 승인 뒤 반영까지")
        print("  시간이 걸립니다. 메모의 오류 문구를 먼저 보세요.")
        print("  서비스 이름이 후보에 없을 수도 있습니다. 그때는 포털의")
        print("  '참고문서'(오퍼레이션 명세)를 받아 이름을 확인해야 합니다.")
        return

    print("\n=== 되는 조합 ===")
    for row in working:
        print(f"\n[{row['service']}/{row['shape']}] {row['params']} — {row['n_rows']}건")
        print("  필드: " + ", ".join(row["fields"]))
        print("  " + " | ".join(_answers(row["fields"])))

    if any(r["shape"] == "wfs" for r in working):
        print("\n▶ wfs 가 됩니다. bbox 로 영역을 훑을 수 있고 좌표가 함께 옵니다.")
        print("  지오코딩 단계가 통째로 필요 없어집니다.")
    else:
        print("\n▶ attr 만 됩니다. PNU 가 있어야 조회되므로 필지 목록을")
        print("  먼저 구해야 합니다. 파일(15004246) 경로를 다시 봐야 합니다.")
