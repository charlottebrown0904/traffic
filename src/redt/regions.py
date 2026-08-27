"""파일럿 권역 / 시군구 코드 관리."""
from __future__ import annotations

from functools import lru_cache

import yaml

from .config import ROOT


@lru_cache(maxsize=1)
def _config() -> dict:
    with open(ROOT / "config" / "pilot_regions.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def all_regions() -> dict:
    return _config()["regions"]


def active_regions() -> list[str]:
    return _config().get("active", [])


def sigungu_codes(regions: list[str] | None = None) -> dict[str, str]:
    """권역 이름들 → {시군구코드: 이름}. regions 가 None 이면 active 사용."""
    names = regions if regions is not None else active_regions()
    known = all_regions()
    unknown = [n for n in names if n not in known]
    if unknown:
        raise KeyError(f"알 수 없는 권역: {unknown}. 사용 가능: {list(known)}")

    merged: dict[str, str] = {}
    for name in names:
        merged.update({str(k): v for k, v in known[name]["sigungu"].items()})
    return merged
