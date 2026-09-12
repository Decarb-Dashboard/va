"""Trace the Virginia boundary (and every layer) through the clipping pipeline.

Run this in the project environment when a build fails inside a GEOS call:

    python -m scripts.diagnose_geometry

It prints library versions, the boundary state at every stage the build touches
it, and the result of each union baseline, so the step that breaks is visible
without reading a traceback.
"""

from __future__ import annotations

import argparse
import warnings
from typing import Any, Callable

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely
import shapely.ops

from scripts.config import load_yaml_config
from scripts.io import (
    describe_geometry,
    expected_reprojected_bounds,
    geometry_report,
    load_va_boundary,
    load_vector_collection,
    reproject_polygonal,
    sanitize_geometries,
)


def _versions() -> None:
    print("environment")
    print(f"  shapely    {shapely.__version__} (GEOS {shapely.geos_version})")
    print(f"  geopandas  {gpd.__version__}")
    print(f"  pandas     {pd.__version__}")
    print(f"  pyproj     {pyproj.__version__} (PROJ {pyproj.proj_version_str})")
    print(f"  PROJ data  {pyproj.datadir.get_data_dir()}")
    try:
        print(f"  engine     {gpd.options.io_engine or 'auto (pyogrio if installed)'}")
    except AttributeError:
        pass


def _attempt(label: str, call: Callable[[], Any]) -> None:
    """Run one union baseline, reporting warnings as well as the result."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = call()
            if result is None:
                outcome = "None"
            else:
                outcome = f"{result.geom_type} empty={result.is_empty} valid={result.is_valid}"
        except Exception as exc:  # noqa: BLE001 - diagnostics
            outcome = f"{type(exc).__name__}: {exc}"
    messages = [str(warning.message) for warning in caught]
    print(f"  {label:44s} -> {outcome}")
    for message in messages:
        print(f"       warning: {message}")


def diagnose_boundary(cfg: dict[str, Any], target_crs: str) -> None:
    path = cfg["paths"]["va_boundary"]

    print(f"\nboundary: {path}")
    raw = gpd.read_file(path)
    print(f"  {describe_geometry(raw, 'read_file (no repair)')}")
    for index, geometry in zip(raw.index, raw.geometry):
        parts = len(getattr(geometry, "geoms", []) or [])
        print(f"    row {index}: {geometry.geom_type} parts={parts} wkt[:70]={str(geometry)[:70]}")

    loaded = load_va_boundary(path)
    print(f"  {describe_geometry(loaded, 'after load_va_boundary')}")

    cleaned, stats = sanitize_geometries(loaded, label="va boundary")
    print(f"  {describe_geometry(cleaned, 'after sanitize_geometries')}")
    print(f"    stats: {stats.format()}")
    print(f"    untouched (same object): {cleaned is loaded}")

    reprojected = cleaned
    if str(cleaned.crs) != target_crs:
        expected = expected_reprojected_bounds(cleaned, target_crs)
        _attempt(
            "GeoDataFrame.to_crs()  [set_coordinates path]",
            lambda: cleaned.to_crs(target_crs).geometry.iloc[0],
        )
        reprojected = reproject_polygonal(cleaned, target_crs)
        print(f"  {describe_geometry(reprojected, f'after reproject_polygonal({target_crs})')}")
        drift = np.abs(np.asarray(reprojected.total_bounds) - np.asarray(expected))
        print(f"    expected bounds {np.round(expected, 6).tolist()}")
        print(f"    drift from expected: {np.round(drift, 9).tolist()}")

    print("\nunion baselines (all should return a MultiPolygon):")
    geometry = reprojected.geometry
    _attempt("geometry.union_all()", geometry.union_all)
    _attempt("shapely.union_all(geometry.dropna().values)",
             lambda: shapely.union_all(geometry.dropna().values))
    _attempt("shapely.union_all(np.asarray(values))",
             lambda: shapely.union_all(np.asarray(geometry.values)))
    _attempt("shapely.unary_union via ops", lambda: shapely.ops.unary_union(list(geometry)))
    _attempt("dissolve().geometry.iloc[0]",
             lambda: reprojected.dissolve().geometry.iloc[0])


def diagnose_layers(cfg: dict[str, Any]) -> None:
    paths = cfg["paths"]
    layers = {
        "pipelines": (paths.get("pipelines"), paths.get("pipelines_layer")),
        "railroads": (paths.get("railroads"), None),
        "primary_roads": (paths.get("primary_roads"), None),
        "incorporated_places": (paths.get("incorporated_places"), None),
        "principal_ports": (paths.get("principal_ports"), None),
    }

    print("\nreference layers (as read, before repair):")
    for name, (path, layer) in layers.items():
        if not path:
            continue
        try:
            gdf = load_vector_collection(path, layer=layer)
        except Exception as exc:  # noqa: BLE001 - diagnostics
            print(f"  {name}: LOAD FAILED {type(exc).__name__}: {exc}")
            continue
        print(f"  {geometry_report(gdf, name).describe()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose geometry used by the map build")
    parser.add_argument("--config", default="config.yml")
    parser.add_argument("--target-crs", default="EPSG:4326", help="CRS the layers are clipped in")
    parser.add_argument("--skip-layers", action="store_true", help="Only check the boundary")
    args = parser.parse_args()

    cfg = load_yaml_config(args.config)
    _versions()
    diagnose_boundary(cfg, args.target_crs)
    if not args.skip_layers:
        diagnose_layers(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
