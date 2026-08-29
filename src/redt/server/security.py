"""비밀번호 해싱과 세션 토큰.

외부 의존성 없이 표준 라이브러리만 쓴다 (hashlib.scrypt, secrets).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
TOKEN_TTL = timedelta(days=14)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return digest.hex(), salt


def verify_password(password: str, expected_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    # 타이밍 공격을 피하려면 문자열 == 이 아니라 상수시간 비교를 써야 한다
    return hmac.compare_digest(candidate, expected_hash)


def new_token() -> tuple[str, str, str]:
    """(평문 토큰, 저장용 해시, 만료시각). 평문은 DB 에 남기지 않는다."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + TOKEN_TTL
    return token, token_hash(token), expires.isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
