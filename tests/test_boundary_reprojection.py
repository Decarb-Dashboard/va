"""Regression test for reprojecting the Virginia boundary.

`GeoDataFrame.to_crs()` rebuilds geometry through `shapely.set_coordinates()`,
which raises "IllegalArgumentException: Points of LinearRing do not form a
closed linestring" on some shapely/GEOS builds when the transformed ring no
longer closes exactly. The build reprojects the outline with
`io.reproject_polygonal()` instead; this test pins that behaviour.

Runs under pytest, or standalone:

    python -m pytest tests/test_boundary_reprojection.py
    python tests/test_boundary_reprojection.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.io import (  # noqa: E402
    expected_reprojected_bounds,
    has_finite_bounds,
    load_va_boundary,
    reproject_polygonal,
)

BOUNDARY_PATH = Path(__file__).resolve().parents[1] / "geo-boundaries" / "va_boundary_20m.geojson"

SOURCE_CRS = "EPSG:4269"
TARGET_CRS = "EPSG:4326"

# Virginia in WGS84, with room for boundary-file differences.
VIRGINIA_BOUNDS = (-83.7, 36.5, -75.2, 39.5)
BOUNDS_TOLERANCE_DEG = 0.5


def _boundary():
    boundary = load_va_boundary(str(BOUNDARY_PATH))
    assert str(boundary.crs) == SOURCE_CRS, f"fixture CRS changed: {boundary.crs}"
    return boundary


def test_reprojection_produces_valid_polygonal_geometry():
    projected = reproject_polygonal(_boundary(), TARGET_CRS)

    assert str(projected.crs) == TARGET_CRS
    assert len(projected) == 1
    assert set(projected.geometry.geom_type) <= {"Polygon", "MultiPolygon"}
    assert not projected.geometry.isna().any(), "reprojection produced null geometry"
    assert not projected.geometry.is_empty.any(), "reprojection produced empty geometry"
    assert projected.geometry.is_valid.all(), "reprojection produced invalid geometry"
    assert has_finite_bounds(projected).all(), "reprojection produced non-finite coordinates"


def test_reprojected_bounds_stay_over_virginia():
    projected = reproject_polygonal(_boundary(), TARGET_CRS)
    minx, miny, maxx, maxy = projected.total_bounds

    assert all(math.isfinite(value) for value in (minx, miny, maxx, maxy))
    for actual, expected in zip((minx, miny, maxx, maxy), VIRGINIA_BOUNDS):
        assert abs(actual - expected) < BOUNDS_TOLERANCE_DEG, (
            f"bounds {projected.total_bounds.tolist()} are not over Virginia"
        )


def test_reprojected_bounds_match_transformed_source_bounds():
    boundary = _boundary()
    projected = reproject_polygonal(boundary, TARGET_CRS)
    expected = expected_reprojected_bounds(boundary, TARGET_CRS)

    drift = np.abs(np.asarray(projected.total_bounds) - np.asarray(expected))
    assert drift.max() < 1e-6, f"bounds drifted from the transformed source box by {drift.max()}"


def test_union_all_returns_valid_polygonal_geometry():
    projected = reproject_polygonal(_boundary(), TARGET_CRS)
    mask = projected.geometry.union_all()

    assert mask is not None, "union_all() returned nothing"
    assert not mask.is_empty, "union_all() returned empty geometry"
    assert mask.is_valid, "union_all() returned invalid geometry"
    assert mask.geom_type in {"Polygon", "MultiPolygon"}
    assert all(math.isfinite(value) for value in mask.bounds)
    assert mask.area > 0


def test_projected_crs_round_trip():
    """The same helper must also work for the CRS the static render uses."""
    boundary = _boundary()
    mercator = reproject_polygonal(boundary, "EPSG:3857")

    assert str(mercator.crs) == "EPSG:3857"
    assert mercator.geometry.is_valid.all()
    assert has_finite_bounds(mercator).all()
    # Web Mercator metres, not degrees.
    assert abs(mercator.total_bounds[0]) > 1e6

    back = reproject_polygonal(mercator, SOURCE_CRS)
    drift = np.abs(np.asarray(back.total_bounds) - np.asarray(boundary.total_bounds))
    assert drift.max() < 1e-6, f"round trip drifted by {drift.max()}"


def test_reprojection_is_a_real_transform_not_a_relabel():
    boundary = _boundary()
    mercator = reproject_polygonal(boundary, "EPSG:3857")
    assert not np.allclose(mercator.total_bounds, boundary.total_bounds), (
        "coordinates unchanged: the CRS was relabelled instead of transformed"
    )


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface the real error
            failures += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
