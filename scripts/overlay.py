"""Information panels drawn on top of the static map render.

The PNG is the project's shareable artifact (it is what the README shows), so
it carries the same information as the web dashboard: title, headline numbers,
a complete legend and the top emitters.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import geopandas as gpd
import matplotlib.image as mpimg
import pandas as pd
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from scripts.points import build_icon_resolver

# Reference layers drawn by render.py, in draw order. Each entry maps a config
# style prefix to the label shown in the legend.
REFERENCE_LAYERS = [
    ("boundary", "State boundary", "boundary_edgecolor"),
    ("pipelines", "Natural gas pipelines", "pipelines_color"),
    ("primary_roads", "Primary roads", "primary_roads_color"),
    ("railroads", "Railroads", "railroads_color"),
    ("incorporated_places", "Incorporated places", "incorporated_places_color"),
    ("principal_ports", "Principal ports", "principal_ports_color"),
]

SOURCES = (
    "Sources: EPA GHGRP FLIGHT (2023 reported emissions) · US Census TIGER boundaries "
    "· AWS Terrarium elevation tiles"
)


def _style(cfg: dict[str, Any], key: str, default: str) -> str:
    return str(cfg.get("style", {}).get(key, default))


def _facility_totals(points: gpd.GeoDataFrame, emissions_col: str) -> pd.Series:
    if emissions_col not in points.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(points[emissions_col], errors="coerce").fillna(0.0)


def _icon_groups(cfg: dict[str, Any], points: gpd.GeoDataFrame, emissions_col: str):
    """Group facilities by icon so the legend lists exactly what is on the map."""
    resolve = build_icon_resolver(cfg)
    labels = cfg.get("icons", {}).get("labels", {}) or {}
    totals = _facility_totals(points, emissions_col)

    counts: Counter[str] = Counter()
    tons: dict[str, float] = {}
    paths: dict[str, Any] = {}

    subparts = points["subparts"] if "subparts" in points.columns else pd.Series([""] * len(points))
    for position, value in enumerate(subparts):
        icon_name, icon_path = resolve(value)
        counts[icon_name] += 1
        tons[icon_name] = tons.get(icon_name, 0.0) + (
            float(totals.iloc[position]) if len(totals) > position else 0.0
        )
        paths.setdefault(icon_name, icon_path)

    groups = [
        {
            "icon": name,
            "label": labels.get(name, "Other reporting facility"),
            "count": count,
            "tons": tons.get(name, 0.0),
            "path": paths.get(name),
        }
        for name, count in counts.items()
    ]
    groups.sort(key=lambda item: item["tons"], reverse=True)
    return groups


def _panel_text(fig, x, y, text, *, size, color, weight="normal", ha="left", va="baseline", **kwargs):
    return fig.text(x, y, text, fontsize=size, color=color, fontweight=weight, ha=ha, va=va, **kwargs)


def _draw_title_block(fig, cfg, points, emissions_col, top) -> float:
    text_color = _style(cfg, "overlay_text_color", "#e8f0fa")
    muted = _style(cfg, "overlay_muted_color", "#8ba0b8")
    accent = _style(cfg, "overlay_accent_color", "#4dd0e1")

    left = 0.022
    _panel_text(fig, left, top, "VIRGINIA", size=40, color=text_color, weight="bold")
    _panel_text(fig, left, top - 0.036, "INDUSTRIAL GHG EMITTERS", size=19, color=accent,
                weight="bold")
    _panel_text(fig, left, top - 0.063, "EPA Greenhouse Gas Reporting Program · 2023",
                size=11.5, color=muted)

    totals = _facility_totals(points, emissions_col)
    stats = [
        (f"{len(points)}", "FACILITIES"),
        (f"{totals.sum() / 1e6:.1f}", "Mt CO2e"),
        (f"{len(_icon_groups(cfg, points, emissions_col))}", "SECTORS"),
    ]

    stat_y = top - 0.125
    for index, (value, label) in enumerate(stats):
        x = left + index * 0.072
        _panel_text(fig, x, stat_y, value, size=24, color=text_color, weight="bold")
        _panel_text(fig, x, stat_y - 0.026, label, size=9, color=muted)

    return stat_y - 0.06


def _draw_legend(fig, cfg, groups, start_y: float) -> None:
    text_color = _style(cfg, "overlay_text_color", "#e8f0fa")
    muted = _style(cfg, "overlay_muted_color", "#8ba0b8")
    left = 0.022

    _panel_text(fig, left, start_y, "FACILITY TYPE", size=10.5, color=muted, weight="bold")
    row_height = 0.0292
    icon_cache: dict[str, Any] = {}

    y = start_y - 0.032
    for group in groups:
        icon_path = group["path"]
        if icon_path is not None:
            key = str(icon_path)
            if key not in icon_cache:
                icon_cache[key] = mpimg.imread(icon_path)
            image = OffsetImage(icon_cache[key], zoom=0.30)
            fig.add_artist(
                AnnotationBbox(
                    image,
                    (left + 0.007, y + 0.004),
                    xycoords="figure fraction",
                    frameon=False,
                    box_alignment=(0.5, 0.5),
                    annotation_clip=False,
                )
            )
        _panel_text(fig, left + 0.020, y, group["label"], size=11, color=text_color)
        _panel_text(fig, left + 0.196, y, str(group["count"]), size=10, color=muted, ha="right")
        y -= row_height

    y -= 0.012
    _panel_text(fig, left, y, "REFERENCE LAYERS", size=10.5, color=muted, weight="bold")
    y -= 0.029

    for prefix, label, color_key in REFERENCE_LAYERS:
        color = _style(cfg, color_key, "#8fa6bd")
        if prefix == "principal_ports":
            fig.add_artist(_circle_patch(fig, left + 0.0065, y + 0.004, color))
        else:
            fig.add_artist(_line_patch(fig, left + 0.001, left + 0.013, y + 0.004, color, prefix))
        _panel_text(fig, left + 0.020, y, label, size=11, color=text_color)
        y -= 0.0272


def _line_patch(fig, x0, x1, y, color, prefix):
    from matplotlib.lines import Line2D

    width = 3.4 if prefix == "pipelines" else 2.0
    return Line2D(
        [x0, x1], [y, y],
        transform=fig.transFigure,
        color=color,
        linewidth=width,
        solid_capstyle="round",
    )


def _circle_patch(fig, x, y, color):
    from matplotlib.patches import Circle

    return Circle((x, y), radius=0.0035, transform=fig.transFigure, facecolor=color,
                  edgecolor="none")


def _draw_top_emitters(fig, cfg, points, emissions_col, count=5) -> None:
    text_color = _style(cfg, "overlay_text_color", "#e8f0fa")
    muted = _style(cfg, "overlay_muted_color", "#8ba0b8")
    accent = _style(cfg, "overlay_accent_color", "#4dd0e1")

    if emissions_col not in points.columns or points.empty:
        return

    frame = points.copy()
    frame[emissions_col] = pd.to_numeric(frame[emissions_col], errors="coerce").fillna(0.0)
    top = frame.nlargest(count, emissions_col)
    if top.empty:
        return

    name_col = "facility_name" if "facility_name" in top.columns else None
    values = (top[emissions_col] / 1000.0).tolist()[::-1]
    names = (
        [str(name).title() for name in top[name_col].tolist()][::-1]
        if name_col
        else [f"Facility {i + 1}" for i in range(len(values))][::-1]
    )

    axes = fig.add_axes([0.655, 0.822, 0.285, 0.118])
    axes.set_facecolor("none")
    bars = axes.barh(range(len(values)), values, color=accent, alpha=0.85, height=0.62)
    axes.set_yticks(range(len(values)))
    axes.set_yticklabels(
        [name if len(name) <= 34 else f"{name[:32]}…" for name in names],
        fontsize=9.5,
        color=text_color,
    )
    axes.tick_params(axis="x", colors=muted, labelsize=9, length=0)
    axes.tick_params(axis="y", length=0)
    for spine in axes.spines.values():
        spine.set_visible(False)
    axes.grid(axis="x", color=muted, alpha=0.18, linewidth=0.6)
    axes.set_axisbelow(True)
    axes.set_xlabel("kt CO2e", fontsize=9, color=muted, labelpad=2)

    for bar, value in zip(bars, values):
        axes.text(
            bar.get_width() + max(values) * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{value:,.0f}",
            va="center",
            fontsize=9,
            color=muted,
        )
    axes.set_xlim(0, max(values) * 1.18)

    fig.text(0.578, 0.958, f"TOP {len(values)} EMITTERS", fontsize=10.5, color=muted,
             fontweight="bold")


def draw_overlay(fig, cfg: dict[str, Any], points: gpd.GeoDataFrame) -> None:
    """Draw title, stats, legend, top emitters and sources onto the figure."""
    emissions_col = str(
        cfg.get("style", {}).get("icon_size_emissions_col", "ghg_quantity_metric_tons_co2e")
    )
    muted = _style(cfg, "overlay_muted_color", "#8ba0b8")

    legend_start = _draw_title_block(fig, cfg, points, emissions_col, top=0.945)
    _draw_legend(fig, cfg, _icon_groups(cfg, points, emissions_col), legend_start)
    _draw_top_emitters(fig, cfg, points, emissions_col)

    fig.text(0.30, 0.040, "Icon size scales with reported emissions.", fontsize=9, color=muted)
    fig.text(0.30, 0.022, SOURCES, fontsize=9, color=muted)
    fig.text(0.978, 0.022, "decarb-dashboard.github.io/va", fontsize=9, color=muted, ha="right")
