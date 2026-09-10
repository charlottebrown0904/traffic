"""행안부 '법정동별(행정동 통반단위) 주민등록 인구 및 세대현황' 을 두드려 본다.

요구사항 2026-09-10 — 인구가 안 붙는 법정동을 메우려고 신청한 API.

## 이것이 왜 정답으로 보이는가

지금까지 인구는 KOSIS 읍·면·동 표에서 왔다. 그 표는 **행정동** 단위라,
법정동인 우리 자료와 이름이 안 맞았다 (실측: 동 18.4%, 리 0%).

이 API 는 한 줄에 **법정동명과 행정동명이 같이** 들어 있다고 돼 있다.
그러면 두 가지가 한 번에 풀린다.

  1) 대조표가 따로 필요 없다 — 줄 자체가 대조표다.
  2) 인구를 나눌 필요가 없다 — 법정동 단위 총인구수가 바로 온다.
     (행정동 하나가 법정동 여럿을 덮을 때 인구를 어떻게 쪼갤지는
      자료가 말해주지 않아, 그것이 가장 큰 걸림돌이었다.)

칸 목록에 **리명**도 있다. 사실이면 리 15,203칸의 0% 도 같이 풀린다.

## 그런데 확인해야 할 것이 있다

  - 진짜 주소가 무엇인가 (문서에 경로만 적혀 있다)
  - 한 줄이 통·반 단위면 전국이 몇 줄인가. 일일 트래픽이 10,000 건이라
    쪽을 크게 못 받으면 며칠이 걸린다.
  - 법정동 단위로 접어 달라고 할 수 있는가, 아니면 우리가 합쳐야 하는가
  - 개발계정이 전국을 다 주는가 (표본만 주는 계정도 있다)

**짐작하지 않고 두드려 본다.** 이 저장소는 응답 모양을 세 번 틀렸다.

  실행: PYTHONPATH=src python scripts/stdg_pop_probe.py
"""
from __future__ import annotations

import json
import sys

from redt.collect.http import get

# 문서에 상세기능 경로(/selectStdgPpltnHhStus)만 적혀 있어서 앞부분을
# 모른다. 행안부(1741000) 아래에 사는 것이 가장 그럴듯하지만 확인이
# 먼저다 — 틀린 주소로 404 를 받고 '자료가 없다' 로 읽으면 안 된다.
CANDIDATES = [
    "https://apis.data.go.kr/1741000/stdgPpltnHhStus/selectStdgPpltnHhStus",
    "https://apis.data.go.kr/1741000/StdgPpltnHhStus/selectStdgPpltnHhStus",
    "https://apis.data.go.kr/1741000/selectStdgPpltnHhStus/selectStdgPpltnHhStus",
    "https://apis.data.go.kr/1741000/stdgPpltnHhStus_v2/selectStdgPpltnHhStus",
]

# 우리가 찾는 칸들. 응답에 이 이름들이 있는지 본다.
WANT = ["시도명", "시군구명", "법정동명", "리명", "행정기관코드", "행정동명",
        "총인구수", "세대수", "남자인구수", "여자인구수"]


def peek(url: str) -> dict | None:
    """한 쪽만 받아 본다. 실패하면 왜 실패했는지 적고 넘어간다."""
    print(f"\n  {url}")
    try:
        resp = get(url, {"type": "json", "numOfRows": "5", "pageNo": "1"},
                   timeout=60)
    except Exception as exc:                     # noqa: BLE001 — 탐침이다
        print(f"    호출 실패: {type(exc).__name__} {str(exc)[:200]}")
        return None
    body = resp.text or ""
    print(f"    http={resp.status_code}  {len(body):,}B")
    if resp.status_code != 200 or not body.strip():
        print(f"    {' '.join(body[:250].split())}")
        return None
    try:
        payload = resp.json()
    except ValueError:
        # XML 오류 봉투로 오는 경우가 흔하다. 그대로 보여 준다.
        print(f"    JSON 이 아님: {' '.join(body[:300].split())}")
        return None
    print(f"    바깥 열쇠: {list(payload)[:8]}")
    return payload


def find_rows(payload) -> list[dict]:
    """응답 어디에 줄이 들어 있든 찾아 낸다.

    포털 응답은 서비스마다 봉투가 다르다. 꼴을 맞히지 않고 **딕셔너리
    리스트**가 나오는 첫 자리를 줄로 본다.
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


def main() -> int:
    print("행안부 법정동별 주민등록 인구·세대현황 — 주소부터 찾는다")
    payload = None
    for url in CANDIDATES:
        payload = peek(url)
        if payload:
            rows = find_rows(payload)
            if rows:
                print(f"\n  ✔ 줄을 찾았습니다 — {len(rows)}줄 (첫 쪽)")
                print("  첫 줄 전체:")
                print("    " + json.dumps(rows[0], ensure_ascii=False)[:600])
                names = set(rows[0])
                print("\n  우리가 찾는 칸이 있는가")
                for w in WANT:
                    print(f"    {'있음' if w in names else '없음'}  {w}")
                missing = [w for w in WANT if w not in names]
                if missing:
                    print(f"\n  ⚠ 이름이 다를 수 있습니다. 실제 칸: {sorted(names)}")
                # 전국이 몇 줄인지. 이것이 하루 한도(10,000)를 넘는지가
                # 며칠 걸릴지를 정한다.
                total = None
                for k in ("totalCount", "totalcount", "TOTAL_COUNT"):
                    for node in json.dumps(payload).split():
                        if k in node:
                            break
                txt = json.dumps(payload, ensure_ascii=False)
                for k in ("totalCount", "totalcount"):
                    i = txt.find(k)
                    if i >= 0:
                        total = txt[i:i + 60]
                        break
                print(f"\n  전체 건수 단서: {total or '응답에 안 적혀 있음'}")
                return 0
            print("    줄을 못 찾았습니다. 봉투를 그대로 보여 줍니다:")
            print("    " + json.dumps(payload, ensure_ascii=False)[:500])
    print("\n  네 후보 모두 실패했습니다. data.go.kr 의 그 API 상세 화면에서")
    print("  '엔드포인트' 또는 '요청주소' 를 그대로 알려주시면 그것으로 다시 잽니다.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
