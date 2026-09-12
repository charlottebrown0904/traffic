"""설정 로딩 — .env(키)와 settings.yaml(분석 파라미터)을 한 곳에서 다룬다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW, INTERIM, PROCESSED = DATA / "raw", DATA / "interim", DATA / "processed"
DB_PATH = PROCESSED / "redt.duckdb"
GEOCODE_CACHE = INTERIM / "geocode_cache.jsonl"

load_dotenv(ROOT / "config" / ".env")


# 한국 공공 API 는 해외 IP 를 막는다 (docs/finding-geoblock.md).
# 해외에서 돌 때는 서울 리전 중계기를 거친다. 그때 인증키는 중계기 쪽에만 있고
# 이쪽에는 없으므로, require() 가 키 없음으로 막아서면 안 된다.
VIA_RELAY = "__via_relay__"


@dataclass(frozen=True)
class Relay:
    url: str = os.getenv("REDT_RELAY_URL", "").rstrip("/")
    token: str = os.getenv("REDT_RELAY_TOKEN", "")

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)


@lru_cache(maxsize=1)
def relay() -> Relay:
    return Relay()


@dataclass(frozen=True)
class Keys:
    data_go_kr: str = os.getenv("DATA_GO_KR_KEY", "")
    ex: str = os.getenv("EX_API_KEY", "")
    vworld: str = os.getenv("VWORLD_KEY", "")
    # R-ONE(부동산통계정보). **여기 있으면 직접 부르고, 없으면 중계기로 간다.**
    # www.reb.or.kr 이 해외 IP 에 응답하는 곳이면 직접 부르는 쪽이 Vercel
    # 함수 호출과 전송량을 아낀다 (docs/reb-openapi.md §6).
    reb: str = os.getenv("REB_KEY", "")

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if value:
            return value
        if relay().enabled:
            # 중계기가 자기 환경변수의 진짜 키로 바꿔 끼운다.
            return VIA_RELAY
        raise RuntimeError(
            f"API 키가 없습니다: {name}. config/.env 를 만들고 채우거나 "
            f"환경변수로 지정하세요 (config/.env.example 참고)."
        )


@lru_cache(maxsize=1)
def settings() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def keys() -> Keys:
    return Keys()


def bands() -> list[tuple[float, float]]:
    return [tuple(b) for b in settings()["spatial"]["bands"]]


def band_labels() -> list[str]:
    return [f"{lo:g}-{hi:g}" for lo, hi in bands()]


def primary_band() -> str:
    """스코어·화면이 기본으로 쓰는 밴드.

    밴드 경계를 바꿀 때마다 코드 여러 곳의 기본값 문자열이 같이 안 바뀌면,
    그 명령들은 오류 없이 **빈 결과**를 낸다. 표본이 없는 것과 밴드 이름이
    틀린 것을 구분할 수 없게 되므로, 여기서 미리 막고 소리 내어 죽는다.
    """
    labels = band_labels()
    want = settings()["spatial"].get("primary_band")
    if want is None:
        return labels[0]
    if want not in labels:
        raise ValueError(
            f"settings.yaml 의 spatial.primary_band='{want}' 가 밴드 목록에 없습니다. "
            f"쓸 수 있는 값: {labels}"
        )
    return want


def band_label(km: float) -> str | None:
    """거리(km)를 밴드 라벨로. 어느 밴드에도 안 들면 None."""
    for lo, hi in bands():
        if lo <= km < hi:
            return f"{lo:g}-{hi:g}"
    lo, hi = bands()[-1]
    # 마지막 밴드는 상한을 포함시켜 경계 거래를 버리지 않는다
    return f"{lo:g}-{hi:g}" if km == hi else None


def ensure_dirs() -> None:
    for path in (RAW, INTERIM, PROCESSED):
        path.mkdir(parents=True, exist_ok=True)
