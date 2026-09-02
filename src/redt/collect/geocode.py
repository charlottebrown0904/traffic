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


# ── 2단계 지오코딩 ────────────────────────────────────────────────────
#
# 좌표 없는 거래가 329만 건인데 브이월드 하루 한도는 4,000건입니다. 그대로면
# 822번 실행해야 합니다. **전국을 다 붙일 필요가 없다는 것이 답입니다.**
#
#   1단계  법정동 중심점을 붙인다. 법정동 하나에 한 번만 부르므로 전국
#          2만 번이면 끝나고, 그 뒤로는 모든 거래가 공짜로 대략 위치를
#          갖는다. 거리 밴드에는 못 쓰지만 '어느 영업소 근처인가' 를
#          가리는 데는 충분하다.
#   2단계  영업소 반경 안에 드는 법정동의 거래만 지번 단위로 올린다.
#
# 예전 구조로는 이것이 불가능했습니다. geocode_with_fallback 이 **법정동
# 중심점 결과를 지번까지 붙은 주소로 캐싱**했기 때문입니다.
#
#   "화성시 장안면 사랑리 123-4" → (동 중심점, level=umd)
#
# 같은 법정동의 거래 100건이면 같은 점을 100번 새로 부르고, 게다가 한 번
# umd 로 굳으면 나중에 지번으로 올리려 해도 캐시가 막습니다. 그래서
# 거친 결과는 **거친 키**에, 지번 결과는 지번 키에 따로 둡니다.


def coarse_key(sigungu: str, umd: str) -> str:
    """법정동까지의 주소. 이 단위로 캐싱해야 한 번만 부른다."""
    return build_address(None, sigungu, umd, None)


def geocode_umd(pairs: list[tuple[str, str]], cache: GeocodeCache | None = None,
                limit: int | None = None) -> dict[tuple, tuple]:
    """법정동 중심점을 붙인다. (시군구, 법정동) 하나당 한 번만 부른다."""
    cache = cache or GeocodeCache()
    result: dict[tuple, tuple] = {}
    pending = []
    for pair in dict.fromkeys(pairs):          # 순서를 지키며 중복 제거
        key = coarse_key(*pair)
        if not key:
            continue
        hit = cache.get(key)
        if hit is not None:
            if hit["lat"] is not None:
                result[pair] = (hit["lat"], hit["lon"], "umd")
        else:
            pending.append(pair)
    if limit is not None:
        pending = pending[:limit]

    print(f"법정동 중심점: 캐시 적중 {len(result):,} / 신규 {len(pending):,} "
          f"(법정동 단위라 거래 건수와 무관합니다)")
    ok = 0
    for i, pair in enumerate(pending, 1):
        key = coarse_key(*pair)
        lat, lon = geocode_one(key, "PARCEL")
        cache.put(key, lat, lon, "vworld", "umd")
        if lat is not None:
            result[pair] = (lat, lon, "umd")
            ok += 1
        polite_sleep(0.05)
        if i % 500 == 0:
            print(f"  {i:,}/{len(pending):,}  확보 {ok:,}")
    if pending:
        print(f"  결과: 확보 {ok:,} / 실패 {len(pending) - ok:,}")
    return result


def geocode_parcel(rows: list[tuple[str, str, str]],
                   cache: GeocodeCache | None = None,
                   limit: int | None = None) -> dict[tuple, tuple]:
    """지번 단위로 올린다. **법정동 중심점으로 되돌아가지 않는다.**

    되돌아가면 거친 좌표가 지번 키에 굳어, 다음에 다시 시도할 수 없게
    된다. 실패는 실패로 남겨 두면 나중에 다시 해볼 수 있다.
    """
    cache = cache or GeocodeCache()
    result: dict[tuple, tuple] = {}
    pending = []
    for row in dict.fromkeys(rows):
        if not (row[2] and str(row[2]).strip()):
            continue                            # 지번이 없으면 올릴 수 없다
        key = build_address(None, *row)
        hit = cache.get(key)
        if hit is not None:
            if hit["lat"] is not None:
                result[row] = (hit["lat"], hit["lon"], hit.get("level") or "parcel")
        else:
            pending.append(row)
    if limit is not None:
        pending = pending[:limit]

    print(f"지번 단위: 캐시 적중 {len(result):,} / 신규 {len(pending):,}")
    ok = 0
    for i, row in enumerate(pending, 1):
        lat, lon = geocode_one(build_address(None, *row), "PARCEL")
        cache.put(build_address(None, *row), lat, lon, "vworld",
                  "parcel" if lat is not None else None)
        if lat is not None:
            result[row] = (lat, lon, "parcel")
            ok += 1
        polite_sleep(0.05)
        if i % 500 == 0:
            print(f"  {i:,}/{len(pending):,}  확보 {ok:,}")
    if pending:
        print(f"  결과: 지번단위 확보 {ok:,} / 실패 {len(pending) - ok:,}")
    return result
