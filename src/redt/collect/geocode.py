"""지번 주소 → 좌표 (VWorld). 캐시가 비용을 좌우하므로 캐시를 1급 시민으로 다룬다."""
from __future__ import annotations

import json
from pathlib import Path

from ..config import GEOCODE_CACHE, ensure_dirs, keys
from .http import get, polite_sleep

VWORLD_URL = "https://api.vworld.kr/req/address"


class GeocodeCache:
    def __init__(self, path: Path | None = None):
        self.path = path or GEOCODE_CACHE
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                self._data[row["addr_key"]] = row

    def get(self, addr: str) -> dict | None:
        return self._data.get(addr)

    def put(self, addr: str, lat: float | None, lon: float | None, source: str,
            level: str | None = None) -> None:
        row = {"addr_key": addr, "lat": lat, "lon": lon, "source": source, "level": level}
        self._data[addr] = row
        ensure_dirs()
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def __len__(self) -> int:
        return len(self._data)


def build_address(sido: str, sigungu: str, umd: str, jibun: str) -> str:
    parts = [p.strip() for p in (sido, sigungu, umd, jibun) if p and str(p).strip()]
    return " ".join(parts)


def geocode_one(address: str, kind: str = "PARCEL") -> tuple[float | None, float | None]:
    """실패해도 예외를 던지지 않는다 — 실패는 캐시에 NULL로 기록해 재시도를 막는다."""
    resp = get(
        VWORLD_URL,
        {
            "service": "address",
            "request": "getcoord",
            "version": "2.0",
            "crs": "epsg:4326",
            "type": kind,
            "address": address,
            "format": "json",
            "key": keys().require("vworld"),
        },
    )
    try:
        payload = resp.json()
        if payload.get("response", {}).get("status") != "OK":
            return None, None
        point = payload["response"]["result"]["point"]
        return float(point["y"]), float(point["x"])
    except (ValueError, KeyError, TypeError):
        return None, None


def geocode_with_fallback(sigungu: str, umd: str, jibun: str
                          ) -> tuple[float | None, float | None, str | None]:
    """2단계 지오코딩.

    국토부는 개인정보 보호를 이유로 **토지·일반건축물의 지번을 일부만 공개**한다.
    따라서 상당수 거래는 지번 단위 좌표를 얻을 수 없다.
      1) 지번까지 → 'parcel'  (정확, 거리밴드 분석에 사용 가능)
      2) 법정동까지 → 'umd'   (동 중심점, 오차 ±1~2km)
    어느 단계로 얻었는지를 반드시 기록해서, 근거리 밴드 분석에서 걸러낼 수 있게 한다.
    """
    if jibun and str(jibun).strip():
        full = build_address(None, sigungu, umd, jibun)
        lat, lon = geocode_one(full, "PARCEL")
        if lat is not None:
            return lat, lon, "parcel"

    coarse = build_address(None, sigungu, umd, None)
    if not coarse:
        return None, None, None
    lat, lon = geocode_one(coarse, "PARCEL")
    return (lat, lon, "umd") if lat is not None else (None, None, None)


def geocode_many(rows: list[tuple[str, str, str]], cache: GeocodeCache | None = None,
                 limit: int | None = None) -> dict[tuple, tuple]:
    """rows: (시군구, 법정동, 지번) 튜플 목록 → {튜플: (lat, lon, level)}"""
    cache = cache or GeocodeCache()
    result: dict[tuple, tuple] = {}
    pending = []

    for row in rows:
        key = build_address(None, *row)
        hit = cache.get(key)
        if hit is not None:
            result[row] = (hit["lat"], hit["lon"], hit.get("level"))
        else:
            pending.append(row)

    if limit is not None:
        pending = pending[:limit]

    print(f"지오코딩: 캐시 적중 {len(result):,} / 신규 요청 {len(pending):,}")
    levels = {"parcel": 0, "umd": 0, "fail": 0}
    for i, row in enumerate(pending, 1):
        lat, lon, level = geocode_with_fallback(*row)
        cache.put(build_address(None, *row), lat, lon, "vworld", level)
        result[row] = (lat, lon, level)
        levels[level or "fail"] += 1
        polite_sleep(0.05)
        if i % 500 == 0:
            print(f"  {i:,}/{len(pending):,}  parcel={levels['parcel']:,} "
                  f"umd={levels['umd']:,} fail={levels['fail']:,}")

    if pending:
        print(f"  결과: 지번단위 {levels['parcel']:,} / 법정동단위 {levels['umd']:,} "
              f"/ 실패 {levels['fail']:,}")
    return result
