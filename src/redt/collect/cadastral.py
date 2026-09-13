"""연속지적도(SHP) → 필지 좌표.

**왜 필요한가.** std_land 60만 필지에 좌표가 없다. 좌표가 없으면 비교표준지를
평가사처럼 '같은 인근지역에서' 고르지 못한다 — 지금은 같은 법정동리인지와
속성만 보고, 그 빈자리를 개별공시지가로 메우려다 전국 검산에서 적중이
떨어졌다 (docs/radar-and-current-value.md §8). 좌표가 들어오면 그 자리가
메워진다. 덤으로, 실거래를 지번 지오코딩이 아니라 **PNU 로** 필지에 붙일 수
있다 — 지금은 거래면적이 필지면적과 안 맞는 건이 셋 중 둘이라 그 밖의 요인
표본을 크게 버리고 있다 (#40).

**무엇을 읽는가.** V-WORLD 디지털트윈국토의 `연속지적도_전국` 데이터셋은
시군구·일반구마다 `LSMD_CONT_LDREG_<시도>_<시군구>.zip` 한 장이다(276개,
합계 약 7GB). 압축 안에 .shp/.dbf/.shx/.prj 가 들어 있고, 레코드마다 PNU 와
필지 도형이 있다.

**어떻게 가볍게 읽는가.**
  · pyshp 로 읽는다 — 순수 파이썬이라 GDAL 이 필요 없다.
  · 도형 전체가 아니라 **레코드의 경계상자 가운데**만 쓴다. 필지는 작고
    볼록한 편이라 이것으로 족하다 (api/tile.js geomCenter 와 같은 방식).
    shapefile 은 폴리곤마다 bbox 를 헤더에 들고 있어 점을 다 읽지 않아도 된다.
  · 원하는 PNU 집합을 주면 그것만 남긴다 — 한 파일 13만 필지 중 표준지는
    수천 개다.
  · 파일 하나를 받아 → 읽고 → 지운다. 디스크는 100MB 를 안 넘는다.

**좌표계.** 연속지적도는 지역마다 원점이 다르다(중부 5186 · 서부 5185 ·
동부 5187 · 동해 5188, 옛 자료는 5174 계열). .prj 를 읽어 pyproj 로 WGS84 로
옮긴다. .prj 가 없거나 못 읽으면 그 파일은 **건너뛴다** — 원점을 찍어 맞추면
전국이 조용히 수백 미터씩 어긋난다.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Iterator

# 우리나라 지적 좌표계. **가산값으로 가르면 안 된다** — 2010 계열(5186)과
# 옛 계열(5174)이 둘 다 북쪽 가산 60만을 쓴다. 둘은 데이텀이 다르고(GRS80 대
# 베셀), 그 차이가 실제 위치로 100~200m 다. 그래서 데이텀을 먼저 본다.
_BELT = {"125": ("서부", 5185, 5173), "127": ("중부", 5186, 5174),
         "129": ("동부", 5187, 5176), "131": ("동해", 5188, 5177)}
_OLD_DATUM = re.compile(r"BESSEL|KOREAN_?1985|KOREAN_?DATUM|TOKYO", re.I)
_NEW_DATUM = re.compile(r"GRS_?1980|KOREA_?2000|ITRF|WGS_?1984|WGS84", re.I)


def epsg_from_prj(prj: str) -> int | None:
    """.prj 글자에서 EPSG 코드를 고른다. 못 고르면 None (그 파일은 건너뛴다).

    순서: ① 파일에 적힌 EPSG 권한코드 ② UTM-K(5179) ③ 원점 경도로 띠를 고르고
    데이텀으로 새 계열(2010)·옛 계열을 가른다. 데이텀이 애매하면 None 이다 —
    찍어 맞히면 전국이 조용히 100~200m 어긋난다.
    """
    if not prj:
        return None
    m = re.search(r'AUTHORITY\s*\[\s*"EPSG"\s*,\s*"?(\d{4,5})"?', prj, re.I)
    if m:
        return int(m.group(1))
    flat = prj.replace(" ", "")
    lon = re.search(r'CENTRAL_MERIDIAN",(-?\d+(?:\.\d+)?)', flat, re.I)
    east = re.search(r'FALSE_EASTING",(-?\d+(?:\.\d+)?)', flat, re.I)
    if not lon:
        return None
    lon_v = float(lon.group(1))
    # UTM-K — 전국 한 장짜리 좌표계. 원점 127.5 · 동쪽 가산 100만.
    if abs(lon_v - 127.5) < 0.01 and east and abs(float(east.group(1)) - 1_000_000) < 1:
        return 5179
    # 5174 는 원점이 127.00289 다 (옛 도쿄 데이텀 보정). 소수점이 살아 있으면 그것만으로 갈린다.
    if abs(lon_v - 127.0028902777778) < 1e-4:
        return 5174
    belt = _BELT.get(str(int(round(lon_v))))
    if not belt:
        return None
    _, new_code, old_code = belt
    if _OLD_DATUM.search(prj):
        return old_code
    if _NEW_DATUM.search(prj):
        return new_code
    return None


def _member(names: list[str], ext: str) -> str | None:
    hit = [n for n in names if n.lower().endswith(ext)]
    return hit[0] if hit else None


def centroids_from_zip(path: Path, want: set[str] | None = None,
                       pnu_field: str = "PNU") -> Iterator[tuple[str, float, float]]:
    """zip 한 장에서 (PNU, 경도, 위도) 를 낸다. want 를 주면 그 PNU 만.

    좌표계를 못 읽으면 아무것도 내지 않는다 — 틀린 좌표보다 없는 편이 낫다.
    """
    import pyproj                                      # noqa: PLC0415
    import shapefile                                   # noqa: PLC0415

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shp, dbf, shx = (_member(names, e) for e in (".shp", ".dbf", ".shx"))
        prj = _member(names, ".prj")
        if not (shp and dbf and shx):
            return
        code = epsg_from_prj(z.read(prj).decode("utf-8", "replace")) if prj else None
        if not code:
            return
        tf = pyproj.Transformer.from_crs(f"EPSG:{code}", "EPSG:4326", always_xy=True)
        # 지적 자료의 dbf 는 대개 CP949 다. 실패하면 latin-1 로 읽어도 PNU(숫자)는
        # 멀쩡하다 — 우리가 쓰는 것은 그 열뿐이다.
        with io.BytesIO(z.read(shp)) as fshp, io.BytesIO(z.read(dbf)) as fdbf, \
                io.BytesIO(z.read(shx)) as fshx:
            try:
                r = shapefile.Reader(shp=fshp, dbf=fdbf, shx=fshx, encoding="cp949")
                fields = [f[0] for f in r.fields[1:]]
            except UnicodeDecodeError:
                fshp.seek(0); fdbf.seek(0); fshx.seek(0)
                r = shapefile.Reader(shp=fshp, dbf=fdbf, shx=fshx,
                                     encoding="latin-1", encodingErrors="replace")
                fields = [f[0] for f in r.fields[1:]]
            idx = None
            for cand in (pnu_field, "pnu", "PNU_CD", "고유번호"):
                if cand in fields:
                    idx = fields.index(cand)
                    break
            if idx is None:
                return
            for sr in r.iterShapeRecords():
                pnu = str(sr.record[idx] or "").strip()
                if not pnu or (want is not None and pnu not in want):
                    continue
                bb = getattr(sr.shape, "bbox", None)
                if not bb or len(bb) != 4:
                    continue
                x = (bb[0] + bb[2]) / 2.0
                y = (bb[1] + bb[3]) / 2.0
                lon, lat = tf.transform(x, y)
                # 우리나라 밖이면 좌표계를 잘못 읽은 것이다 — 버린다.
                if not (124.0 <= lon <= 132.0 and 33.0 <= lat <= 39.0):
                    continue
                yield pnu, round(lon, 6), round(lat, 6)
