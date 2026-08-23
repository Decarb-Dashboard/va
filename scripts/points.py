"""Point rendering utilities."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.image as mpimg
import pandas as pd
from matplotlib.offsetbox import AnnotationBbox, OffsetImage


_DEFAULT_ICON_BY_SUBPARTS = {
    "C": "icon_v2_C",
    "C,HH": "icon_v2_C_HH",
    "C,Q": "icon_v2_C_Q",
    "C,W": "icon_v2_C_W",
    "C,S": "icon_v2_C_S",
    "C,I": "icon_v2_C_I",
    "C,II": "icon_v2_C_II",
    "AA,C": "icon_v2_AA_C",
    "DD": "icon_v2_DD",
    "C,N": "icon_v2_C_N",
    "TT": "icon_v2_TT",
    "FF": "coal.jpg",
    "D": "power.jpg",
    "C,D": "power.jpg",
    "C,G,PP": "chemical.jpg",
    "C,H": "cement.jpg",
    "C,TT": "icon_v2_TT",
    "AA,C,TT": "icon_v2_AA_C",
}


def _normalize_subparts(subparts: str) -> str:
    codes = sorted({part.strip().upper() for part in str(subparts or "").split(",") if part.strip()})
    return ",".join(codes)


def _load_icon_mappings(cfg: dict[str, Any]) -> tuple[str, dict[str, str]]:
    icon_cfg = cfg.get("geo-icons", {})
    default_icon = str(icon_cfg.get("default", "manufacturing.jpg"))

    raw_mapping = icon_cfg.get("by_subparts", _DEFAULT_ICON_BY_SUBPARTS)
    mapping: dict[str, str] = {}
    if isinstance(raw_mapping, dict):
        for subparts, icon_name in raw_mapping.items():
            mapping[_normalize_subparts(str(subparts))] = str(icon_name)

    if not mapping:
        mapping = {key: value for key, value in _DEFAULT_ICON_BY_SUBPARTS.items()}

    return default_icon, mapping


def _load_icon(path: Path):
    return mpimg.imread(path)


def _resolve_icon_path(icon_dir: Path, icon_name: str) -> Path | None:
    raw_path = icon_dir / icon_name
    if raw_path.exists():
        return raw_path

    if raw_path.suffix:
        return None

    for suffix in (".png", ".jpg", ".jpeg"):
        candidate = icon_dir / f"{icon_name}{suffix}"
        if candidate.exists():
            return candidate

    return None


def draw_points_with_facility_icons(
    map_ax,
    points_gdf: gpd.GeoDataFrame,
    cfg: dict[str, Any],
) -> None:
    """Draw facilities with icons by subpart mapping.

    Icon size scales with each facility's GHG emissions quantity.
    """
    style = cfg["style"]
    if points_gdf.empty:
        return

    icon_dir = Path(cfg.get("paths", {}).get("icons_dir", "geo-icons"))
    default_icon, icon_by_subparts = _load_icon_mappings(cfg)
    base_icon_zoom = float(style.get("icon_zoom", 0.085))
    min_zoom_scale = float(style.get("icon_zoom_scale_min", 0.75))
    max_zoom_scale = float(style.get("icon_zoom_scale_max", 1.35))
    emissions_col = str(style.get("icon_size_emissions_col", "ghg_quantity_metric_tons_co2e"))

    points = points_gdf.copy()
    if "subparts" not in points.columns:
        points["subparts"] = ""

    emissions_values = None
    if emissions_col in points.columns:
        emissions_values = points[emissions_col]

    if emissions_values is not None:
        emissions_values = pd.to_numeric(emissions_values, errors="coerce").clip(lower=0)
        emission_min = float(emissions_values.min(skipna=True))
        emission_max = float(emissions_values.max(skipna=True))
    else:
        emission_min = 0.0
        emission_max = 0.0

    emission_span = emission_max - emission_min

    icon_cache: dict[str, Any] = {}
    for _, row in points.iterrows():
        subparts = row["subparts"]
        normalized_subparts = _normalize_subparts(subparts)
        icon_name = icon_by_subparts.get(normalized_subparts, default_icon)
        icon_path = _resolve_icon_path(icon_dir, icon_name)
        if icon_path is None:
            continue

        if icon_name not in icon_cache:
            icon_cache[icon_name] = _load_icon(icon_path)

        row_emissions = row.get(emissions_col)
        zoom_scale = 1.0
        if emission_span > 0 and row_emissions is not None:
            try:
                numeric_emissions = float(row_emissions)
            except (TypeError, ValueError):
                numeric_emissions = math.nan

            if not math.isnan(numeric_emissions):
                normalized = (max(numeric_emissions, 0.0) - emission_min) / emission_span
                zoom_scale = min_zoom_scale + normalized * (max_zoom_scale - min_zoom_scale)

        image = OffsetImage(icon_cache[icon_name], zoom=base_icon_zoom * zoom_scale)
        marker = AnnotationBbox(
            image,
            (row.geometry.x, row.geometry.y),
            frameon=False,
            box_alignment=(0.5, 0.5),
            zorder=6,
        )
        map_ax.add_artist(marker)
