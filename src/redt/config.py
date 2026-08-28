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


@dataclass(frozen=True)
class Keys:
    data_go_kr: str = os.getenv("DATA_GO_KR_KEY", "")
    ex: str = os.getenv("EX_API_KEY", "")
    vworld: str = os.getenv("VWORLD_KEY", "")

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise RuntimeError(
                f"API 키가 없습니다: {name}. config/.env 를 만들고 채워주세요 "
                f"(config/.env.example 참고)."
            )
        return value


@lru_cache(maxsize=1)
def settings() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def keys() -> Keys:
    return Keys()


def bands() -> list[tuple[float, float]]:
    return [tuple(b) for b in settings()["spatial"]["bands"]]


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
