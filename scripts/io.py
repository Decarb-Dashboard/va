"""Input/output helpers for boundary and emissions datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.errors import GEOSException
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid


EPSG_4326 = "EPSG:4326"


@dataclass
class GeometryStats:
    """What sanitising a layer had to change, for build diagnostics."""

    label: str
    total: int = 0
    null: int = 0
    empty: int = 0
    non_finite: int = 0
    invalid: int = 0
    repaired: int = 0
    collapsed: int = 0
    dropped: int = 0
    kept: int = 0
    geom_types: list[str] = field(default_factory=list)

    def describe(self) -> str:
        """Health of a layer as read, before anything is changed."""
        return (
            f"{self.label}: {self.total} features {self.geom_types}"
            f" | null {self.null}, empty {self.empty}, non-finite {self.non_finite},"
            f" invalid {self.invalid}"
        )

    def format(self) -> str:
        """What sanitising actually changed."""
        return (
            f"{self.describe()} -> repaired {self.repaired}"
            f" (collapsed {self.collapsed}), dropped {self.dropped}, kept {self.kept}"
        )


def _flatten_parts(geometry: BaseGeometry | None) -> Iterator[BaseGeometry]:
    """Yield the simple (non-collection) parts of any geometry."""
    if geometry is None or geometry.is_empty:
        return
    if hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _flatten_parts(part)
    else:
        yield geometry


def collapse_to_dimension(geometry: BaseGeometry | None, dimension: int) -> BaseGeometry | None:
    """Reduce a geometry to the parts matching `dimension` (0 point/1 line/2 polygon).

    `make_valid()` turns a self-intersecting polygon into a mixed-dimension
    GeometryCollection (polygon + the collapsed edges as lines). GEOS overlay
    operations cannot determine a result dimension for such inputs and abort
    with "Should never reach here: Unable to determine overlay result geometry
    dimension", so collections are reduced back to the dimension the source
    feature had before repair.
    """
    parts = [part for part in _flatten_parts(geometry) if shapely.get_dimensions(part) == dimension]
    if not parts:
        return None
    merged = shapely.union_all(parts)
    if merged is None or merged.is_empty:
        return None
    return merged


def _has_finite_bounds(gdf: gpd.GeoDataFrame) -> np.ndarray:
    """True where a feature's bounds are finite (NaN/inf coordinates break GEOS)."""
    bounds = gdf.geometry.bounds.to_numpy(dtype="float64", na_value=np.nan)
    return np.isfinite(bounds).all(axis=1)


def geometry_report(gdf: gpd.GeoDataFrame, label: str) -> GeometryStats:
    """Describe a layer's geometry health without modifying it."""
    geometry = gdf.geometry
    non_null = gdf[geometry.notna() & ~geometry.is_empty]
    return GeometryStats(
        label=label,
        total=len(gdf),
        null=int(geometry.isna().sum()),
        empty=int(geometry.is_empty.sum()),
        non_finite=int((~_has_finite_bounds(non_null)).sum()) if len(non_null) else 0,
        invalid=int((~geometry.is_valid).sum()),
        geom_types=sorted(set(geometry.geom_type.dropna())),
    )


def sanitize_geometries(
    gdf: gpd.GeoDataFrame,
    label: str = "layer",
) -> tuple[gpd.GeoDataFrame, GeometryStats]:
    """Return a GEOS-safe copy of `gdf` plus a report of what changed.

    Drops null, empty and non-finite geometry, repairs invalid geometry with
    `make_valid()`, and keeps every repaired feature at its original dimension
    so no mixed-dimension collection reaches an overlay operation.
    """
    stats = geometry_report(gdf, label)
    if gdf.empty:
        return gdf.copy(), stats

    usable = gdf.geometry.notna() & ~gdf.geometry.is_empty
    cleaned = gdf[usable].copy()
    if not cleaned.empty:
        cleaned = cleaned[_has_finite_bounds(cleaned)].copy()

    if cleaned.empty:
        stats.dropped = stats.total
        stats.kept = 0
        return cleaned, stats

    invalid = ~cleaned.geometry.is_valid
    if invalid.any():
        # Remember the dimension each feature had before repair: make_valid may
        # add lower-dimension debris that we drop again below.
        dimensions = shapely.get_dimensions(cleaned.geometry.values)
        stats.repaired = int(invalid.sum())

        collapsed = 0
        fixed: list[BaseGeometry | None] = []
        for geometry, dimension in zip(cleaned.geometry[invalid], dimensions[invalid.to_numpy()]):
            try:
                geometry = make_valid(geometry)
            except (GEOSException, ValueError) as exc:
                # One unrepairable feature is dropped; the layer still builds.
                print(f"[WARN] {label}: dropped a feature make_valid() could not repair: {exc}")
                fixed.append(None)
                continue
            if geometry is not None and geometry.geom_type == "GeometryCollection":
                geometry = collapse_to_dimension(geometry, int(dimension))
                collapsed += 1
            fixed.append(geometry)
        stats.collapsed = collapsed
        cleaned.loc[invalid, "geometry"] = gpd.GeoSeries(
            fixed, index=cleaned.index[invalid], crs=cleaned.crs
        )
        cleaned = cleaned[cleaned.geometry.notna() & ~cleaned.geometry.is_empty].copy()

    stats.kept = len(cleaned)
    stats.dropped = stats.total - stats.kept
    return cleaned, stats


def _repair_geometries(gdf: gpd.GeoDataFrame, label: str = "layer") -> gpd.GeoDataFrame:
    """Repair invalid geometries (e.g. unclosed LinearRings) in place."""
    if gdf.geometry is None:
        return gdf
    cleaned, stats = sanitize_geometries(gdf, label=label)
    if stats.dropped or stats.repaired:
        print(f"[INFO] {stats.format()}")
    return cleaned


def load_va_boundary(path: str) -> gpd.GeoDataFrame:
    """Load the Virginia boundary file as a GeoDataFrame."""
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Boundary file '{path}' is empty.")
    return _repair_geometries(gdf, label=Path(path).name)


def load_vector_layer(path: str, layer: str | None = None) -> gpd.GeoDataFrame:
    """Load a geospatial layer from a vector file (GeoJSON/GPKG/shapefile)."""
    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    if gdf.empty:
        layer_msg = f" (layer='{layer}')" if layer else ""
        raise ValueError(f"Vector file '{path}'{layer_msg} is empty.")
    return _repair_geometries(gdf, label=Path(path).name)


def load_vector_collection(path: str, layer: str | None = None) -> gpd.GeoDataFrame:
    """Load one vector layer or combine all vector files found under a directory."""
    input_path = Path(path)
    if input_path.is_file():
        return load_vector_layer(str(input_path), layer=layer)

    if not input_path.is_dir():
        raise FileNotFoundError(f"Vector input path does not exist: {input_path}")

    vector_paths = sorted(
        p
        for p in input_path.rglob("*")
        if p.is_file() and p.suffix.lower() in {".geojson", ".json", ".gpkg", ".shp"}
    )
    if not vector_paths:
        raise ValueError(f"No supported vector files found under directory: {input_path}")

    gdfs = [load_vector_layer(str(vector_path), layer=layer) for vector_path in vector_paths]
    base_crs = gdfs[0].crs
    merged = []
    for gdf in gdfs:
        if base_crs is not None and gdf.crs != base_crs:
            merged.append(gdf.to_crs(base_crs))
        else:
            merged.append(gdf)

    combined = gpd.GeoDataFrame(
        pd.concat(merged, ignore_index=True),
        geometry="geometry",
        crs=base_crs,
    )
    if combined.empty:
        raise ValueError(f"Vector input '{input_path}' resolved to zero features.")
    return combined


def load_emissions_csv(path: str) -> pd.DataFrame:
    """Load emissions CSV data into a DataFrame."""
    try:
        return pd.read_csv(path)
    except pd.errors.ParserError as exc:
        raise ValueError(
            f"Failed to parse CSV '{path}': inconsistent commas/quoting are likely; "
            "check quoted fields in rows that contain commas."
        ) from exc


def validate_required_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    """Ensure required columns are present in a DataFrame."""
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def emissions_to_gdf(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    crs: str = EPSG_4326,
) -> gpd.GeoDataFrame:
    """Convert emissions tabular records to a point GeoDataFrame."""
    validate_required_columns(df, [lat_col, lon_col])

    clean_df = df.copy()
    clean_df[lat_col] = pd.to_numeric(clean_df[lat_col], errors="coerce")
    clean_df[lon_col] = pd.to_numeric(clean_df[lon_col], errors="coerce")
    clean_df = clean_df.dropna(subset=[lat_col, lon_col])

    return gpd.GeoDataFrame(
        clean_df,
        geometry=gpd.points_from_xy(clean_df[lon_col], clean_df[lat_col]),
        crs=crs,
    )


def ensure_crs(gdf: gpd.GeoDataFrame, target_crs: str) -> gpd.GeoDataFrame:
    """Return a GeoDataFrame in the target CRS."""
    if gdf.crs is None:
        raise ValueError("GeoDataFrame has no CRS; cannot reproject.")
    if str(gdf.crs) == target_crs:
        return gdf
    return gdf.to_crs(target_crs)
