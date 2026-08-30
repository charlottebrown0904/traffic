"""로그·오류 메시지에서 키를 지운다.

공공 API 는 키를 쿼리스트링으로 받는다. 그래서 4xx 응답의 requests 예외 메시지에는
serviceKey=<진짜키> 가 그대로 들어간다. 그 트레이스백을 어딘가에 붙여넣는 순간
키가 새므로, 사람 눈에 닿기 전에 지운다.
"""
from __future__ import annotations

import re

_SECRET = re.compile(r"(?i)\b(serviceKey|apiKey|authKey|accessKey|key)=[^&\s'\"]+")


def scrub(text: str) -> str:
    return _SECRET.sub(r"\1=***", text)
