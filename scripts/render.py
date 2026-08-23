"""Orchestrates the single-map rendering pipeline."""

from __future__ import annotations

import io
import math
import urllib.request
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch
import numpy as np
from PIL import Image
from shapely.geometry import MultiPolygon, Polygon

from scripts.io import (
    emissions_to_gdf,
    ensure_crs,
    load_emissions_csv,
    load_va_boundary,
    load_vector_collection,
)
from scripts.layout import apply_dark_theme, create_canvas
from scripts.map_base import draw_boundary, draw_pipelines, draw_reference_layer, set_extent_to_boundary
from scripts.points import draw_points_with_facility_icons

TARGET_CRS = "EPSG:3857"
_WEB_MERCATOR_ORIGIN = 20037508.342789244


def _prepare_paths(cfg: dict[str, Any]) -> dict[str, Path]:
    render_cfg = cfg["render"]
    output_dir = Path(render_cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "output_dir": output_dir,
        "output_png": output_dir / render_cfg["output_png"],
    }


def _load_boundary_3857(cfg: dict[str, Any]):
    boundary = load_va_boundary(cfg["paths"]["va_boundary"])
    return ensure_crs(boundary, TARGET_CRS)


def _load_pipelines_3857(cfg: dict[str, Any]):
    pipelines_path = cfg["paths"].get("pipelines")
    if not pipelines_path:
        return None

    layer = cfg["paths"].get("pipelines_layer")
    pipelines = load_vector_collection(pipelines_path, layer=layer)
    return ensure_crs(pipelines, TARGET_CRS)


def _load_reference_layers_3857(cfg: dict[str, Any]) -> dict[str, Any]:
    path_keys = {
        "railroads": "railroads",
        "primary_roads": "primary_roads",
        "incorporated_places": "incorporated_places",
        "principal_ports": "principal_ports",
    }

    layers: dict[str, Any] = {}
    for layer_name, path_key in path_keys.items():
        source_path = cfg["paths"].get(path_key)
        if not source_path:
            continue
        layer = load_vector_collection(source_path)
        layers[layer_name] = ensure_crs(layer, TARGET_CRS)

    return layers


def _draw_reference_layers(map_ax, boundary, cfg: dict[str, Any], layers: dict[str, Any]) -> None:
    style = cfg.get("style", {})
    for layer_name, layer_gdf in layers.items():
        draw_reference_layer(
            map_ax,
            layer_gdf,
            boundary,
            color=style.get(f"{layer_name}_color", "#546e7a"),
            linewidth=float(style.get(f"{layer_name}_linewidth", 0.35)),
            alpha=float(style.get(f"{layer_name}_alpha", 0.35)),
            zorder=float(style.get(f"{layer_name}_zorder", 1.5)),
            marker_size=float(style.get(f"{layer_name}_marker_size", 6.0)),
        )


def _save_figure(fig, path: Path, dpi: int) -> None:
    fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0)
    plt.close(fig)


def _polygon_to_mpl_path(polygon: Polygon) -> MplPath:
    vertices: list[tuple[float, float]] = []
    codes: list[int] = []

    def add_ring(coords) -> None:
        ring = list(coords)
        if len(ring) < 3:
            return
        for index, (x_coord, y_coord) in enumerate(ring):
            vertices.append((float(x_coord), float(y_coord)))
            if index == 0:
                codes.append(MplPath.MOVETO)
            elif index == len(ring) - 1:
                codes.append(MplPath.CLOSEPOLY)
            else:
                codes.append(MplPath.LINETO)

    add_ring(polygon.exterior.coords)
    for interior in polygon.interiors:
        add_ring(interior.coords)

    if not vertices:
        return MplPath(np.empty((0, 2), dtype=float), np.empty((0,), dtype=np.uint8))
    return MplPath(np.asarray(vertices, dtype=float), np.asarray(codes, dtype=np.uint8))


def _boundary_clip_patch(boundary) -> PathPatch | None:
    geometry = boundary.geometry.union_all()
    polygons: list[Polygon]
    if isinstance(geometry, Polygon):
        polygons = [geometry]
    elif isinstance(geometry, MultiPolygon):
        polygons = list(geometry.geoms)
    else:
        polygons = []

    paths = [_polygon_to_mpl_path(poly) for poly in polygons if not poly.is_empty]
    if not paths:
        return None

    clip_path = paths[0] if len(paths) == 1 else MplPath.make_compound_path(*paths)
    return PathPatch(clip_path, transform=None)


def _lon_lat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """Convert longitude/latitude to slippy-map tile coordinates."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_bounds_3857(tx: int, ty: int, zoom: int) -> tuple[float, float, float, float]:
    """Return (left, bottom, right, top) in EPSG:3857 for a tile."""
    n = 2 ** zoom
    tile_size = 2 * _WEB_MERCATOR_ORIGIN / n
    left = -_WEB_MERCATOR_ORIGIN + tx * tile_size
    top = _WEB_MERCATOR_ORIGIN - ty * tile_size
    return left, top - tile_size, left + tile_size, top


def _fetch_terrarium_elevation(
    minx: float, miny: float, maxx: float, maxy: float, zoom: int,
) -> tuple[np.ndarray, tuple[float, float, float, float]] | None:
    """Download Terrarium-format elevation tiles from AWS and return an elevation
    grid (metres) plus its EPSG:3857 extent.

    Terrarium tiles encode elevation as:
        elevation = (red * 256 + green + blue / 256) - 32768
    They are served in Web Mercator (EPSG:3857), so no reprojection is needed
    for a 3857 display axis.
    """
    def _m_to_lon(mx: float) -> float:
        return mx / _WEB_MERCATOR_ORIGIN * 180.0

    def _m_to_lat(my: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * my / _WEB_MERCATOR_ORIGIN)))

    lon_min, lon_max = _m_to_lon(minx), _m_to_lon(maxx)
    lat_min, lat_max = _m_to_lat(miny), _m_to_lat(maxy)

    x_min, y_nw = _lon_lat_to_tile(lon_min, lat_max, zoom)
    x_max, y_se = _lon_lat_to_tile(lon_max, lat_min, zoom)
    y_min, y_max = min(y_nw, y_se), max(y_nw, y_se)

    grid_w = x_max - x_min + 1
    grid_h = y_max - y_min + 1
    px = 256
    total_w, total_h = grid_w * px, grid_h * px
    elevation = np.full((total_h, total_w), np.nan, dtype=np.float32)

    base_url = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium"
    downloaded = 0
    for ty in range(y_min, y_max + 1):
        for tx in range(x_min, x_max + 1):
            url = f"{base_url}/{zoom}/{tx}/{ty}.png"
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = resp.read()
                img = np.array(Image.open(io.BytesIO(data)))
                r = img[:, :, 0].astype(np.float32)
                g = img[:, :, 1].astype(np.float32)
                b = img[:, :, 2].astype(np.float32)
                elev = (r * 256.0 + g + b / 256.0) - 32768.0
                row = (ty - y_min) * px
                col = (tx - x_min) * px
                elevation[row:row + elev.shape[0], col:col + elev.shape[1]] = elev
                downloaded += 1
            except Exception:
                pass

    if downloaded == 0:
        return None

    print(f"[INFO] Terrain: fetched {downloaded}/{grid_w * grid_h} tiles at zoom {zoom}")

    left = _tile_bounds_3857(x_min, y_min, zoom)[0]
    right = _tile_bounds_3857(x_max, y_min, zoom)[2]
    top = _tile_bounds_3857(x_min, y_min, zoom)[3]
    bottom = _tile_bounds_3857(x_min, y_max, zoom)[1]

    return elevation, (left, bottom, right, top)


def _compute_multidirectional_hillshade(
    elevation: np.ndarray,
    cell_size_x: float,
    cell_size_y: float,
    vertical_exag: float = 1.5,
) -> np.ndarray:
    """Compute a multi-directional hillshade (0-1 float) from an elevation grid."""
    altitude = math.radians(45.0)
    azimuths_deg = [315.0, 270.0, 225.0, 360.0]
    weights = [0.40, 0.25, 0.20, 0.15]

    elev = np.where(np.isfinite(elevation), elevation * vertical_exag, 0.0)
    dy, dx = np.gradient(elev, cell_size_y, cell_size_x)
    slope = np.sqrt(dx * dx + dy * dy)
    slope_angle = np.arctan(slope)
    aspect = np.arctan2(-dx, dy)

    combined = np.zeros_like(elev)
    for az_deg, w in zip(azimuths_deg, weights):
        az = math.radians(az_deg)
        shade = (
            np.sin(altitude) * np.cos(slope_angle)
            + np.cos(altitude) * np.sin(slope_angle) * np.cos(az - aspect)
        )
        combined += w * np.clip(shade, 0.0, 1.0)

    return np.clip(combined, 0.0, 1.0)


def _apply_hypsometric_tint(
    elevation: np.ndarray,
    hillshade: np.ndarray,
    background_rgb: tuple[float, float, float],
    tint_strength: float,
) -> np.ndarray:
    """Build an RGBA overlay combining hillshade relief with elevation-dependent colouring."""
    h, w = hillshade.shape
    rgba = np.zeros((h, w, 4), dtype=np.float32)

    valid = np.isfinite(elevation)
    elev_safe = np.where(valid, elevation, 0.0)

    e_min, e_max = 0.0, max(float(np.nanmax(elev_safe[valid])), 1.0) if np.any(valid) else (0.0, 1.0)
    e_norm = np.clip((elev_safe - e_min) / (e_max - e_min), 0.0, 1.0)

    stops = np.array([0.0, 0.15, 0.35, 0.65, 1.0])
    colors = np.array([
        [0.42, 0.52, 0.60],   # coastal:   cool steel-blue
        [0.48, 0.58, 0.58],   # tidewater: blue-green gray
        [0.55, 0.62, 0.50],   # piedmont:  muted sage
        [0.68, 0.58, 0.45],   # foothills: warm brown
        [0.82, 0.74, 0.62],   # peaks:     pale warm tan
    ])

    for ch in range(3):
        rgba[:, :, ch] = np.interp(e_norm, stops, colors[:, ch])

    shade_factor = 0.20 + hillshade * 0.80
    rgba[:, :, :3] *= shade_factor[..., np.newaxis]

    relief = np.clip(e_norm * 1.3, 0.0, 1.0)
    base_alpha = 0.35 + relief * 0.40
    rgba[:, :, 3] = np.where(valid, base_alpha * tint_strength, 0.0)
    rgba[:, :, 3] = np.clip(rgba[:, :, 3], 0.0, 1.0)

    return rgba


def _draw_terrain_overlay(map_ax, boundary, cfg: dict[str, Any]) -> None:
    """Draw terrain from Terrarium DEM tiles, clipped to the boundary."""
    terrain_cfg = cfg.get("terrain", {})
    style = cfg.get("style", {})
    tint_strength = float(terrain_cfg.get("tint_strength", 0.25))
    terrain_zorder = float(style.get("terrain_zorder", 0.5))
    vertical_exag = float(terrain_cfg.get("vertical_exaggeration", 1.5))
    tile_zoom = terrain_cfg.get("tile_zoom", 9)
    if tile_zoom == "auto":
        tile_zoom = 9

    bg_hex = style.get("background", "#0b0f14")
    bg_rgb = tuple(int(bg_hex.lstrip("#")[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    minx, miny, maxx, maxy = boundary.total_bounds
    pad = 0.05
    dx, dy = maxx - minx, maxy - miny
    fetch_bounds = (minx - dx * pad, miny - dy * pad, maxx + dx * pad, maxy + dy * pad)

    result = _fetch_terrarium_elevation(*fetch_bounds, zoom=int(tile_zoom))
    if result is None:
        print("[WARN] Could not fetch terrain elevation tiles.")
        return

    elevation, (left, bottom, right, top) = result
    h, w = elevation.shape

    cell_x = (right - left) / w
    cell_y = (top - bottom) / h

    hillshade = _compute_multidirectional_hillshade(elevation, cell_x, cell_y, vertical_exag)
    rgba = _apply_hypsometric_tint(elevation, hillshade, bg_rgb, tint_strength)

    extent = (left, right, bottom, top)

    image_artist = map_ax.imshow(
        rgba,
        extent=extent,
        origin="upper",
        interpolation="bilinear",
        zorder=terrain_zorder,
    )

    clip_patch = _boundary_clip_patch(boundary)
    if clip_patch is not None:
        clip_patch.set_transform(map_ax.transData)
        image_artist.set_clip_path(clip_patch)


def render_map(cfg: dict[str, Any]) -> Path:
    """Render the full VA GHG map with boundary, layers, terrain, and facility icons."""
    emissions_csv = cfg["paths"].get("emissions_csv")
    if not emissions_csv:
        raise ValueError("paths.emissions_csv is not set; cannot render map.")

    paths = _prepare_paths(cfg)
    boundary = _load_boundary_3857(cfg)
    pipelines = _load_pipelines_3857(cfg)
    reference_layers = _load_reference_layers_3857(cfg)

    points_df = load_emissions_csv(emissions_csv)
    if "reporting_year" in points_df.columns:
        points_df = points_df[points_df["reporting_year"] == 2023]
    lat_col = cfg["paths"].get("emissions_lat_col", "latitude")
    lon_col = cfg["paths"].get("emissions_lon_col", "longitude")
    points = emissions_to_gdf(points_df, lat_col=lat_col, lon_col=lon_col)
    points = ensure_crs(points, TARGET_CRS)

    fig, map_ax, panel_ax = create_canvas(cfg)
    apply_dark_theme(fig, map_ax, panel_ax, cfg)
    _draw_terrain_overlay(map_ax, boundary, cfg)
    draw_boundary(map_ax, boundary, cfg)
    if pipelines is not None:
        draw_pipelines(map_ax, pipelines, boundary, cfg)
    _draw_reference_layers(map_ax, boundary, cfg, reference_layers)
    draw_points_with_facility_icons(map_ax, points, cfg)
    set_extent_to_boundary(map_ax, boundary, padding_pct=float(cfg["style"].get("padding_pct", 0.02)))

    output_path = paths["output_png"]
    _save_figure(fig, output_path, int(cfg["render"]["dpi"]))
    return output_path
