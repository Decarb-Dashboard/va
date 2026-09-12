from pathlib import Path
import geopandas as gpd
import pandas as pd


def merge_geojson_chunks(raw_dir, output_path):
    """
    Merge multiple GeoJSON chunks into a single GeoPackage.

    Parameters
    ----------
    raw_dir : str or Path
        Directory containing chunked Geojson files
    output_path : str or Path
        Output geopackage path
    """

    raw_dir = Path(raw_dir)
    output_path = Path(output_path)

    files = sorted(raw_dir.glob("*.geojson"))

    if not files:
        raise FileNotFoundError(f"No GeoJSON files found in {raw_dir}")

    print(f"\n🔎 Found {len(files)} chunk files")
    for f in files:
        print(f"   • {f.name}")

    gdfs = []
    for f in files:
        print(f"\n📥 Loading: {f.name}")
        gdfs.append(gpd.read_file(f))

    print("\n🔗 Merging datasets...")
    merged = gpd.GeoDataFrame(
        pd.concat(gdfs, ignore_index=True),
        crs=gdfs[0].crs
    )

    print(f"✅ Total features: {len(merged)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n💾 Saving to: {output_path}")
    merged.to_file(output_path, driver="GPKG")

    print("\n🎉 Merge complete.")


if __name__ == "__main__":

    RAW_DIR = "geo-layers/natural_gas_pipelines/raw"
    OUTPUT = "geo-layers/natural_gas_pipelines/pipelines_us.gpkg"

    merge_geojson_chunks(RAW_DIR, OUTPUT)
