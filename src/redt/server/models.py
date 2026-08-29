"""요청·응답 스키마.

응답에서 무엇을 **빼는지**가 중요하다. 중개사 이메일과 해시는 공개 응답에
절대 포함하지 않는다. 반대로 사무소명·등록번호·연락처는 공인중개사법상
표시·광고 명시사항이라 반드시 포함한다.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

KIND = Literal["land", "factory", "house", "commercial"]
DEAL_TYPE = Literal["sale", "lease"]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
# 중개사무소 등록번호는 지자체마다 형식이 조금씩 다르다.
# 지나치게 엄격하면 실제 유효한 번호를 거부하므로 느슨하게 받고,
# 진짜 검증은 시군구 조회 연동으로 미룬다 (docs/legal-notes.md).
LICENSE_RE = re.compile(r"^[0-9가-힣]{2,6}-\d{2,4}-\d{2,6}$")


class BrokerSignup(BaseModel):
    email: str
    password: str = Field(min_length=10, max_length=200)
    office_name: str = Field(min_length=1, max_length=100)
    office_address: str = Field(min_length=1, max_length=200)
    license_no: str
    agent_name: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=5, max_length=30)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("이메일 형식이 올바르지 않습니다")
        return v

    @field_validator("license_no")
    @classmethod
    def _license(cls, v: str) -> str:
        v = v.strip()
        if not LICENSE_RE.match(v):
            raise ValueError("등록번호 형식이 올바르지 않습니다 (예: 41590-2024-00001)")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    token: str
    expires_at: str
    broker: "BrokerPublic"


class BrokerPublic(BaseModel):
    """공개 응답 — 이메일과 자격증명은 포함하지 않는다."""
    id: int
    office_name: str
    office_address: str
    license_no: str
    agent_name: str
    phone: str
    status: str


class ListingCreate(BaseModel):
    kind: KIND
    deal_type: DEAL_TYPE = "sale"
    address: str = Field(min_length=1, max_length=200)
    area_m2: float = Field(gt=0, le=100_000_000)
    price_manwon: int = Field(gt=0, le=100_000_000)
    contact_phone: str = Field(min_length=5, max_length=30)
    lat: float | None = None
    lon: float | None = None
    jimok: str | None = Field(default=None, max_length=30)
    land_use: str | None = Field(default=None, max_length=50)
    memo: str | None = Field(default=None, max_length=2000)

    @field_validator("lat")
    @classmethod
    def _lat(cls, v):
        if v is not None and not (33 <= v <= 39):
            raise ValueError("위도가 국내 범위를 벗어났습니다")
        return v

    @field_validator("lon")
    @classmethod
    def _lon(cls, v):
        if v is not None and not (124 <= v <= 132):
            raise ValueError("경도가 국내 범위를 벗어났습니다")
        return v


class ListingUpdate(BaseModel):
    address: str | None = Field(default=None, min_length=1, max_length=200)
    area_m2: float | None = Field(default=None, gt=0, le=100_000_000)
    price_manwon: int | None = Field(default=None, gt=0, le=100_000_000)
    contact_phone: str | None = Field(default=None, min_length=5, max_length=30)
    memo: str | None = Field(default=None, max_length=2000)
    lat: float | None = None
    lon: float | None = None


class ListingPublic(BaseModel):
    id: int
    kind: KIND
    deal_type: DEAL_TYPE
    address: str
    lat: float | None = None
    lon: float | None = None
    area_m2: float
    price_manwon: int
    price_per_m2: float | None = None
    jimok: str | None = None
    land_use: str | None = None
    memo: str | None = None
    contact_phone: str
    status: str
    paid_until: str | None = None
    nearest_tollgate_id: str | None = None
    nearest_name: str | None = None
    nearest_km: float | None = None
    band: str | None = None
    created_at: str
    # 표시·광고 명시사항 (공인중개사법 제18조의2)
    office_name: str
    office_address: str
    license_no: str
    agent_name: str


TokenResponse.model_rebuild()
