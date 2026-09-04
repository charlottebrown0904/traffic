"""지번 주소 → 좌표 (VWorld). 캐시가 비용을 좌우하므로 캐시를 1급 시민으로 다룬다."""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import GEOCODE_CACHE, ensure_dirs, keys, settings
from .http import get

VWORLD_URL = "https://api.vworld.kr/req/address"


class GeocodeCache:
    def __init__(self, path: Path | None = None):
        self.path = path or GEOCODE_CACHE
        self._data: dict[str, dict] = {}
        # 워커 여러 개가 동시에 적는다. 잠그지 않으면 한 줄이 다른 줄
        # 가운데로 끼어들어 그 두 줄이 다음 실행에서 못 읽히는 JSON 이 된다.
        # 그러면 좌표를 이미 산 주소를 **돈 주고 다시 산다**.
        self._lock = threading.Lock()
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
        ensure_dirs()
        with self._lock:
            self._data[addr] = row
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def __len__(self) -> int:
        return len(self._data)


def purge_failures(cache: GeocodeCache) -> tuple[int, int]:
    """좌표 없이 기록된 캐시 항목을 지운다. (지운 수, 남은 수)

    예전 코드는 한도 초과도 '좌표 없는 주소' 로 캐시에 적었다. 그렇게 박힌
    항목은 한도가 풀려도 다시 물어보지 않는다. 지금은 구분하지만, **이미
    적힌 것들은 이유를 모른다** — 진짜 없는 주소인지 그날 한도에 걸린
    것인지 캐시에 남아 있지 않다.

    그래서 좌표 없는 항목을 통째로 버리고 다시 물어본다. 진짜 없는 주소를
    한 번 더 부르는 비용이 들지만, 붙을 수 있었던 주소를 영영 안 부르는
    것보다 낫다.
    """
    keep = {k: v for k, v in cache._data.items() if v.get("lat") is not None}
    dropped = len(cache._data) - len(keep)
    ensure_dirs()
    with open(cache.path, "w", encoding="utf-8") as fh:
        for row in keep.values():
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    cache._data = keep
    return dropped, len(keep)


def build_address(sido: str, sigungu: str, umd: str, jibun: str) -> str:
    parts = [p.strip() for p in (sido, sigungu, umd, jibun) if p and str(p).strip()]
    return " ".join(parts)


class QuotaExhausted(RuntimeError):
    """브이월드가 주소를 못 찾은 것이 아니라, 우리 쪽 문제로 못 준 경우."""


# ── 병렬 호출 ────────────────────────────────────────────────────────
#
# run 21 의 지오코딩이 2시간 58분 걸렸다. 호출 3만 건을 한 줄로 세워
# 한 건씩 부른 결과다. 한 건에 0.36초, 그중 대부분이 응답을 기다리는
# 시간이다 — CPU 는 놀고 있었다.
#
# 브이월드의 진짜 제약은 **하루 호출 수**(3만~4만)지 초당 속도가 아니다.
# 어차피 하루치를 다 쓰고 멈출 것이라면, 그것을 3시간에 걸쳐 쓸 이유가
# 없다. 워커를 여러 개 두고 전체 속도만 예의 있게 묶는다.
#
#   워커 8 · 초당 12건 → 3만 건에 42분  (기존 2시간 58분)
#
# 속도를 워커 수로만 정하면 안 된다. 응답이 빨라지는 날 초당 20건씩
# 때리게 되고, 그건 우리가 통제하지 못하는 값이다. 그래서 워커와 별개로
# **전체 속도 상한**을 둔다.


class _Pace:
    """호출 사이 간격을 전역으로 지킨다. 워커가 몇 개든 합쳐서 초당 N건."""

    def __init__(self, per_sec: float):
        self._gap = 1.0 / per_sec if per_sec > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if not self._gap:
            return
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next)
            self._next = at + self._gap
        delay = at - now
        if delay > 0:
            time.sleep(delay)


def _geo_cfg() -> dict:
    cfg = settings().get("geocode") or {}
    return {"workers": int(cfg.get("workers", 8) or 1),
            "calls_per_sec": float(cfg.get("calls_per_sec", 12) or 0)}


_PACE = None
_PACE_LOCK = threading.Lock()


def _pace() -> _Pace:
    global _PACE
    with _PACE_LOCK:
        if _PACE is None:
            _PACE = _Pace(_geo_cfg()["calls_per_sec"])
    return _PACE


def _drive(pending: list, work, label: str = "확보"
           ) -> tuple[int, Counter, str | None]:
    """pending 을 워커 여러 개로 처리한다.

    work(item) -> str | None    얻은 정밀도('parcel'·'umd') 또는 None.
                                캐시 쓰기까지 work 안에서 한다.
                                QuotaExhausted 를 올리면 **전체가 멈춘다**.
    반환 (처리한 수, 정밀도별 개수, 멈춘 이유 or None)

    한도에 걸린 뒤 새 호출을 시작하지 않는 것이 이 함수의 존재 이유다.
    순차 코드에서는 break 하나로 되던 일인데, 워커가 여럿이면 깃발을
    들어야 한다. 이것이 없으면 남은 주소가 전부 '좌표 없는 주소' 로
    캐시에 박히고, 한도가 풀려도 다시 물어보지 않는다.
    """
    counts: Counter = Counter()
    if not pending:
        return 0, counts, None

    cfg = _geo_cfg()
    workers = max(1, cfg["workers"])
    cps = cfg["calls_per_sec"]
    if workers > 1:
        # 실행 로그에서 '몇 개로 돌고 있나' 를 바로 보게 한다. 설정을
        # 바꿔놓고 안 먹은 것을 나중에 알면 한 판을 통째로 버린다.
        eta = f" · 예상 {len(pending) / cps / 60:.0f}분" if cps > 0 else ""
        print(f"  워커 {workers}개 · 전체 상한 초당 {cps:g}건{eta}", flush=True)
    stop = threading.Event()
    lock = threading.Lock()
    state = {"done": 0, "why": None}
    total = len(pending)

    def one(item):
        if stop.is_set():
            return                      # 아직 안 부른 것은 안 부른 채로 남긴다
        try:
            level = work(item)
        except QuotaExhausted as exc:
            stop.set()
            with lock:
                if state["why"] is None:
                    state["why"] = str(exc)
            return
        with lock:
            state["done"] += 1
            counts[level] += 1
            done, got = state["done"], state["done"] - counts[None]
        if done % 500 == 0:
            print(f"  {done:,}/{total:,}  {label} {got:,}", flush=True)

    if workers == 1:
        for item in pending:            # 검사에서 순서를 보고 싶을 때
            one(item)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, pending))
    return state["done"], counts, state["why"]


def geocode_one(address: str, kind: str = "PARCEL"
                ) -> tuple[float | None, float | None]:
    """좌표를 찾는다. 못 찾으면 (None, None).

    **'주소가 없다' 와 '우리가 못 물어봤다' 는 다르다.** 예전에는 둘 다
    (None, None) 이었고, 그 실패가 캐시에 NULL 로 박혔다. 하루 한도에
    걸리는 순간 남은 주소가 전부 '좌표 없는 주소' 로 영구 기록되고,
    한도가 풀려도 다시 물어보지 않는다. 로그에는 '실패 N건' 이라고만
    남아서 '시골 지번은 원래 잘 안 붙는구나' 로 읽힌다.

    그래서 시스템 오류는 예외로 올려 보낸다. 부르는 쪽이 멈추고,
    캐시에 아무것도 안 쓴다.
    """
    # 주소 하나가 호출 두 번이 되기도 한다(지번 실패 → 법정동). 속도는
    # **호출** 단위로 묶어야 실제로 지켜진다.
    _pace().wait()
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
    except ValueError:
        raise QuotaExhausted(f"응답이 JSON 이 아닙니다 (HTTP {resp.status_code})")

    body = payload.get("response", {})
    status = body.get("status")
    if status == "OK":
        try:
            point = body["result"]["point"]
            return float(point["y"]), float(point["x"])
        except (KeyError, TypeError, ValueError):
            # OK 인데 좌표를 못 읽는 것은 응답 모양이 바뀐 것이다.
            raise QuotaExhausted("OK 인데 좌표 칸을 못 읽었습니다 — 응답 모양 확인")
    if status == "NOT_FOUND":
        return None, None          # 진짜로 없는 주소. 캐시에 남겨도 된다.

    # ERROR 그 밖의 무엇이든 — 한도 초과·인증 오류·장애. 우리 문제다.
    err = body.get("error") or {}
    raise QuotaExhausted(
        f"status={status} code={err.get('code')} text={err.get('text')}")


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


def _say_stopped(stopped: str | None, done: int, total: int) -> None:
    """한도에 걸려 멈췄으면, 몇 건에서 걸렸는지를 크게 말한다.

    이 숫자가 곧 '오늘 실제로 쓸 수 있는 호출 수' 다. 추측한 4,000 을
    코드에 박아두는 대신 매 실행에서 측정한다.
    """
    if not stopped:
        return
    print()
    print(f"  ⛔ {done:,}건째에서 멈췄습니다 — {stopped}")
    print(f"     남은 {total - done:,}건은 캐시에 아무것도 쓰지 않았습니다.")
    print(f"     다음 실행이 그대로 이어받습니다.")
    workers = _geo_cfg()["workers"]
    about = "" if workers <= 1 else f" (워커 {workers}개 — ±{workers} 오차)"
    print(f"     **{done:,} 이 오늘 쓸 수 있었던 실제 한도입니다{about}.**")


def geocode_many(rows: list[tuple[str, str, str]], cache: GeocodeCache | None = None,
                 limit: int | None = None) -> dict[tuple, tuple]:
    """rows: (시군구, 법정동, 지번) 튜플 목록 → {튜플: (lat, lon, level)}"""
    # `cache or GeocodeCache()` 로 쓰면 안 된다. __len__ 이 0 인 **빈 캐시는
    # falsy** 라, 호출자가 건넨 캐시가 조용히 버려지고 기본 경로의 캐시가
    # 새로 만들어진다. 실제 운영에서는 캐시가 대개 비어 있지 않아 안 드러나고,
    # 검사에서 처음 드러났다 — 검사용 캐시를 건넸는데 진짜 파일에 썼다.
    if cache is None:
        cache = GeocodeCache()
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

    def work(row):
        # 한도에 걸리면 QuotaExhausted 가 여기서 올라가고, _drive 가
        # 남은 주소를 부르지 않는다. 캐시에는 아무것도 안 쓴다.
        lat, lon, level = geocode_with_fallback(*row)
        cache.put(build_address(None, *row), lat, lon, "vworld", level)
        # dict 한 칸 쓰기는 스레드 사이에서 쪼개지지 않는다 (CPython).
        result[row] = (lat, lon, level)
        return level

    done, counts, stopped = _drive(pending, work)
    if pending:
        print(f"  결과: 지번단위 {counts['parcel']:,} / 법정동단위 {counts['umd']:,} "
              f"/ 주소 없음 {counts[None]:,}")
        _say_stopped(stopped, done, len(pending))
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
    # `cache or GeocodeCache()` 로 쓰면 안 된다. __len__ 이 0 인 **빈 캐시는
    # falsy** 라, 호출자가 건넨 캐시가 조용히 버려지고 기본 경로의 캐시가
    # 새로 만들어진다. 실제 운영에서는 캐시가 대개 비어 있지 않아 안 드러나고,
    # 검사에서 처음 드러났다 — 검사용 캐시를 건넸는데 진짜 파일에 썼다.
    if cache is None:
        cache = GeocodeCache()
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
    def work(pair):
        key = coarse_key(*pair)
        lat, lon = geocode_one(key, "PARCEL")
        cache.put(key, lat, lon, "vworld", "umd")
        if lat is None:
            return None
        result[pair] = (lat, lon, "umd")
        return "umd"

    done, counts, stopped = _drive(pending, work)
    if pending:
        print(f"  결과: 확보 {done - counts[None]:,} / 주소 없음 {counts[None]:,}")
        _say_stopped(stopped, done, len(pending))
    return result


def geocode_parcel(rows: list[tuple[str, str, str]],
                   cache: GeocodeCache | None = None,
                   limit: int | None = None) -> dict[tuple, tuple]:
    """지번 단위로 올린다. **법정동 중심점으로 되돌아가지 않는다.**

    되돌아가면 거친 좌표가 지번 키에 굳어, 다음에 다시 시도할 수 없게
    된다. 실패는 실패로 남겨 두면 나중에 다시 해볼 수 있다.
    """
    # `cache or GeocodeCache()` 로 쓰면 안 된다. __len__ 이 0 인 **빈 캐시는
    # falsy** 라, 호출자가 건넨 캐시가 조용히 버려지고 기본 경로의 캐시가
    # 새로 만들어진다. 실제 운영에서는 캐시가 대개 비어 있지 않아 안 드러나고,
    # 검사에서 처음 드러났다 — 검사용 캐시를 건넸는데 진짜 파일에 썼다.
    if cache is None:
        cache = GeocodeCache()
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
    def work(row):
        key = build_address(None, *row)
        lat, lon = geocode_one(key, "PARCEL")
        cache.put(key, lat, lon, "vworld",
                  "parcel" if lat is not None else None)
        if lat is None:
            return None
        result[row] = (lat, lon, "parcel")
        return "parcel"

    done, counts, stopped = _drive(pending, work)
    if pending:
        print(f"  결과: 지번단위 확보 {done - counts[None]:,} "
              f"/ 주소 없음 {counts[None]:,}")
        _say_stopped(stopped, done, len(pending))
    return result
