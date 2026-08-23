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
    gdf["radius_m"] = (
        gdf["ghg_quantity_metric_tons_co2e"].clip(lower=0).pow(0.35).clip(lower=300, upper=3000)
    )
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
    return {
        "base_dir": str(paths_cfg.get("icons_dir", "geo-icons")),
        "default": str(icons_cfg.get("default", "manufacturing")),
        "by_subparts": icons_cfg.get("by_subparts", {}),
    }


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
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return output_dir
