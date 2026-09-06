"""Figure and panel layout helpers."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt


def create_canvas(cfg: dict[str, Any]):
    """Create the 16:9 canvas.

    ``layout.mode: overlay`` (default) gives the map the whole frame and draws
    the information panels on top of it; ``layout.mode: panel`` keeps the older
    map + right-side panel split.
    """
    render_cfg = cfg["render"]
    width_px = int(render_cfg["width_px"])
    height_px = int(render_cfg["height_px"])
    dpi = int(render_cfg["dpi"])
    layout_cfg = cfg.get("layout", {})
    mode = str(layout_cfg.get("mode", "overlay")).lower()

    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    if mode == "overlay":
        map_ax = fig.add_axes([0.00, 0.00, 1.00, 1.00])
        panel_ax = None
    else:
        map_frac = float(layout_cfg.get("map_frac", 0.66))
        map_ax = fig.add_axes([0.00, 0.00, map_frac, 1.00])
        panel_ax = fig.add_axes([map_frac, 0.00, 1.0 - map_frac, 1.00])
    return fig, map_ax, panel_ax


def apply_dark_theme(fig, map_ax, panel_ax, cfg: dict[str, Any]) -> None:
    """Apply dark theme styles and hide panel axis ticks/spines."""
    background = cfg["style"]["background"]
    fig.patch.set_facecolor(background)
    map_ax.set_facecolor(background)
    if panel_ax is not None:
        panel_ax.set_facecolor(background)
        panel_ax.set_axis_off()
