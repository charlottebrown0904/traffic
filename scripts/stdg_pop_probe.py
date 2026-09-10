"""행안부 '법정동별(행정동 통반단위) 주민등록 인구 및 세대현황' 을 두드려 본다.

요구사항 2026-09-10 — 인구가 안 붙는 법정동을 메우려고 신청한 API.

  목록: https://www.data.go.kr/data/15108071/openapi.do
  End Point: https://apis.data.go.kr/1741000/stdgPpltnHhStus   (확인됨)
  상세기능: /selectStdgPpltnHhStus

## 이것이 왜 정답으로 보이는가

지금까지 인구는 KOSIS 읍·면·동 표에서 왔다. 그 표는 **행정동** 단위라,
법정동인 우리 자료와 이름이 안 맞았다 (실측: 동 18.4%, 리 0%).

이 API 는 한 줄에 **법정동명과 행정동명이 같이** 들어 있다. 그러면
대조표가 따로 필요 없고(줄 자체가 대조표다), 인구를 쪼갤 필요도 없다
— 법정동 단위 총인구수가 바로 온다. 칸 목록에 **리명**도 있어, 사실
이면 리 15,203칸의 0% 도 같이 풀린다.

## 왜 아직 404 인가를 가른다

End Point + 상세기능 을 그대로 이어 붙인 주소로 이미 두드렸는데
404 였다. 주소가 맞다면 남는 설명은 셋이다.

  (1) 상세기능 경로의 꼴이 다르다 (.do 가 붙거나 get~ 이거나)
  (2) 파라미터 이름이 다르다 (_type 을 쓰는 서비스가 있다)
  (3) **아직 라우팅이 안 열렸다** — 활용신청 승인 뒤 반영까지 시간이
      걸린다. 이때 포털은 오류 봉투가 아니라 404 를 준다.

셋을 가르려면 **응답 본문을 통째로 봐야** 한다. 404 에도 포털이 무슨
말을 적어 두는 경우가 있다. 그래서 이 탐침은 상태코드만 세지 않고
본문을 그대로 찍는다.

  실행: PYTHONPATH=src python scripts/stdg_pop_probe.py
"""
from __future__ import annotations

import json
import sys

from redt.collect.http import get_once

BASE = "https://apis.data.go.kr/1741000/stdgPpltnHhStus"

# 상세기능 경로의 꼴. 문서에 /selectStdgPpltnHhStus 로 적혀 있지만,
# 포털 서비스마다 .do 가 붙거나 동사가 get~ 인 경우가 있다.
PATHS = [
    "/selectStdgPpltnHhStus",
    "",                                  # End Point 자체가 호출 주소인 경우
    "/selectStdgPpltnHhStus.do",
    "/getStdgPpltnHhStus",
    "/selectStdgPpltnHhStusList",
]

# 파라미터 이름. 포털은 type 과 _type 두 갈래를 쓴다.
PARAM_SETS = [
    {"type": "json", "numOfRows": "5", "pageNo": "1"},
    {"_type": "json", "numOfRows": "5", "pageNo": "1"},
    {"numOfRows": "5", "pageNo": "1"},
]

# 우리가 찾는 칸들. 응답에 이 이름들이 있는지 본다.
WANT = ["시도명", "시군구명", "법정동명", "리명", "행정기관코드", "행정동명",
        "총인구수", "세대수", "남자인구수", "여자인구수"]


def find_rows(payload) -> list[dict]:
    """응답 어디에 줄이 들어 있든 찾아 낸다.

    포털 응답은 서비스마다 봉투가 다르다. 꼴을 맞히지 않고 **딕셔너리
    리스트**가 나오는 첫 자리를 줄로 본다. 이 저장소는 응답 모양을
    세 번 틀렸다.
    """
    found: list[dict] = []

    def walk(node):
        if found:
            return
        if isinstance(node, list):
            dicts = [x for x in node if isinstance(x, dict)]
            if len(dicts) == len(node) and dicts:
                found.extend(dicts)
                return
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)

    walk(payload)
    return found


def report(payload) -> bool:
    rows = find_rows(payload)
    if not rows:
        print("      줄을 못 찾았습니다. 봉투 그대로:")
        print("      " + json.dumps(payload, ensure_ascii=False)[:600])
        return False
    print(f"      ✔ 줄 {len(rows)}개")
    print("      첫 줄 전체:")
    print("        " + json.dumps(rows[0], ensure_ascii=False)[:800])
    names = set(rows[0])
    print("\n      우리가 찾는 칸")
    for w in WANT:
        print(f"        {'있음' if w in names else '없음'}  {w}")
    if any(w not in names for w in WANT):
        print(f"\n      실제 칸 이름: {sorted(names)}")
    # 전국이 몇 줄인지. 하루 한도(10,000)를 넘는지가 며칠 걸릴지를 정한다.
    txt = json.dumps(payload, ensure_ascii=False)
    for k in ("totalCount", "totalcount", "TOTAL_COUNT", "totCnt", "listTotalCount"):
        i = txt.find(k)
        if i >= 0:
            print(f"\n      전체 건수: {txt[i:i + 60]}")
            break
    else:
        print("\n      전체 건수가 응답에 안 적혀 있습니다")
    return True


def try_one(url: str, params: dict) -> tuple[bool, int]:
    label = ",".join(sorted(params))
    print(f"\n  {url}\n    파라미터 [{label}]")
    try:
        resp = get_once(url, params, timeout=40)
    except Exception as exc:                     # noqa: BLE001 — 탐침이다
        print(f"    호출 실패: {type(exc).__name__} {str(exc)[:180]}")
        return False, 0
    body = resp.text or ""
    print(f"    http={resp.status_code}  {len(body):,}B  "
          f"type={resp.headers.get('content-type', '?')}")
    # **본문을 통째로 본다.** 404 에도 포털이 무슨 말을 적어 두는
    # 경우가 있고, 그 한 줄이 '주소가 틀렸다' 와 '아직 안 열렸다' 를
    # 가른다. 상태코드만 세면 그 구분을 영영 못 한다.
    if body.strip():
        print(f"    본문: {' '.join(body[:400].split())}")
    if resp.status_code != 200 or not body.strip():
        return False, resp.status_code
    try:
        payload = resp.json()
    except ValueError:
        print("    (JSON 이 아닙니다 — 위 본문이 전부입니다)")
        return False, resp.status_code
    return report(payload), resp.status_code


def main() -> int:
    print("행안부 법정동별 주민등록 인구·세대현황")
    print(f"  End Point: {BASE}")
    for path in PATHS:
        url = BASE + path
        for params in PARAM_SETS:
            ok, code = try_one(url, params)
            if ok:
                print(f"\n✔ 됩니다 — {url}  파라미터 {sorted(params)}")
                return 0
            # **404 면 그 경로 자체가 없다.** 파라미터를 바꿔 봐야
            # 같은 404 라, 남은 조합은 건너뛰고 다음 경로로 간다.
            if code == 404:
                break
            # 200 인데 우리가 원한 꼴이 아니면 파라미터를 바꿔 본다.
        # (경로 반복 계속)
    print("\n아직 안 됩니다. 위 본문에 포털이 남긴 말이 있으면 그것이 답입니다.")
    print("아무 말도 없이 404 만 오면, 활용신청이 아직 반영 안 된 것일 수")
    print("있습니다 (승인 뒤 몇 시간 걸립니다). 그때는 잠시 뒤 다시 잽니다.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
