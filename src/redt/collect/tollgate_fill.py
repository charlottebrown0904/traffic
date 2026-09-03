"""교통량 파일에만 있고 영업소 마스터에 없는 영업소의 좌표를 이름으로 채운다.

왜 필요한가
-----------
영업소 마스터는 한국도로공사 API(locationinfoUnit)에서 받는다. 그런데 교통량
파일에는 **민자고속도로** 영업소가 함께 들어 있다. 도로공사가 운영하지 않는
노선이라 그 API 에는 없다. 진단(`redt.cli gaps`)에서 이렇게 나왔다.

    교통량 파일에 있는 영업소   475
    영업소 마스터에 등재        401
    그중 좌표 있음              401   ← 좌표 결측은 0건이었다
    교통량과 마스터가 짝맞음    395

빠진 80개는 좌표가 없는 게 아니라 **명단 자체에 없다**. 그런데 그 안에
서시흥·남안산·송산마도·조암·봉담·정남·북오산 처럼 우리가 거래를 수집한
경기권 영업소가 들어 있다. 교통량 상위권(연 2억 대)도 여럿이다. 빼놓고
분석하면 수도권 서남부가 통째로 비는 셈이다.

어떻게 채우는가
---------------
교통량 CSV 에 영업소명이 있으므로 이름으로 좌표를 찾는다. VWorld 장소검색을
쓰되, **이름이 비슷하다고 그냥 믿지 않는다.** 잘못 찍힌 좌표 하나가 거리
밴드를 통째로 뒤집기 때문에, 아래를 모두 통과한 것만 저장한다.

  1. 한반도 좌표 범위 안일 것
  2. 검색 결과 이름에 우리가 찾는 영업소 이름이 실제로 들어 있을 것
  3. 이미 마스터에 있는 다른 영업소와 200m 안으로 겹치지 않을 것

통과하지 못한 것은 채우지 않고 이유와 함께 남긴다. 억지로 채우면 '좌표가
없어서 빠진 것' 이 '엉뚱한 자리에 찍힌 것' 으로 바뀔 뿐이라 더 나쁘다.

저장할 때 src 를 'poi' 로 적어 도로공사 원본('ex')과 구분한다. 출처가 섞이면
나중에 좌표를 의심할 때 어느 것을 의심해야 할지 알 수 없다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from ..config import RAW, INTERIM, ensure_dirs, keys
from ..ids import canon_series
from .http import get, get_once, polite_sleep

SEARCH_URL = "https://api.vworld.kr/req/search"
ADDRESS_URL = "https://api.vworld.kr/req/address"
CACHE = INTERIM / "tollgate_poi_cache.jsonl"
REGION_CACHE = INTERIM / "tollgate_region_cache.jsonl"

# 연달아 이만큼 **호출이** 실패하면 창구가 막힌 것으로 보고 멈춘다.
#
# '찾았는데 없더라' 는 여기 세지 않는다. 둘은 다른 일이다. 민자 영업소
# 이름이 장소 색인에 없는 것은 정상이고, 그걸로 멈추면 뒤쪽 80개를 아예
# 시도조차 못 한다. 실제로 그렇게 2초 만에 서 버렸다.
GIVE_UP_STREAK = 15

class CallFailed(RuntimeError):
    """창구가 막힌 것. '찾았는데 없더라' 와 구분하려고 따로 둔다."""


KOREA_LAT = (33.0, 39.0)
KOREA_LON = (124.0, 132.0)
DUP_METERS = 200.0

# 영업소명은 그 자체로는 검색이 잘 안 된다. '서시흥' 은 지명이기도 해서
# 엉뚱한 상가가 먼저 나온다. 접미사를 붙여 시설로 좁히고, 실패하면 다음을 쓴다.
SUFFIXES = ("영업소", "요금소", "IC", "나들목", "톨게이트")

# 본선영업소·JC 는 나들목이 아니라 노선 위 시설이라 접미사 규칙이 다르다.
TRIM = ("본선", "JC", "분기점")


# 도로공사가 내려주는 영업소 명부. 교통량 파일에는 이름이 없어서
# 지금까지 2025년 연간 파일에서 이름을 빌려 왔는데, 그 파일은 **그 뒤에
# 생긴 영업소를 모른다.** 2026년 신설 327 이 이름 없이 들어와 좌표를
# 못 찾은 것이 그 때문이다. 명부가 있으면 그것이 우선이다.
MASTER_GLOB = "tollgate_master_*.csv"


def names_from_master() -> dict[str, str]:
    """도로공사 영업소 명부에서 코드 → 이름. 가장 최근 파일을 쓴다."""
    files = sorted(Path(RAW).glob(MASTER_GLOB))
    if not files:
        return {}
    df = pd.read_csv(files[-1], encoding="utf-8-sig", dtype=str)
    if "영업소코드" not in df or "영업소명" not in df:
        return {}
    # 가상 영업소(가상영업소여부 Y)는 실제 시설이 아니다 — 좌표를 찾으면
    # 엉뚱한 곳이 찍힌다.
    if "가상영업소여부" in df:
        df = df[df["가상영업소여부"].fillna("").str.strip() != "Y"]
    out: dict[str, str] = {}
    for tid, name in zip(canon_series(df["영업소코드"]), df["영업소명"]):
        if isinstance(name, str) and name.strip():
            out[tid] = name.strip()
    return out


def names_from_traffic() -> dict[str, str]:
    """영업소코드 → 영업소명. 명부가 있으면 그것이 이긴다."""
    out: dict[str, str] = {}
    for path in sorted(Path(RAW).glob("tcs_annual_*.csv")):
        if path.name.startswith("legacy_"):
            continue
        df = pd.read_csv(path, encoding="utf-8-sig", usecols=["영업소코드", "영업소명"])
        df["tollgate_id"] = canon_series(df["영업소코드"])
        for tid, name in zip(df["tollgate_id"], df["영업소명"]):
            if isinstance(name, str) and name.strip():
                out[tid] = name.strip()          # 최신 파일 이름이 이긴다
    # 교통량 파일의 이름은 '영업소 327' 처럼 코드로 채워 둔 것이 섞인다.
    # 명부에 진짜 이름이 있으면 그것으로 덮는다 — 코드 이름으로는
    # 좌표를 못 찾는다.
    master = names_from_master()
    if master:
        replaced = sum(1 for k in out if k in master and out[k] != master[k])
        out.update(master)
        if replaced:
            print(f"  영업소 명부에서 이름 {replaced}건을 바로잡았습니다")
    return out


class _Cache:
    """질의 → 결과. **API 가 답한 것만** 적는다.

    '답을 받았는데 해당 없음' 은 적어 둔다 — 안 그러면 매번 같은 걸 또 묻는다.
    반대로 '호출이 실패함' 은 적지 않는다. 키가 없거나 중계기가 잠깐 죽은 것을
    '그런 곳은 없다' 로 굳혀 두면, 원인을 고친 뒤 다시 돌려도 영원히 못 찾는다.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or CACHE
        self.data: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.data[row["q"]] = row

    def get(self, q: str) -> dict | None:
        return self.data.get(q)

    def put(self, q: str, row: dict) -> None:
        row = {"q": q, **row}
        self.data[q] = row
        ensure_dirs()
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def search_place(query: str, cache: _Cache) -> dict | None:
    """VWorld 장소검색. 실패는 예외가 아니라 None 으로 돌려준다."""
    hit = cache.get(query)
    if hit is not None:
        return hit if hit.get("lat") is not None else None

    try:
        # 재시도하지 않는다. 없는 이름은 네 번 물어도 없다. 영업소 80개 ×
        # 접미사 다섯 개면 400번인데, 실패마다 2·4·8초를 기다리면 그 헛기다림만
        # 으로 작업 시간 제한에 걸린다 (탐침에서 이미 한 번 당했다).
        resp = get_once(SEARCH_URL, {
            "service": "search", "request": "search", "version": "2.0",
            "crs": "EPSG:4326", "size": 10, "page": 1,
            "query": query, "type": "place", "format": "json",
            "key": keys().require("vworld"),
        })
        payload = resp.json()
    except Exception as exc:                       # noqa: BLE001
        # 호출 자체가 실패한 것은 캐시하지 않는다. 키가 없거나 중계기가 잠깐
        # 죽은 것을 '그런 곳은 없다' 로 굳혀 두면, 고친 뒤에 다시 돌려도
        # 영원히 안 찾는다. '답을 받았는데 없더라' 만 캐시한다.
        raise CallFailed(str(exc)[:200]) from exc

    result = (payload.get("response") or {}).get("result") or {}
    items = result.get("items") or []
    rows = []
    for item in items:
        point = item.get("point") or {}
        try:
            lat, lon = float(point["y"]), float(point["x"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({"lat": lat, "lon": lon, "title": item.get("title") or ""})

    # 고른 것을 그대로 두고 candidates 에 rows 를 넣으면 자기 자신을 담게 되어
    # json.dumps 가 'Circular reference detected' 로 죽는다. 실제로 죽었다.
    # 사본을 만들고, 후보에는 고르지 않은 것만 남긴다.
    picked = dict(rows[0]) if rows else {"lat": None, "lon": None, "title": None}
    picked["candidates"] = [dict(r) for r in rows[1:5]]
    cache.put(query, picked)
    return picked if picked.get("lat") is not None else None


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _core(name: str) -> str:
    """'장안본선' → '장안', '기장서JC' → '기장서'. 접미사 규칙을 붙이기 위한 어간."""
    out = name
    for token in TRIM:
        out = out.replace(token, "")
    return out.strip() or name


def _accept(name: str, row: dict, known: list[tuple[float, float]]) -> tuple[bool, str]:
    lat, lon = row["lat"], row["lon"]
    if not (KOREA_LAT[0] <= lat <= KOREA_LAT[1] and KOREA_LON[0] <= lon <= KOREA_LON[1]):
        return False, f"한반도 밖 ({lat:.4f},{lon:.4f})"
    title = row.get("title") or ""
    core = _core(name)
    if core and core not in title.replace(" ", ""):
        return False, f"이름 불일치 (찾음: {title})"
    for klat, klon in known:
        d = _haversine_m(lat, lon, klat, klon)
        if d < DUP_METERS:
            return False, f"기존 영업소와 {d:.0f}m — 같은 지점으로 보임"
    return True, title


def fill_missing(con, limit: int | None = None) -> pd.DataFrame:
    """마스터에 없는 영업소를 이름으로 찾아 채운다. 채운 행을 돌려준다."""
    names = names_from_traffic()
    if not names:
        print("  교통량 CSV 가 없어 이름을 얻을 수 없습니다.")
        return pd.DataFrame()

    have = {r[0] for r in con.execute(
        "SELECT tollgate_id FROM tollgate WHERE lat IS NOT NULL").fetchall()}
    known = con.execute(
        "SELECT lat, lon FROM tollgate WHERE lat IS NOT NULL").fetchall()
    known = [(float(a), float(b)) for a, b in known]

    traffic_ids = {r[0] for r in con.execute(
        "SELECT DISTINCT tollgate_id FROM traffic").fetchall()}
    todo = sorted(traffic_ids - have, key=lambda t: int(t) if t.isdigit() else 0)
    if limit:
        todo = todo[:limit]
    print(f"  마스터에 없는 영업소 {len(todo)}개 — 이름으로 좌표를 찾습니다",
          flush=True)

    cache = _Cache()
    filled, failed = [], []
    err_streak = 0
    stopped = False
    for done, tid in enumerate(todo, 1):
        if done % 10 == 0:
            print(f"    …{done}/{len(todo)} (확보 {len(filled)})", flush=True)
        name = names.get(tid)
        if not name:
            failed.append((tid, "", "교통량 파일에 이름이 없음"))
            continue

        core = _core(name)
        picked, why = None, "검색 결과 없음"
        call_failed = False
        for suffix in SUFFIXES:
            try:
                row = search_place(f"{core}{suffix}", cache)
            except CallFailed as exc:
                why, call_failed = f"호출 실패 — {exc}"[:160], True
                continue
            if row is None:
                continue
            ok, detail = _accept(name, row, known)
            if ok:
                picked, why = row, detail
                break
            why = detail
            polite_sleep()

        # 창구가 막힌 것만 연속으로 센다. '없더라' 로는 멈추지 않는다.
        err_streak = err_streak + 1 if call_failed else 0
        if err_streak >= GIVE_UP_STREAK:
            failed.append((tid, name, why))
            print(f"  ⚠ 호출이 {GIVE_UP_STREAK}번 연속 실패했습니다 — 이름 문제가 아니라"
                  " 검색 창구가 막힌 것으로 보고 멈춥니다.", flush=True)
            print(f"    마지막 사유: {why}", flush=True)
            stopped = True
            break

        if picked is None:
            failed.append((tid, name, why))
            continue

        filled.append({
            "tollgate_id": tid, "name": name, "route_no": None,
            "lat": picked["lat"], "lon": picked["lon"],
            "sido": None, "sigungu": None, "sigungu_cd": None,
            "is_open_type": None, "src": "poi",
        })
        known.append((picked["lat"], picked["lon"]))

    if stopped:
        print(f"  ⚠ 중간에 멈췄습니다 — {len(todo)}개 중 {len(filled) + len(failed)}개만 시도했습니다.")
    print(f"  좌표 확보 {len(filled)}개 · 실패 {len(failed)}개")
    if failed:
        kinds: dict[str, int] = {}
        for _, _, why in failed:
            head = why.split("(")[0].split("—")[0].strip()[:24]
            kinds[head] = kinds.get(head, 0) + 1
        print("  실패 사유별: " + " · ".join(
            f"{k} {v}건" for k, v in sorted(kinds.items(), key=lambda x: -x[1])))
        print("  --- 못 찾은 영업소 (상위 20) ---")
        for tid, name, why in failed[:20]:
            print(f"    {tid:>5}  {name or '(이름없음)':<10}  {why}")
    return pd.DataFrame(filled)


def reverse_region(lat: float, lon: float, cache: _Cache) -> tuple[str, str] | None:
    """좌표 → (시도, 시군구). 실패는 None.

    영업소 마스터에는 시도·시군구가 아예 오지 않는다. 순위표에서 '경기도 시흥시'
    가 안 보이면 이름만으로 어디인지 짐작해야 하는데, 그건 이 화면을 처음 보는
    사람에게는 불가능하다.
    """
    key = f"rev:{lat:.5f},{lon:.5f}"
    hit = cache.get(key)
    if hit is not None:
        return (hit["sido"], hit["sigungu"]) if hit.get("sido") else None

    try:
        resp = get(ADDRESS_URL, {
            "service": "address", "request": "getAddress", "version": "2.0",
            "crs": "EPSG:4326", "point": f"{lon},{lat}", "type": "both",
            "format": "json", "key": keys().require("vworld"),
        })
        payload = resp.json()
    except Exception as exc:                       # noqa: BLE001
        # 호출 실패는 캐시하지 않는다 (search_place 와 같은 이유)
        raise CallFailed(str(exc)[:200]) from exc

    items = (payload.get("response") or {}).get("result") or []
    for item in items:
        struct = item.get("structure") or {}
        sido = (struct.get("level1") or "").strip()
        sigungu = (struct.get("level2") or "").strip()
        if sido:
            cache.put(key, {"sido": sido, "sigungu": sigungu})
            return sido, sigungu
    cache.put(key, {"sido": None, "sigungu": None})
    return None


def fill_regions(con, limit: int | None = None) -> int:
    """좌표는 있는데 시도·시군구가 비어 있는 영업소를 역지오코딩으로 채운다."""
    rows = con.execute("""
        SELECT tollgate_id, lat, lon FROM tollgate
        WHERE lat IS NOT NULL AND (sido IS NULL OR sido = '')
        ORDER BY tollgate_id
    """).fetchall()
    if limit:
        rows = rows[:limit]
    if not rows:
        print("  시도·시군구가 빈 영업소가 없습니다.")
        return 0

    print(f"  시도·시군구가 빈 영업소 {len(rows)}개 — 좌표로 되짚습니다", flush=True)
    cache = _Cache(REGION_CACHE)
    filled = 0
    err_streak = 0
    for done, (tid, lat, lon) in enumerate(rows, 1):
        if done % 50 == 0:
            print(f"    …{done}/{len(rows)} (채움 {filled})", flush=True)
        try:
            region = reverse_region(float(lat), float(lon), cache)
        except CallFailed as exc:
            err_streak += 1
            if err_streak >= GIVE_UP_STREAK:
                print(f"  ⚠ 호출이 {GIVE_UP_STREAK}번 연속 실패했습니다 — 역지오코딩"
                      f" 창구가 막힌 것으로 보고 멈춥니다. 마지막 사유: {exc}", flush=True)
                break
            continue
        err_streak = 0
        if region is None:
            continue
        con.execute("UPDATE tollgate SET sido = ?, sigungu = ? WHERE tollgate_id = ?",
                    [region[0], region[1], tid])
        filled += 1
        polite_sleep()
    print(f"  지역 채움 {filled}/{len(rows)}")
    return filled
