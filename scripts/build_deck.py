"""Prepare deck.gl-ready assets for the VA GHG dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from scripts.io import emissions_to_gdf, load_emissions_csv, load_va_boundary, load_vector_collection

EPSG_4326 = "EPSG:4326"


def _to_feature_collection(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    if gdf.crs is not None and str(gdf.crs) != EPSG_4326:
        gdf = gdf.to_crs(EPSG_4326)
    return json.loads(gdf.to_json(drop_id=True))


def _write_geojson(path: Path, gdf: gpd.GeoDataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_to_feature_collection(gdf), separators=(",", ":")))


def _clip_to_boundary(layer: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Clip any layer to Virginia to avoid shipping continental-scale geometry."""
    if layer.crs is None:
        raise ValueError("Layer has no CRS; cannot clip to boundary.")

    if boundary.crs is None:
        raise ValueError("Boundary has no CRS; cannot clip layers.")

    boundary_local = boundary.to_crs(layer.crs) if layer.crs != boundary.crs else boundary
    boundary_union = boundary_local.geometry.union_all()

    clipped = layer.copy()
    clipped["geometry"] = clipped.geometry.intersection(boundary_union)
    valid_geometry = (~clipped.geometry.is_empty) & (~clipped.geometry.isna())
    clipped = clipped[valid_geometry].copy()
    return clipped


def _ghg_points(cfg: dict[str, Any], boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    paths = cfg["paths"]
    emissions_df = load_emissions_csv(paths["emissions_csv"])
    emissions_df = emissions_df.loc[emissions_df["reporting_year"] == 2023].copy()
    gdf = emissions_to_gdf(
        emissions_df,
        lat_col=paths.get("emissions_lat_col", "latitude"),
        lon_col=paths.get("emissions_lon_col", "longitude"),
        crs=EPSG_4326,
    )
    gdf = _clip_to_boundary(gdf, boundary)
    gdf["ghg_quantity_metric_tons_co2e"] = pd.to_numeric(
        gdf.get("ghg_quantity_metric_tons_co2e"), errors="coerce"
    ).fillna(0)
    # Icon/marker size scales with the square root of emissions so area, not
    # radius, tracks the reported quantity.
    tons = gdf["ghg_quantity_metric_tons_co2e"].clip(lower=0)
    gdf["radius_m"] = (tons.pow(0.5) * 3.0).clip(lower=400, upper=6000)
    keep_cols = [
        "facility_name",
        "subparts",
        "ghg_quantity_metric_tons_co2e",
        "radius_m",
        "reporting_year",
        "geometry",
    ]
    return gdf[keep_cols]


def _icon_manifest(cfg: dict[str, Any]) -> dict[str, Any]:
    icons_cfg = cfg.get("icons", {})
    paths_cfg = cfg.get("paths", {})
    icons_dir = Path(str(paths_cfg.get("icons_dir", "geo-icons")))

    by_subparts = icons_cfg.get("by_subparts", {}) or {}
    for subparts, icon_name in sorted(by_subparts.items()):
        if _resolve_icon_file(icons_dir, str(icon_name)) is None:
            print(f"[WARN] Icon for subparts '{subparts}' not found in {icons_dir}: {icon_name}")

    return {
        "base_dir": str(icons_dir),
        "default": str(icons_cfg.get("default", "icon_v2_C")),
        "by_subparts": by_subparts,
        "labels": icons_cfg.get("labels", {}) or {},
    }


def _resolve_icon_file(icons_dir: Path, icon_name: str) -> str | None:
    """Return the on-disk filename for an icon name, or None when it is missing."""
    if "." in icon_name:
        return icon_name if (icons_dir / icon_name).exists() else None
    for suffix in (".png", ".jpg", ".jpeg"):
        if (icons_dir / f"{icon_name}{suffix}").exists():
            return f"{icon_name}{suffix}"
    return None


def _style_manifest(cfg: dict[str, Any]) -> dict[str, Any]:
    """Colours the web map shares with the static render."""
    style = cfg.get("style", {})
    keys = (
        "background",
        "boundary_edgecolor",
        "pipelines_color",
        "pipelines_glow_color",
        "railroads_color",
        "primary_roads_color",
        "incorporated_places_color",
        "principal_ports_color",
    )
    return {key: style[key] for key in keys if key in style}


def build_deck_assets(cfg: dict[str, Any]) -> Path:
    output_dir = Path(cfg["render"]["output_dir"]) / "deck-data"
    output_dir.mkdir(parents=True, exist_ok=True)

    boundary = load_va_boundary(cfg["paths"]["va_boundary"])
    _write_geojson(output_dir / "boundary.geojson", boundary)

    pipelines = load_vector_collection(
        cfg["paths"]["pipelines"], layer=cfg["paths"].get("pipelines_layer")
    )
    _write_geojson(output_dir / "pipelines.geojson", _clip_to_boundary(pipelines, boundary))

    for layer_name in ["railroads", "primary_roads", "incorporated_places", "principal_ports"]:
        layer = load_vector_collection(cfg["paths"][layer_name])
        _write_geojson(output_dir / f"{layer_name}.geojson", _clip_to_boundary(layer, boundary))

    ghg = _ghg_points(cfg, boundary)
    _write_geojson(output_dir / "ghg_2023.geojson", ghg)

    bounds = boundary.to_crs(EPSG_4326).total_bounds
    minx, miny, maxx, maxy = [float(v) for v in bounds]
    manifest = {
        "center": [(minx + maxx) / 2.0, (miny + maxy) / 2.0],
        "bounds": [minx, miny, maxx, maxy],
        "terrain_exaggeration": float(cfg.get("terrain", {}).get("vertical_exaggeration", 1.8)),
        "files": {
            "boundary": "output/deck-data/boundary.geojson",
            "pipelines": "output/deck-data/pipelines.geojson",
            "railroads": "output/deck-data/railroads.geojson",
            "primary_roads": "output/deck-data/primary_roads.geojson",
            "incorporated_places": "output/deck-data/incorporated_places.geojson",
            "principal_ports": "output/deck-data/principal_ports.geojson",
            "ghg": "output/deck-data/ghg_2023.geojson",
        },
        "icons": _icon_manifest(cfg),
        "style": _style_manifest(cfg),
        "web": cfg.get("web", {}),
        "emissions_range": [
            float(ghg["ghg_quantity_metric_tons_co2e"].min()),
            float(ghg["ghg_quantity_metric_tons_co2e"].max()),
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return output_dir
