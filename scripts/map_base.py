"""Base-map rendering helpers."""

from __future__ import annotations

from typing import Any

import geopandas as gpd


def draw_boundary(map_ax, boundary_gdf: gpd.GeoDataFrame, cfg: dict[str, Any]) -> None:
    """Draw boundary outline and optional fill on the map axis."""
    style = cfg["style"]
    fill_color = style.get("boundary_fill")

    boundary_gdf.plot(
        ax=map_ax,
        facecolor=fill_color if fill_color else "none",
        edgecolor=style.get("boundary_edgecolor", "#9fb3c8"),
        linewidth=float(style["boundary_linewidth"]),
        alpha=float(style["boundary_alpha"]),
    )


def draw_pipelines(
    map_ax,
    pipelines_gdf: gpd.GeoDataFrame,
    boundary_gdf: gpd.GeoDataFrame,
    cfg: dict[str, Any],
) -> None:
    """Draw natural gas pipelines clipped to the boundary extent."""
    style = cfg["style"]
    clipped = gpd.clip(pipelines_gdf, boundary_gdf)
    if clipped.empty:
        return

    zorder = float(style.get("pipelines_zorder", 2))

    # Soft halo underneath so the pipeline network reads first on a dark map.
    glow_width = float(style.get("pipelines_glow_linewidth", 0.0))
    if glow_width > 0:
        clipped.plot(
            ax=map_ax,
            color=style.get("pipelines_glow_color", style.get("pipelines_color", "#9D00FF")),
            linewidth=glow_width,
            alpha=float(style.get("pipelines_glow_alpha", 0.2)),
            zorder=zorder - 0.05,
        )

    clipped.plot(
        ax=map_ax,
        color=style.get("pipelines_color", "#4ba3c7"),
        linewidth=float(style.get("pipelines_linewidth", 0.4)),
        alpha=float(style.get("pipelines_alpha", 0.5)),
        zorder=zorder,
    )


def draw_reference_layer(
    map_ax,
    layer_gdf: gpd.GeoDataFrame,
    boundary_gdf: gpd.GeoDataFrame,
    *,
    color: str,
    linewidth: float,
    alpha: float,
    zorder: float,
    marker_size: float = 6.0,
) -> None:
    """Draw a reference vector layer clipped to the boundary extent."""
    clipped = gpd.clip(layer_gdf, boundary_gdf)
    if clipped.empty:
        return

    geom_types = {str(geom_type) for geom_type in clipped.geometry.geom_type.unique()}
    if geom_types <= {"Point", "MultiPoint"}:
        clipped.plot(
            ax=map_ax,
            color=color,
            alpha=alpha,
            zorder=zorder,
            markersize=marker_size,
        )
        return

    clipped.plot(
        ax=map_ax,
        color=color,
        linewidth=linewidth,
        alpha=alpha,
        zorder=zorder,
    )


def set_extent_to_boundary(
    map_ax,
    boundary_gdf: gpd.GeoDataFrame,
    padding_pct: float,
    *,
    figure_aspect: float | None = None,
    reserve_left_frac: float = 0.0,
    reserve_right_frac: float = 0.0,
) -> None:
    """Set the axis extent to the boundary bounds.

    When ``figure_aspect`` is given the extent is widened to exactly match the
    figure so nothing is letterboxed, and ``reserve_left_frac`` /
    ``reserve_right_frac`` keep that share of the frame clear of the state for
    overlay panels.
    """
    minx, miny, maxx, maxy = boundary_gdf.total_bounds
    pad_x = (maxx - minx) * float(padding_pct)
    pad_y = (maxy - miny) * float(padding_pct)
    minx, maxx = minx - pad_x, maxx + pad_x
    miny, maxy = miny - pad_y, maxy + pad_y

    if figure_aspect:
        usable = max(1e-6, 1.0 - reserve_left_frac - reserve_right_frac)
        data_width = (maxx - minx) / usable
        data_height = data_width / figure_aspect

        if data_height < (maxy - miny):
            data_height = maxy - miny
            data_width = data_height * figure_aspect

        left = minx - data_width * reserve_left_frac
        center_y = (miny + maxy) / 2.0
        map_ax.set_xlim(left, left + data_width)
        map_ax.set_ylim(center_y - data_height / 2.0, center_y + data_height / 2.0)
    else:
        map_ax.set_xlim(minx, maxx)
        map_ax.set_ylim(miny, maxy)

    map_ax.set_aspect("equal", adjustable="box")
    map_ax.set_axis_off()
