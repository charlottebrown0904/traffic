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


# discover-sigungu 가 훑어서 찾아 둔 전국 코드. 추측한 목록이 아니라
# 실제로 자료가 온 코드만 들어 있다.
DISCOVERED = ROOT / "config" / "sigungu_codes.yaml"
NATIONWIDE = "nationwide"


def discovered_codes() -> dict[str, str]:
    """전국 시군구 코드. 아직 안 찾았으면 빈 dict."""
    if not DISCOVERED.exists():
        return {}
    data = yaml.safe_load(DISCOVERED.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for sido, codes in data.items():
        for code in codes:
            out[str(code)] = ""
    return out


def sigungu_codes(regions: list[str] | None = None) -> dict[str, str]:
    """권역 이름들 → {시군구코드: 이름}. regions 가 None 이면 active 사용.

    'nationwide' 는 pilot_regions.yaml 이 아니라 discover-sigungu 가 훑어
    찾아 둔 목록을 씁니다. 전국 시군구를 손으로 적어 넣으면 RTMS 가 잘못된
    코드에 0건을 돌려주는 탓에 그 시군구만 조용히 빕니다.
    """
    names = regions if regions is not None else active_regions()
    if NATIONWIDE in names:
        found = discovered_codes()
        if not found:
            raise KeyError(
                "전국 코드를 아직 안 찾았습니다. `python -m redt.cli "
                "discover-sigungu` 를 먼저 한 번 돌리세요 "
                "(config/sigungu_codes.yaml 이 만들어집니다).")
        rest = [n for n in names if n != NATIONWIDE]
        merged = dict(found)
        if rest:
            merged.update(sigungu_codes(rest))
        return merged

    known = all_regions()
    unknown = [n for n in names if n not in known]
    if unknown:
        raise KeyError(f"알 수 없는 권역: {unknown}. 사용 가능: {list(known)}")

    merged: dict[str, str] = {}
    for name in names:
        merged.update({str(k): v for k, v in known[name]["sigungu"].items()})
    return merged
