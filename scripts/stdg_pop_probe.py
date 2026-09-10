"""행안부 '법정동별(행정동 통반단위) 주민등록 인구 및 세대현황' 을 두드려 본다.

요구사항 2026-09-10 — 인구가 안 붙는 법정동을 메우려고 신청한 API.
목록 화면: https://www.data.go.kr/data/15108071/openapi.do

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

## 주소를 짐작하지 않는다

처음에는 기관번호 1741000 아래로 네 가지를 짐작해 두드렸다. **전부
404** 였다 — 서버에는 닿았는데 그 경로가 없다는 뜻이다. 짐작으로는
더 못 좁힌다.

그래서 목록 화면을 **중계기로 읽어** 거기 적힌 주소를 뽑아 쓴다.
www.data.go.kr 은 이미 중계기 허용 목록에 있다 (api/relay.js 의 ALLOW).

  실행: PYTHONPATH=src python scripts/stdg_pop_probe.py
"""
from __future__ import annotations

import json
import re
import sys

from redt.collect.http import get_once

# 목록 화면. 포털은 같은 자료를 여러 주소로 보여 주고, 어떤 꼴은
# 사람이 아닌 요청에 404 를 준다. 그래서 한 주소에 걸지 않는다.
PAGES = [
    "https://www.data.go.kr/data/15108071/openapi.do",
    "https://www.data.go.kr/tcs/dss/selectApiDataDetailView.do"
    "?publicDataPk=15108071",
    "https://www.data.go.kr/catalog/15108071/openapi.json",
    "https://www.data.go.kr/data/15108071/openapi.do#/API%20목록",
]

# 목록 화면에서 뽑아 낼 주소의 모양. 포털은 서비스마다 기관번호와
# 경로가 달라서, 호스트만 알고 나머지는 화면이 말하게 둔다.
# 콜론을 넣는 이유: odcloud 는 .../v1/uddi:1a2b-3c4d 꼴이라, 콜론을
# 빼면 'uddi' 에서 잘려 못 쓰는 주소가 된다.
ENDPOINT = re.compile(
    r"https?://(?:apis?\.data\.go\.kr|api\.odcloud\.kr)/[A-Za-z0-9_\-/.:]+")

# 우리가 찾는 칸들. 응답에 이 이름들이 있는지 본다.
WANT = ["시도명", "시군구명", "법정동명", "리명", "행정기관코드", "행정동명",
        "총인구수", "세대수", "남자인구수", "여자인구수"]


def read_page() -> str:
    """목록 화면을 중계기로 읽는다. 여러 꼴을 차례로 시도한다.

    **재시도하지 않는다** (get_once). 틀린 주소는 다시 불러도 틀린
    주소인데, get() 은 404 를 일시적 장애로 보고 네 번 더 부른다 —
    후보가 여럿이면 그 헛기다림만으로 시간이 다 간다.
    """
    for url in PAGES:
        print(f"\n  {url}")
        try:
            resp = get_once(url, {}, timeout=40)
        except Exception as exc:                 # noqa: BLE001 — 탐침이다
            print(f"    실패: {type(exc).__name__} {str(exc)[:180]}")
            continue
        body = resp.text or ""
        print(f"    http={resp.status_code}  {len(body):,}B")
        if resp.status_code == 200 and body.strip():
            # 막는 화면인지 눈으로 확인할 수 있게 앞머리를 보여 준다.
            head = " ".join(body[:200].split())
            print(f"    앞머리: {head}")
            return body
        if body.strip():
            print(f"    {' '.join(body[:200].split())}")
    return ""


def candidates(page: str) -> list[str]:
    """화면에 적힌 주소들. 우리가 부를 만한 것만 남긴다."""
    found: list[str] = []
    for m in ENDPOINT.finditer(page):
        url = m.group(0).rstrip(".,)'\"")
        if url not in found:
            found.append(url)
    # 상세기능 이름이 들어간 것을 앞으로 올린다.
    found.sort(key=lambda u: ("StdgPpltn" not in u and "stdgPpltn" not in u, u))
    return found


def peek(url: str) -> dict | None:
    """한 쪽만 받아 본다. 실패하면 왜 실패했는지 적고 넘어간다."""
    print(f"\n  {url}")
    try:
        resp = get_once(url, {"type": "json", "numOfRows": "5",
                              "pageNo": "1"}, timeout=40)
    except Exception as exc:                     # noqa: BLE001 — 탐침이다
        print(f"    호출 실패: {type(exc).__name__} {str(exc)[:180]}")
        return None
    body = resp.text or ""
    print(f"    http={resp.status_code}  {len(body):,}B")
    if resp.status_code != 200 or not body.strip():
        print(f"    {' '.join(body[:250].split())}")
        return None
    try:
        return resp.json()
    except ValueError:
        # XML 오류 봉투로 오는 경우가 흔하다. 그대로 보여 준다.
        print(f"    JSON 이 아님: {' '.join(body[:300].split())}")
        return None


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


def report(payload: dict) -> bool:
    rows = find_rows(payload)
    if not rows:
        print("    줄을 못 찾았습니다. 봉투를 그대로 보여 줍니다:")
        print("    " + json.dumps(payload, ensure_ascii=False)[:500])
        return False
    print(f"    ✔ 줄 {len(rows)}개 (첫 쪽)")
    print("    첫 줄 전체:")
    print("      " + json.dumps(rows[0], ensure_ascii=False)[:700])
    names = set(rows[0])
    print("\n    우리가 찾는 칸이 있는가")
    for w in WANT:
        print(f"      {'있음' if w in names else '없음'}  {w}")
    if any(w not in names for w in WANT):
        print(f"\n    실제 칸 이름: {sorted(names)}")
    # 전국이 몇 줄인지. 하루 한도(10,000)를 넘는지가 며칠 걸릴지를 정한다.
    txt = json.dumps(payload, ensure_ascii=False)
    for k in ("totalCount", "totalcount", "TOTAL_COUNT", "totCnt"):
        i = txt.find(k)
        if i >= 0:
            print(f"\n    전체 건수 단서: {txt[i:i + 60]}")
            break
    else:
        print("\n    전체 건수가 응답에 안 적혀 있습니다")
    return True


def main() -> int:
    page = read_page()
    urls = candidates(page) if page else []
    if urls:
        print(f"\n화면에서 주소 후보 {len(urls)}개를 찾았습니다")
        for u in urls[:12]:
            print(f"  · {u}")
    else:
        print("\n화면에서 주소를 못 찾았습니다 "
              "(로그인해야 보이는 화면일 수 있습니다)")

    for url in urls[:8]:
        payload = peek(url)
        if payload and report(payload):
            print(f"\n✔ 이 주소로 됩니다: {url}")
            return 0

    print("\n아직 못 찾았습니다. 활용가이드 문서의 'End Point' 한 줄을")
    print("그대로 알려주시면 그것으로 다시 잽니다 (인증키는 빼고).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
