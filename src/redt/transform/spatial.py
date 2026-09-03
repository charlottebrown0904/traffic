"""거래 좌표 ↔ 영업소 좌표 공간 조인.

전국 거래 수십만 × 영업소 수백 개는 벡터화된 haversine 으로 충분히 빠르다.
(geopandas/PostGIS 없이 numpy 만으로 처리)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import band_label, settings

EARTH_RADIUS_KM = 6371.0088


def haversine_matrix(lat1, lon1, lat2, lon2) -> np.ndarray:
    """(n,) 과 (m,) 좌표 배열 → (n, m) 거리 행렬(km)."""
    lat1 = np.radians(np.asarray(lat1, dtype=float))[:, None]
    lon1 = np.radians(np.asarray(lon1, dtype=float))[:, None]
    lat2 = np.radians(np.asarray(lat2, dtype=float))[None, :]
    lon2 = np.radians(np.asarray(lon2, dtype=float))[None, :]

    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def link_trades_to_tollgates(trades: pd.DataFrame, tollgates: pd.DataFrame,
                             chunk_size: int = 20_000) -> pd.DataFrame:
    """max_link_km 이내 모든 (거래, 영업소) 쌍을 만든다.

    is_nearest 는 **교통량이 있는 영업소 중** 가장 가까운 것을 가리킨다.
    tollgates 에 no_traffic 칸이 있으면 그것으로 가른다.

    왜 그냥 '가장 가까운 영업소' 가 아닌가. 패널은 is_nearest 행만 쓴다
    (transform/panel.py 의 nearest_only). 그런데 도로공사 TCS 에 통행량이
    없는 민자 영업소를 지도에 띄우려고 영업소 표에 등재하는 순간, 그
    영업소가 어떤 거래의 '가장 가까운 곳' 이 된다. 그 거래는 교통량을
    붙일 수 없어 패널에서 통째로 빠진다 — **지도를 고쳤더니 분석 표본이
    줄어드는** 모양이다. 화성 남부처럼 우리가 가장 보고 싶은 지역이
    정확히 그렇게 빈다.

    그래서 연결 자체는 전부 만들되(지도·상세는 이것을 쓴다), '패널에
    쓸 대표 영업소' 는 교통량이 있는 곳 중에서 고른다.
    """
    max_km = float(settings()["spatial"]["max_link_km"])
    trades = trades.dropna(subset=["lat", "lon"])
    tollgates = tollgates.dropna(subset=["lat", "lon"])
    if trades.empty or tollgates.empty:
        return pd.DataFrame(
            columns=["trade_id", "tollgate_id", "distance_km", "band", "is_nearest"]
        )

    tg_ids = tollgates["tollgate_id"].to_numpy()
    # 대표를 뽑을 후보. 칸이 없으면 예전처럼 전부가 후보다.
    if "no_traffic" in tollgates.columns:
        usable = ~tollgates["no_traffic"].fillna(False).to_numpy(dtype=bool)
    else:
        usable = np.ones(len(tollgates), dtype=bool)
    if not usable.any():                 # 전부 미공개면 가를 것이 없다
        usable = np.ones(len(tollgates), dtype=bool)
    usable_idx = np.flatnonzero(usable)
    frames = []

    for start in range(0, len(trades), chunk_size):
        block = trades.iloc[start:start + chunk_size]
        dist = haversine_matrix(
            block["lat"].to_numpy(), block["lon"].to_numpy(),
            tollgates["lat"].to_numpy(), tollgates["lon"].to_numpy(),
        )
        rows, cols = np.where(dist <= max_km)
        if len(rows) == 0:
            continue
        # argmin 을 후보 열에서만 구한 뒤 원래 열 번호로 되돌린다.
        nearest_col = usable_idx[dist[:, usable_idx].argmin(axis=1)]
        frames.append(pd.DataFrame({
            "trade_id": block["trade_id"].to_numpy()[rows],
            "tollgate_id": tg_ids[cols],
            "distance_km": dist[rows, cols],
            "is_nearest": nearest_col[rows] == cols,
        }))

    if not frames:
        return pd.DataFrame(
            columns=["trade_id", "tollgate_id", "distance_km", "band", "is_nearest"]
        )

    linked = pd.concat(frames, ignore_index=True)
    linked["band"] = linked["distance_km"].map(band_label)
    return linked.dropna(subset=["band"])


# 법정동 중심점은 ±1~2km 오차가 있습니다. 반경 경계에 걸친 법정동을
# 자르면, 실제로는 안에 있는 거래를 통째로 버리게 됩니다. 넉넉히 둡니다 —
# 지번 호출 몇 번 더 쓰는 값보다 표본을 잃는 값이 큽니다.
UMD_CENTER_SLACK_KM = 3.0


def umd_near_tollgates(umd_points: "pd.DataFrame", tollgates: "pd.DataFrame",
                       max_km: float,
                       slack_km: float = UMD_CENTER_SLACK_KM) -> "pd.DataFrame":
    """영업소 반경 안에 드는 법정동만 골라낸다.

    지번 단위 좌표는 비쌉니다(하루 4,000건). 전국에 다 붙일 필요가 없고,
    **거리 밴드에 들어갈 수 있는 것에만** 쓰면 됩니다. 법정동 중심점으로
    먼저 걸러 대상을 줄입니다.

    umd_points: sigungu · umd · lat · lon
    tollgates:  lat · lon
    """
    import pandas as pd

    if umd_points.empty or tollgates.empty:
        return umd_points.iloc[0:0].assign(km_nearest=[])

    reach = float(max_km) + float(slack_km)
    dist = haversine_matrix(
        umd_points["lat"].to_numpy(), umd_points["lon"].to_numpy(),
        tollgates["lat"].to_numpy(), tollgates["lon"].to_numpy())
    nearest = dist.min(axis=1)
    out = umd_points.copy()
    out["km_nearest"] = nearest
    kept = out[out["km_nearest"] <= reach].copy()
    print(f"  법정동 {len(out):,}개 중 영업소 {reach:.0f}km 안 {len(kept):,}개 "
          f"({len(kept) / max(len(out), 1):.1%}) — 나머지는 지번 좌표가 "
          f"있어도 어느 밴드에도 못 들어갑니다")
    return kept.sort_values("km_nearest")
