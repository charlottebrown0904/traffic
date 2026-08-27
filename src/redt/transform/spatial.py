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
    """max_link_km 이내 모든 (거래, 영업소) 쌍을 만든다."""
    max_km = float(settings()["spatial"]["max_link_km"])
    trades = trades.dropna(subset=["lat", "lon"])
    tollgates = tollgates.dropna(subset=["lat", "lon"])
    if trades.empty or tollgates.empty:
        return pd.DataFrame(
            columns=["trade_id", "tollgate_id", "distance_km", "band", "is_nearest"]
        )

    tg_ids = tollgates["tollgate_id"].to_numpy()
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
        nearest_col = dist.argmin(axis=1)
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
