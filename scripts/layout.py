"""Figure and panel layout helpers."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt


def create_canvas(cfg: dict[str, Any]):
    """Create a 16:9 canvas with map and right-side panel axes."""
    render_cfg = cfg["render"]
    width_px = int(render_cfg["width_px"])
    height_px = int(render_cfg["height_px"])
    dpi = int(render_cfg["dpi"])

    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    map_ax = fig.add_axes([0.00, 0.00, 0.66, 1.00])
    panel_ax = fig.add_axes([0.66, 0.00, 0.34, 1.00])
    return fig, map_ax, panel_ax


def apply_dark_theme(fig, map_ax, panel_ax, cfg: dict[str, Any]) -> None:
    """Apply dark theme styles and hide panel axis ticks/spines."""
    background = cfg["style"]["background"]
    fig.patch.set_facecolor(background)
    map_ax.set_facecolor(background)
    panel_ax.set_facecolor(background)
    panel_ax.set_axis_off()
