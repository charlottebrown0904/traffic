"""한국도로공사 고속도로 공공데이터포털(data.ex.co.kr) API 클라이언트.

문제: 공공데이터포털의 '한국도로공사_실시간 영업소별 교통량'은 **실시간**이라
과거 시계열이 나오지 않는다. 과거 자료는 별도 경로로 받아야 한다.

이 모듈은 엔드포인트를 추측하지 않고 **실제로 무엇이 되는지 탐침(probe)** 한다.
포털 문서가 버전마다 달라 추측이 위험하기 때문이다.
"""
from __future__ import annotations

import json

from ..config import keys
from .http import get, polite_sleep

BASE = "https://data.ex.co.kr/openapi"

# 후보 엔드포인트. 실제 목록은 https://data.ex.co.kr/openapi/intro/introduce02
CANDIDATES = [
    ("business/curBusinessInfo", "영업소 마스터(좌표)"),
    ("trafficapi/trafficIc", "영업소 입출구 교통량"),
    ("trafficapi/trafficIC", "영업소 입출구 교통량(대문자)"),
    ("trafficapi/trafficAmountByRoute", "노선별 교통량"),
    ("trafficapi/trafficAmountByDay", "일자별 교통량"),
    ("trafficapi/trafficAmount", "교통량"),
    ("odtraffic/trafficAmountByOd", "OD 통행량"),
    ("safeopen/tcsinfo/tcsInfo", "TCS 정보"),
]

# 날짜 파라미터도 API마다 이름이 다르다. 되는 조합을 찾는다.
DATE_PARAM_SETS = [
    ({}, "날짜없음"),
    ({"stdDt": "20240101"}, "stdDt"),
    ({"sumDate": "20240101"}, "sumDate"),
    ({"strDate": "20240101", "endDate": "20240107"}, "strDate/endDate"),
    ({"stdHour": "00", "stdDt": "20240101"}, "stdDt+stdHour"),
]


def _summarize(payload) -> tuple[int, list[str]]:
    """응답에서 레코드 리스트를 찾아 (건수, 필드명) 반환."""
    if not isinstance(payload, dict):
        return 0, []
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return len(value), sorted(value[0].keys())
    return 0, []


def probe(verbose: bool = True) -> list[dict]:
    """모든 후보 엔드포인트 × 날짜 파라미터 조합을 시험하고 결과를 보고한다."""
    key = keys().require("ex")
    findings = []

    for path, label in CANDIDATES:
        for date_params, date_label in DATE_PARAM_SETS:
            params = {"key": key, "type": "json", "numOfRows": 5, "pageNo": 1, **date_params}
            row = {"endpoint": path, "label": label, "date_params": date_label}
            try:
                resp = get(f"{BASE}/{path}", params, timeout=20)
                row["http"] = resp.status_code
                try:
                    payload = resp.json()
                except (ValueError, json.JSONDecodeError):
                    row["result"] = "JSON 아님"
                    row["body"] = resp.text[:120]
                    findings.append(row)
                    continue
                n, fields = _summarize(payload)
                row["n_rows"] = n
                row["fields"] = fields
                row["result"] = "OK" if n else "0건"
                if not n:
                    row["body"] = json.dumps(payload, ensure_ascii=False)[:200]
            except Exception as exc:
                row["result"] = "실패"
                row["body"] = str(exc)[:160]
            findings.append(row)
            polite_sleep(0.2)
            # 이 엔드포인트가 날짜 없이도 잘 되면 나머지 조합은 건너뛴다
            if row.get("result") == "OK" and date_label == "날짜없음":
                break

    if verbose:
        print(f"{'엔드포인트':38s} {'날짜파라미터':14s} {'결과':6s} 건수")
        print("-" * 78)
        for row in findings:
            print(f"{row['endpoint']:38s} {row['date_params']:14s} "
                  f"{row.get('result', ''):6s} {row.get('n_rows', '')}")
        working = [r for r in findings if r.get("result") == "OK"]
        if working:
            print("\n=== 동작하는 엔드포인트의 필드 ===")
            seen = set()
            for row in working:
                if row["endpoint"] in seen:
                    continue
                seen.add(row["endpoint"])
                print(f"\n[{row['endpoint']}] {row['label']}  ({row['date_params']})")
                print("  " + ", ".join(row["fields"]))
        else:
            print("\n동작하는 엔드포인트가 없습니다. EX_API_KEY 를 확인하거나 "
                  "https://data.ex.co.kr/openapi/intro/introduce02 에서 목록을 확인하세요.")
    return findings


def fetch(path: str, params: dict, rows: int = 1000, max_pages: int = 100) -> list[dict]:
    """페이지네이션하며 레코드를 모은다."""
    collected: list[dict] = []
    for page in range(1, max_pages + 1):
        resp = get(f"{BASE}/{path}",
                   {"key": keys().require("ex"), "type": "json",
                    "numOfRows": rows, "pageNo": page, **params})
        try:
            payload = resp.json()
        except ValueError:
            break
        n, _ = _summarize(payload)
        if not n:
            break
        items = next(v for v in payload.values()
                     if isinstance(v, list) and v and isinstance(v[0], dict))
        collected.extend(items)
        if n < rows:
            break
        polite_sleep()
    return collected


# ---------------------------------------------------------------------------
# 과거 조회 가능 여부 판정
# ---------------------------------------------------------------------------

HISTORY_HORIZONS = [
    (1, "어제"),
    (7, "1주 전"),
    (31, "1개월 전"),
    (95, "3개월 전"),
    (185, "6개월 전"),
    (370, "1년 전"),
    (740, "2년 전"),
    (1830, "5년 전"),
    (3660, "10년 전"),
]

DATE_PARAM_NAMES = ["stdDt", "sumDate", "strDate", "trafficDate", "stdDate", "aggDate"]


def _try(path: str, params: dict) -> tuple[int, list[str], str]:
    try:
        resp = get(f"{BASE}/{path}",
                   {"key": keys().require("ex"), "type": "json",
                    "numOfRows": 5, "pageNo": 1, **params}, timeout=20)
        payload = resp.json()
        n, fields = _summarize(payload)
        return n, fields, "" if n else json.dumps(payload, ensure_ascii=False)[:160]
    except Exception as exc:
        return 0, [], str(exc)[:160]


def find_working_combo(endpoints: list[str] | None = None) -> tuple[str, str] | None:
    """(엔드포인트, 날짜파라미터명) 중 어제 날짜로 데이터가 나오는 조합을 찾는다."""
    from datetime import date, timedelta

    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    candidates = endpoints or [p for p, _ in CANDIDATES if "traffic" in p.lower()]

    for path in candidates:
        for param in DATE_PARAM_NAMES:
            n, fields, _ = _try(path, {param: yesterday})
            polite_sleep(0.2)
            if n:
                print(f"✅ 동작: {path}  날짜파라미터={param}  ({n}건)")
                print(f"   필드: {', '.join(fields)}")
                return path, param
    return None


def probe_history(endpoint: str | None = None, date_param: str | None = None) -> dict:
    """제안하신 '일 단위로 뽑아 365일 합치기'가 실제로 가능한지 판정한다.

    핵심 질문은 하나다 — **이 API 가 과거 날짜를 돌려주는가?**
    '실시간' API 는 보관 기간이 짧은 경우가 많아, 되는지 안 되는지를
    문서가 아니라 실제 호출로 확인한다.
    """
    from datetime import date, timedelta

    if not (endpoint and date_param):
        print("동작하는 엔드포인트를 찾는 중...\n")
        combo = find_working_combo()
        if not combo:
            print("\n❌ 날짜 파라미터로 조회되는 엔드포인트를 찾지 못했습니다.")
            print("   `probe-ex` 로 전체 목록을 확인하거나 EX_API_KEY 를 점검하세요.")
            return {}
        endpoint, date_param = combo

    print(f"\n=== 과거 조회 가능 범위 ({endpoint} / {date_param}) ===")
    results, deepest = [], None
    for days, label in HISTORY_HORIZONS:
        target = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
        n, fields, note = _try(endpoint, {date_param: target})
        polite_sleep(0.2)
        mark = "OK " if n else "없음"
        print(f"  {label:8s} {target}  {mark} {n if n else ''} {note[:60]}")
        results.append({"days": days, "label": label, "date": target, "n": n})
        if n:
            deepest = (days, label, target)

    print()
    if not deepest:
        print("❌ 과거 날짜가 전혀 조회되지 않습니다 — 당일 데이터만 제공하는 API입니다.")
        print("   → 지금부터 매일 수집해 쌓는 방법밖에 없고, 분석에 쓸 만한 시계열이")
        print("     되려면 수 년이 걸립니다. docs/traffic-history.md 의 파일데이터 경로로 가세요.")
    elif deepest[0] < 370:
        print(f"⚠️ 최대 {deepest[1]}({deepest[0]}일)까지만 조회됩니다.")
        print("   → 연도별 변화(H2)를 보기엔 부족합니다. 파일데이터 경로를 병행하세요.")
    else:
        years = deepest[0] / 365
        print(f"✅ 최소 {deepest[1]}까지 조회됩니다 (약 {years:.0f}년).")
        print(f"   → 제안하신 방식이 유효합니다. `backfill` 로 일별 수집이 가능합니다.")
        print(f"      예상 요청 수: 약 {int(deepest[0]):,}일 × 페이지수")

    return {"endpoint": endpoint, "date_param": date_param,
            "results": results, "deepest": deepest}
