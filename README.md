# Virginia Industrial Greenhouse Gas Dashboard (`va-ghg-dashboard`)

A geospatial rendering pipeline for producing a dark-theme dashboard map of Virginia industrial greenhouse gas (GHG) facilities.

The project renders a single PNG map showing the Virginia boundary, reference layers (pipelines, railroads, roads, ports, incorporated places), terrain relief fetched from AWS Terrarium tiles, and per-facility icon overlays for reporting year 2023.


## Map preview and web version

![Virginia GHG dashboard map](output/va_ghg_map.png)

Interactive web map: https://Decarb-Dashboard.github.io/va/web/

---

## What this project does

- Loads and validates runtime configuration from `config.yml`.
- Reads a Virginia boundary dataset and reprojects it for plotting.
- Renders a 16:9 map + right-side panel layout in dark theme.
- Fetches Terrarium elevation tiles at runtime to produce a multi-directional hillshade with hypsometric tinting.
- Overlays reference infrastructure layers (pipelines, railroads, roads, ports, places).
- Plots 2023 facility locations with subpart-based icons scaled by GHG emissions.
- Outputs a single PNG: `output/va_ghg_map.png`.

---

## Repository layout

```text
.
├── config.yml               # Runtime configuration (paths, style, render settings)
├── environment.yml           # Conda environment specification
├── scripts/
│   ├── build.py              # CLI entrypoint
│   ├── config.py             # YAML load + schema/path validation
│   ├── io.py                 # Boundary/CSV loading + GeoDataFrame utilities
│   ├── layout.py             # Figure, axes, and theme setup
│   ├── map_base.py           # Boundary draw + extent helpers
│   ├── points.py             # Facility icon rendering
│   ├── render.py             # Render orchestration
│   ├── resize_icons.py       # Icon preprocessing utility
│   └── merge_pipelines.py    # GeoJSON merge utility
├── geo-boundaries/               # State/census boundary layers
│   └── va_boundary_20m.geojson
├── ghg-data/
│   ├── curated/
│   │   ├── facilities_va_validated.csv
│   │   └── rejects/
│   └── flight_cleaned_va_all_years.csv
├── geo-layers/                   # Reference geospatial layers
├── geo-icons/                    # Facility icon assets
├── notebooks/                # Development notebooks
└── output/                   # Generated artifacts
```

---

## Quick start

### 1) Create environment

```bash
conda env create -f environment.yml
conda activate va-ghg
```

### 2) (Optional) Generate smaller icon assets

```bash
python -m scripts.resize_icons --input-dir geo-icons/original --output-dir geo-icons/small --max-size-px 100
```

### 3) Render the map

```bash
python -m scripts.build --config config.yml
```

Output: `output/va_ghg_map.png`

### 4) Build deck.gl assets and run the interactive map

```bash
python -m scripts.build --config config.yml --target deck
python -m http.server 8000
```

Then open `http://localhost:8000/web/` to view the interactive deck.gl map with:
- Terrain (`TerrainLayer` + AWS Terrarium elevation tiles)
- Geo reference layers (pipelines, railroads, roads, incorporated places, ports, VA boundary), clipped to Virginia for better performance
- GHG facilities (`ScatterplotLayer`, 2023 only, radius scaled by emissions)


---

## Configuration reference (`config.yml`)

### Top-level sections

- `state`: state code (currently `VA`)
- `render`: output sizing, DPI, theme, and output filename
- `layout`: map/panel width fractions (must sum to `1.0`)
- `paths`: boundary, emissions, icons, and reference layer paths
- `icons`: subpart-to-icon filename mappings
- `terrain`: tile zoom level, vertical exaggeration, tint strength
- `style`: map colors, alpha, line width, marker size, and extent padding

### Required keys (validated at runtime)

- `render`: `width_px`, `height_px`, `dpi`, `output_dir`, `output_png`, `theme`
- `layout`: `map_frac`, `panel_frac`
- `paths`: `va_boundary`
- `style`: `background`, `boundary_linewidth`, `boundary_alpha`

If configured, `paths.emissions_csv` must point to an existing file.

---


## Data sources

- EPA GHGRP FLIGHT Tool: https://ghgdata.epa.gov/flight/?viewType=line
- US Census TIGER Boundaries: https://www2.census.gov/geo/tiger/GENZ2023/shp/

---

## Data expectations

### Boundary input

`paths.va_boundary` should point to a valid geospatial file readable by GeoPandas.

### Emissions input

The CSV referenced by `paths.emissions_csv` must contain lat/lon columns defined by:

- `paths.emissions_lat_col` (default: `latitude`)
- `paths.emissions_lon_col` (default: `longitude`)

Rows with non-numeric or missing coordinates are dropped during point conversion.


### GHGRP subpart reference (common codes in this dataset)

| Code   | Official Subpart Name                                    | Description + EPA Link                                                                                                                |
| ------ | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **AA** | Pulp and Paper Manufacturing | Emissions from pulp & paper mills, including process emissions and combustion sources. ([click me](https://www.epa.gov/ghgreporting/subpart-aa-pulp-and-paper-manufacturing)) |
| **C** | General Stationary Fuel Combustion | Boilers, heaters, turbines, furnaces, and other stationary combustion units used for heat and power. ([click me](https://www.epa.gov/ghgreporting/subpart-c-general-stationary-fuel-combustion-sources)) |
| **D** | Electricity Generation | Fossil-fuel power plants generating electricity for grid supply. ([click me](https://www.epa.gov/ghgreporting/subpart-d-electricity-generation)) |
| **DD** | Electrical Transmission & Distribution Equipment | SF6 and other fluorinated gases from electrical switchgear and transmission equipment. ([click me](https://www.epa.gov/ghgreporting/subpart-dd-use-electric-transmission-and-distribution-equipment)) |
| **FF** | Underground Coal Mines | Methane emissions released from underground coal mining operations. ([click me](https://www.epa.gov/ghgreporting/subpart-ff-underground-coal-mines)) |
| **G** | Ammonia Manufacturing | Hydrogen reforming and chemical processes used to manufacture ammonia (fertilizer production). ([click me](https://www.epa.gov/ghgreporting/subpart-g-ammonia-manufacturing)) |
| **H** | Cement Production | CO2 released during clinker production and kiln operations in cement manufacturing. ([click me](https://www.epa.gov/ghgreporting/subpart-h-cement-production)) |
| **HH** | Municipal Solid Waste Landfills | Methane emissions generated from decomposition of waste in municipal landfills. ([click me](https://www.epa.gov/ghgreporting/subpart-hh-municipal-solid-waste-landfills)) |
| **I** | Electronics Manufacturing | Semiconductor and electronics manufacturing emissions, including fluorinated gases. ([click me](https://www.epa.gov/ghgreporting/subpart-i-electronics-manufacturing)) |
| **II** | Industrial Wastewater Treatment | Methane and nitrous oxide emissions from treatment of industrial wastewater streams. ([click me](https://www.epa.gov/ghgreporting/subpart-ii-industrial-wastewater-treatment)) |
| **N** | Glass Production | Process and combustion emissions from glass and fiberglass manufacturing furnaces. ([click me](https://www.epa.gov/ghgreporting/subpart-n-glass-production)) |
| **NN** | Suppliers of Natural Gas & Natural Gas Liquefied Liquids | Distribution and supply of natural gas and NGLs, including fugitive emissions accounting. ([click me](https://www.epa.gov/ghgreporting/subpart-nn-suppliers-natural-gas-and-natural-gas-liquids)) |
| **P** | Hydrogen Production | Industrial hydrogen production via reforming or gasification processes. ([click me](https://www.epa.gov/ghgreporting/subpart-p-hydrogen-production)) |
| **PP** | Suppliers of Carbon Dioxide | Facilities that capture, produce, or supply CO2 for industrial or commercial use. ([click me](https://www.epa.gov/ghgreporting/subpart-pp-suppliers-carbon-dioxide)) |
| **Q** | Iron and Steel Production | Blast furnaces, coke production, and steelmaking operations emitting CO2. ([click me](https://www.epa.gov/ghgreporting/subpart-q-iron-and-steel-production)) |
| **S** | Lime Manufacturing | Calcination of limestone/dolomite to produce lime, releasing CO2. ([click me](https://www.epa.gov/ghgreporting/subpart-s-lime-manufacturing)) |
| **TT** | Industrial Waste Landfills | Methane emissions from disposal of industrial waste materials. ([click me](https://www.epa.gov/ghgreporting/subpart-tt-industrial-waste-landfills)) |
| **V** | Nitric Acid Production | Nitrous oxide emissions from nitric acid production processes. ([click me](https://www.epa.gov/ghgreporting/subpart-v-nitric-acid-production)) |
| **W** | Petroleum & Natural Gas Systems | Oil & gas production, processing, transmission, storage, and distribution systems. ([click me](https://www.epa.gov/ghgreporting/subpart-w-petroleum-and-natural-gas-systems)) |
| **Y** | Petroleum Refineries | Refining of crude oil into fuels and petrochemical feedstocks. ([click me](https://www.epa.gov/ghgreporting/subpart-y-petroleum-refineries)) |

### Data dictionary (EPA FLIGHT cleaned output)

Primary table: `ghg-data/flight_cleaned_va_all_years.csv`

| Column | Type | Description |
| --- | --- | --- |
| `reporting_year` | `int` | Reporting year for facility emissions. |
| `facility_name` | `str` | Facility name as reported to EPA. |
| `ghgrp_id` | `int (nullable)` | EPA GHGRP facility identifier. |
| `reported_address` | `str` | Reported street address. |
| `city_name` | `str` | City name (title-cased during cleaning). |
| `county_name` | `str` | County name (title-cased during cleaning). |
| `state` | `str` | Two-letter state abbreviation (uppercased). |
| `zip_code` | `str` | ZIP code stored as a string (padded to 5 digits when numeric). |
| `latitude` | `float` | Facility latitude in decimal degrees. |
| `longitude` | `float` | Facility longitude in decimal degrees. |
| `parent_companies` | `str` | Parent-company ownership string from EPA export. |
| `ghg_quantity_metric_tons_co2e` | `float` | Total GHG emissions in metric tons CO2e (negative values are treated as missing). |
| `subparts` | `str` | GHGRP subpart codes reported for the facility (uppercased, spaces removed). |
| `source_sheet` | `str` | Original worksheet/tab name from the source workbook (typically the year). |
| `ghg_is_negative` | `bool` | Whether raw GHG quantity was negative before nulling in cleaned output. |

#### Cleaning notes

- Header rows are detected by finding `REPORTING YEAR` in raw worksheet exports.
- Source columns are normalized to `snake_case`.
- Numeric fields are coerced; invalid parses are set to null.
- Negative `ghg_quantity_metric_tons_co2e` values are nullified and tracked via `ghg_is_negative`.

---

## Troubleshooting

- **Config validation errors**: check required keys and section names in `config.yml`.
- **Boundary file errors**: confirm `paths.va_boundary` exists and is non-empty.
- **Emissions rendering errors**: verify `paths.emissions_csv` exists and includes valid lat/lon columns.
- **Import errors**: ensure dependencies from `environment.yml` are installed in the active environment.

---

## Roadmap (next sensible increments)

- Add panel content rendering (legends, metrics, labels).
- Add PDF export composition from rendered layers.
- Add automated tests for config validation and render smoke checks.

---

## License

No license file is currently included. Add a `LICENSE` file before public redistribution.
