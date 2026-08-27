"""공공 API 호출 공통 유틸 — 재시도, 레이트리밋, XML/JSON 파싱."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_session = requests.Session()
_session.headers.update({"User-Agent": "redt-research/0.1"})


class ApiError(RuntimeError):
    pass


@retry(
    retry=retry_if_exception_type((requests.RequestException, ApiError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=16),
    reraise=True,
)
def get(url: str, params: dict, timeout: int = 30) -> requests.Response:
    resp = _session.get(url, params=params, timeout=timeout)
    if resp.status_code >= 500:
        raise ApiError(f"{resp.status_code} from {url}")
    resp.raise_for_status()
    return resp


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
