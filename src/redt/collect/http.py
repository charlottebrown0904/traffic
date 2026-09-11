"""공공 API 호출 공통 유틸 — 재시도, 레이트리밋, XML/JSON 파싱."""
from __future__ import annotations

import json
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlsplit

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import VIA_RELAY, relay
from ..scrub import scrub

# 세션은 스레드마다 따로 둔다.
#
# requests.Session 은 여러 스레드가 동시에 쓰는 것을 보장하지 않는다.
# 연결 풀을 공유하다 응답이 뒤섞이면, 예외가 아니라 '다른 시군구의
# 자료가 이 시군구 것으로 저장되는' 형태로 조용히 틀어진다. 그런 오류는
# 로그에 아무 표시가 남지 않는다.
_local = threading.local()


def _sess() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "redt-research/0.1"})
        # 동시 요청만큼 연결을 열어둔다. 기본값(10)이면 그 위로는 줄을 선다.
        adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=4)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.session = s
    return s


class ApiError(RuntimeError):
    pass


# 중계기가 키를 끼워 넣으므로, 이쪽에서 보낸 키 자리는 지우고 보낸다.
# OC(법제처 아이디)는 여기 없다 — 중계기로 실어 보내야 포털이 법제처로 넘길 수 있다.
_KEY_PARAMS = ("serviceKey", "key", "apiKey", "authKey", "accessKey")


def _via_relay(url: str, params: dict) -> tuple[str, dict, dict]:
    """(요청URL, 파라미터, 헤더) 를 중계기 경유 형태로 바꾼다."""
    cfg = relay()
    carried = {k: v for k, v in params.items() if k not in _KEY_PARAMS}
    target = f"{url}?{urlencode(carried)}" if carried else url
    return (f"{cfg.url}/api/relay", {"target": target}, {"x-relay-token": cfg.token})


def _should_relay(url: str, params: dict) -> bool:
    if not relay().enabled:
        return False
    # 키가 진짜로 있으면 (국내 실행) 굳이 돌아가지 않는다.
    if any(params.get(k) not in (None, "", VIA_RELAY) for k in _KEY_PARAMS):
        return False
    return urlsplit(url).netloc in RELAYED_HOSTS


# 중계기가 허용하는 목적지와 **같아야 한다** (api/relay.js 의 ALLOW).
# 중계기 쪽에만 넣고 이쪽에 안 넣으면, 호출이 미국 러너에서 직접 나가
# 지오블록에 막힌다. 그러면 '중계기에 없다' 로 오해하게 된다 —
# api.odcloud.kr 과 www.data.go.kr 에서 실제로 그럴 뻔했다.
RELAYED_HOSTS = {
    "apis.data.go.kr",
    # 표준데이터(tn_pubr_public_*)는 s 가 없는 쪽에 산다. 다른 호스트다.
    "api.data.go.kr",
    "api.odcloud.kr",
    "www.data.go.kr",
    # 경매·공매 원천 확인용 (api/relay.js 의 ALLOW 와 짝).
    "openapi.onbid.co.kr",
    "www.onbid.co.kr",
    "www.courtauction.go.kr",
    "api.vworld.kr",
    "www.vworld.kr",
    "data.ex.co.kr",
    "kosis.kr",
    # 자치법규(조례) Open API — 시군 도시계획조례의 건폐율·용적률·개발행위 기준.
    "www.law.go.kr",
}


@retry(
    retry=retry_if_exception_type((requests.RequestException, ApiError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=16),
    reraise=True,
)
def get(url: str, params: dict, timeout: int = 30) -> requests.Response:
    headers = None
    if _should_relay(url, params):
        url, params, headers = _via_relay(url, params)
    resp = _sess().get(url, params=params, timeout=timeout, headers=headers)
    if resp.status_code >= 500:
        raise ApiError(f"{resp.status_code} from {url}")
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        # requests 의 메시지에는 쿼리스트링이 통째로 들어간다 (serviceKey 포함).
        raise requests.HTTPError(scrub(str(exc)), response=resp) from None
    return resp


def get_once(url: str, params: dict, timeout: int = 15) -> requests.Response:
    """재시도 없이 한 번만 부른다.

    엔드포인트 이름을 **탐침**할 때 쓴다. 틀린 주소는 404 로 돌아오는데,
    `get()` 은 그것을 일시적 장애로 보고 네 번 다시 부른다. 후보가 수십
    개면 그 헛기다림만으로 작업 시간 제한에 걸린다. 틀린 주소는 다시
    불러도 틀린 주소다.
    """
    headers = None
    if _should_relay(url, params):
        url, params, headers = _via_relay(url, params)
    return _sess().get(url, params=params, timeout=timeout, headers=headers)


def get_json(url: str, params: dict, timeout: int = 60) -> dict:
    """JSON 으로 받는다. 아니면 무엇이 왔는지 말하고 죽는다.

    브이월드 /ned WFS 는 오류를 JSON 이 아닌 것으로 돌려주는 일이 있다.
    조용히 빈 dict 를 주면 '이 칸에는 필지가 없구나' 로 읽히므로
    구분되게 던진다.
    """
    resp = get(url, params, timeout)
    try:
        return resp.json()
    except ValueError:
        pass
    # **줄바꿈이 문자열 안에 그대로 든 응답이 온다.** 파이썬 기본 파서는
    # 그것을 거부한다(JSONDecodeError: Invalid control character). 브이월드
    # 장소검색이 실제로 그랬다 — run 40 이 첫 시군구에서 그대로 죽었고,
    # 자료는 멀쩡했는데 관청 좌표를 한 곳도 못 받았다.
    #
    # 규격을 어긴 것은 저쪽이지만, 우리가 못 읽을 이유는 없다. 다시 한 번
    # 느슨하게 읽어 본다. 그래도 안 되면 그때 무엇이 왔는지 말하고 죽는다.
    try:
        return json.loads(resp.text, strict=False)
    except ValueError:
        raise ApiError(
            f"JSON 이 아닙니다 (HTTP {resp.status_code}): {scrub(resp.text[:200])}")


def get_xml(url: str, params: dict, timeout: int = 30) -> ET.Element:
    resp = get(url, params, timeout)
    text = resp.text.lstrip("﻿")
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise ApiError(f"XML 파싱 실패: {text[:300]}") from exc


def text_of(node: ET.Element, tag: str, default: str = "") -> str:
    child = node.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def polite_sleep(seconds: float = 0.12) -> None:
    """공공 API 예의상 간격. 대량 루프에서 차단당하지 않기 위함."""
    time.sleep(seconds)
