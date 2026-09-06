"""Prepare deck.gl-ready assets for the VA GHG dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.errors import GEOSException
from shapely.geometry.base import BaseGeometry

from scripts.io import (
    collapse_to_dimension,
    describe_geometry,
    emissions_to_gdf,
    expected_reprojected_bounds,
    geometry_report,
    has_finite_bounds,
    load_emissions_csv,
    load_va_boundary,
    load_vector_collection,
    reproject_polygonal,
    sanitize_geometries,
)

EPSG_4326 = "EPSG:4326"

# Repaired boundary masks, keyed by the CRS they were built for.
_BOUNDARY_MASKS: dict[str, BaseGeometry] = {}


def _to_feature_collection(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    if gdf.crs is not None and str(gdf.crs) != EPSG_4326:
        gdf = gdf.to_crs(EPSG_4326)
    return json.loads(gdf.to_json(drop_id=True))


def _write_geojson(path: Path, gdf: gpd.GeoDataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_to_feature_collection(gdf), separators=(",", ":")))


def _boundary_mask(boundary: gpd.GeoDataFrame, target_crs) -> BaseGeometry:
    """Return the Virginia outline as a single polygon in `target_crs`.

    The state outline is polygonal by definition, so it takes a polygon-only
    path: no generic mixed-dimension cleanup, and a valid Polygon/MultiPolygon
    goes to the union untouched. Every stage is recorded so a failure names the
    step that broke rather than only its symptom.
    """
    if boundary.crs is None:
        raise ValueError("Boundary has no CRS; cannot clip layers.")

    key = str(target_crs)
    cached = _BOUNDARY_MASKS.get(key)
    if cached is not None:
        return cached

    trace = [describe_geometry(boundary, "boundary as loaded")]

    usable = boundary[boundary.geometry.notna() & ~boundary.geometry.is_empty]
    if len(usable) != len(boundary):
        trace.append(describe_geometry(usable, "after dropping null/empty"))
    if usable.empty:
        raise ValueError(_boundary_failure("boundary has no non-empty geometry", trace))

    unexpected = set(usable.geometry.geom_type) - {"Polygon", "MultiPolygon"}
    if unexpected:
        raise ValueError(
            _boundary_failure(f"boundary is not polygonal: found {sorted(unexpected)}", trace)
        )

    invalid = ~usable.geometry.is_valid
    if invalid.any():
        repaired = usable.geometry[invalid].apply(shapely.make_valid).apply(
            lambda geometry: collapse_to_dimension(geometry, 2)
        )
        usable = usable.copy()
        usable.loc[invalid, usable.geometry.name] = repaired
        usable = usable[usable.geometry.notna() & ~usable.geometry.is_empty]
        trace.append(describe_geometry(usable, f"after make_valid on {int(invalid.sum())} feature(s)"))
        if usable.empty:
            raise ValueError(_boundary_failure("boundary geometry did not survive repair", trace))

    if str(usable.crs) != key:
        # Not GeoDataFrame.to_crs(): its set_coordinates() path fails on this
        # outline on some shapely/GEOS builds. See io.reproject_polygonal.
        expected_bounds = expected_reprojected_bounds(usable, target_crs)
        usable = reproject_polygonal(usable, target_crs)
        trace.append(describe_geometry(usable, f"after reproject_polygonal({key})"))
        _validate_boundary(usable, expected_bounds, key, trace)

    mask = usable.geometry.union_all()
    trace.append(
        f"after union_all: {None if mask is None else mask.geom_type}"
        f" empty={None if mask is None else mask.is_empty}"
        f" valid={None if mask is None else mask.is_valid}"
        f" bounds={None if mask is None else tuple(round(v, 6) for v in mask.bounds)}"
    )

    if mask is None or mask.is_empty:
        raise ValueError(
            _boundary_failure(
                "union of the boundary produced no geometry (GEOS returned nothing)", trace
            )
        )
    if not mask.is_valid:
        raise ValueError(_boundary_failure("union of the boundary is invalid", trace))

    if os.environ.get("VA_GEO_DEBUG"):
        print("[DEBUG] boundary trace:\n  " + "\n  ".join(trace))

    _BOUNDARY_MASKS[key] = mask
    return mask


def _validate_boundary(
    boundary: gpd.GeoDataFrame,
    expected_bounds: tuple[float, float, float, float],
    key: str,
    trace: list[str],
) -> None:
    """Check a reprojected boundary before anything downstream depends on it."""
    geometry = boundary.geometry

    def fail(reason: str) -> None:
        raise ValueError(_boundary_failure(reason, trace))

    if boundary.empty or geometry.isna().any():
        fail(f"reprojection to {key} produced null geometry")
    if geometry.is_empty.any():
        fail(f"reprojection to {key} produced empty geometry")

    unexpected = set(geometry.geom_type) - {"Polygon", "MultiPolygon"}
    if unexpected:
        fail(f"reprojection to {key} produced non-polygonal geometry {sorted(unexpected)}")

    finite = has_finite_bounds(boundary)
    if not finite.all():
        fail(
            f"reprojection to {key} produced non-finite coordinates in "
            f"{int((~finite).sum())} of {len(boundary)} feature(s)"
        )
    if not geometry.is_valid.all():
        fail(f"reprojection to {key} produced invalid geometry")

    # The transformed bounding box should land where transforming the source
    # bounding box says it will; anything else means the transform went wrong.
    actual = boundary.total_bounds
    extent = max(expected_bounds[2] - expected_bounds[0], expected_bounds[3] - expected_bounds[1])
    tolerance = max(abs(extent) * 0.01, 1e-6)
    drift = [abs(float(a) - float(b)) for a, b in zip(actual, expected_bounds)]
    if max(drift) > tolerance:
        fail(
            f"reprojection to {key} landed at {np.round(actual, 6).tolist()}, expected about "
            f"{[round(value, 6) for value in expected_bounds]} (drift {max(drift):.6g} "
            f"> tolerance {tolerance:.6g})"
        )
    trace.append(
        f"bounds check: {np.round(actual, 6).tolist()} within {tolerance:.6g} of expected"
    )


def _boundary_failure(reason: str, trace: list[str]) -> str:
    """Fail with the whole boundary trace so the breaking step is visible."""
    steps = "\n  ".join(trace)
    return f"Virginia boundary: {reason}.\nBoundary trace:\n  {steps}"


def _intersect_feature_by_feature(
    geometries: gpd.GeoSeries, mask: BaseGeometry, label: str
) -> tuple[gpd.GeoSeries, int]:
    """Intersect one feature at a time so a single bad feature cannot stop the build."""
    results: list[BaseGeometry | None] = []
    failures = 0
    for geometry in geometries:
        try:
            results.append(geometry.intersection(mask))
        except (GEOSException, ValueError) as exc:
            failures += 1
            print(f"[WARN] {label}: dropped one feature GEOS could not clip: {exc}")
            results.append(None)
    return gpd.GeoSeries(results, index=geometries.index, crs=geometries.crs), failures


def _clip_to_boundary(
    layer: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, label: str = "layer"
) -> gpd.GeoDataFrame:
    """Clip any layer to Virginia to avoid shipping continental-scale geometry."""
    if layer.crs is None:
        raise ValueError(f"Layer '{label}' has no CRS; cannot clip to boundary.")

    print(f"[INFO] {geometry_report(layer, label).describe()}")
    cleaned, stats = sanitize_geometries(layer, label=label)
    if stats.repaired or stats.dropped:
        print(f"[INFO] {stats.format()}")
    if cleaned.empty:
        print(f"[WARN] {label}: no usable geometry after repair; nothing to clip.")
        return cleaned

    mask = _boundary_mask(boundary, cleaned.crs)

    # Only features whose bounding box meets Virginia can survive the clip, and
    # skipping the rest keeps continental-scale layers off the overlay engine.
    candidate_positions = cleaned.sindex.query(mask)
    candidates = cleaned.iloc[sorted(candidate_positions)].copy()
    if candidates.empty:
        print(f"[INFO] {label}: no features overlap Virginia.")
        return candidates

    dimensions = shapely.get_dimensions(candidates.geometry.values)
    try:
        clipped_geometry = candidates.geometry.intersection(mask)
        failures = 0
    except (GEOSException, ValueError) as exc:
        print(f"[WARN] {label}: vectorised clip failed ({exc}); isolating features.")
        clipped_geometry, failures = _intersect_feature_by_feature(candidates.geometry, mask, label)

    # Overlay output can mix dimensions (a polygon clip touching an edge yields
    # lines); keep only the dimension the source feature had.
    kept: list[BaseGeometry | None] = []
    for geometry, dimension in zip(clipped_geometry, dimensions):
        if geometry is None or geometry.is_empty:
            kept.append(None)
        elif geometry.geom_type == "GeometryCollection":
            kept.append(collapse_to_dimension(geometry, int(dimension)))
        else:
            kept.append(geometry)

    candidates["geometry"] = gpd.GeoSeries(kept, index=candidates.index, crs=candidates.crs)
    clipped = candidates[candidates.geometry.notna() & ~candidates.geometry.is_empty].copy()

    print(
        f"[INFO] {label}: clipped to Virginia -> {len(clipped)} features"
        f" (from {len(candidates)} candidates of {len(cleaned)};"
        f" {failures} unclippable feature(s))"
    )
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
    gdf = _clip_to_boundary(gdf, boundary, label="ghg facilities")
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

    # Reproject the outline once here, with the transformer path, so nothing
    # downstream (GeoJSON writing, the clip mask, the manifest bounds) has to
    # send it through GeoDataFrame.to_crs().
    boundary = reproject_polygonal(load_va_boundary(cfg["paths"]["va_boundary"]), EPSG_4326)
    _write_geojson(output_dir / "boundary.geojson", boundary)

    pipelines = load_vector_collection(
        cfg["paths"]["pipelines"], layer=cfg["paths"].get("pipelines_layer")
    )
    _write_geojson(
        output_dir / "pipelines.geojson", _clip_to_boundary(pipelines, boundary, label="pipelines")
    )

    for layer_name in ["railroads", "primary_roads", "incorporated_places", "principal_ports"]:
        layer = load_vector_collection(cfg["paths"][layer_name])
        _write_geojson(
            output_dir / f"{layer_name}.geojson",
            _clip_to_boundary(layer, boundary, label=layer_name),
        )

    ghg = _ghg_points(cfg, boundary)
    _write_geojson(output_dir / "ghg_2023.geojson", ghg)

    bounds = boundary.total_bounds
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
