import {buildTerrainSurface, terrainTileCount} from './terrain.js';

const {
  DeckGL,
  TerrainLayer,
  GeoJsonLayer,
  IconLayer,
  BitmapLayer,
  MaskExtension,
  WebMercatorViewport
} = deck;

const COLORS = {
  boundary: [143, 166, 189, 220],
  railroads: [215, 221, 230, 92],
  roads: [255, 210, 122, 120],
  places: [154, 167, 180, 60],
  ports: [77, 208, 225, 190]
};

const LAYER_LABELS = {
  boundary: 'Virginia state boundary',
  'pipelines-glow': 'Natural gas pipelines',
  pipelines: 'Natural gas pipelines',
  railroads: 'Railroads',
  'primary-roads': 'Primary roads',
  'incorporated-places': 'Incorporated places',
  ports: 'Principal ports'
};

const DATA_WEIGHTS = {
  manifest: 2,
  boundary: 3,
  ghg: 3,
  principal_ports: 1,
  pipelines: 5,
  incorporated_places: 8,
  primary_roads: 14,
  railroads: 20
};
const TERRAIN_WEIGHT = 30;
const RENDER_WEIGHT = 14;
const READY_SETTLE_MS = 700;
const READY_TIMEOUT_MS = 20000;

const ICON_SIZE_MIN_PX = 20;
const ICON_SIZE_MAX_PX = 54;

// Facilities and reference layers are flat (z = 0) while the terrain mesh has
// real elevation, so depth testing hides them behind ridges as you zoom in.
// Drawing them with the depth test disabled keeps them on top at every zoom.
const OVERLAY_PARAMETERS = {depthCompare: 'always'};

const ELEVATION_TILE_URL =
  'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const rgba = ([r, g, b, a = 255]) => `rgba(${r},${g},${b},${(a / 255).toFixed(2)})`;

const hexToRgb = (hex, alpha = 255) => {
  const value = String(hex || '').replace('#', '');
  if (value.length !== 6) return [255, 255, 255, alpha];
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
    alpha
  ];
};

/* ---------------------------------------------------------------- loading UI */

const progress = (() => {
  const fill = document.getElementById('loading-fill');
  const status = document.getElementById('loading-status');
  const overlay = document.getElementById('loading');
  let done = 0;
  let total = 0;
  let finished = false;

  const paint = () => {
    if (!fill) return;
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    fill.style.width = `${pct}%`;
  };

  return {
    reserve(weight) {
      total += weight;
      paint();
    },
    advance(weight, message) {
      done += weight;
      if (message && status) status.textContent = message;
      paint();
    },
    message(text) {
      if (status) status.textContent = text;
    },
    finish() {
      if (finished) return;
      finished = true;
      done = total;
      paint();
      if (status) status.textContent = 'Ready';
      if (overlay) {
        overlay.classList.add('done');
        setTimeout(() => overlay.remove(), 500);
      }
      document.body.classList.add('map-ready');
    },
    fail(message) {
      if (status) status.textContent = message;
      if (overlay) overlay.classList.add('failed');
    }
  };
})();

/* ------------------------------------------------------------------ data i/o */

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

function formatTons(value) {
  return Number(value || 0).toLocaleString('en-US', {maximumFractionDigits: 0});
}

function normalizeSubparts(subparts) {
  return String(subparts || '')
    .split(',')
    .map((part) => part.trim().toUpperCase())
    .filter(Boolean)
    .sort()
    .join(',');
}

function iconNameToFile(iconName) {
  if (typeof iconName !== 'string' || iconName.length === 0) {
    return 'icon_v2_C.png';
  }
  return iconName.includes('.') ? iconName : `${iconName}.png`;
}

/* ------------------------------------------------------------------- icons */

function buildIconIndex(manifest) {
  const iconConfig = manifest.icons || {};
  const baseDir = iconConfig.base_dir || 'geo-icons';
  const labels = iconConfig.labels || {};
  const defaultIconName = iconConfig.default || 'icon_v2_C';

  const bySubparts = {};
  Object.entries(iconConfig.by_subparts || {}).forEach(([subparts, iconName]) => {
    bySubparts[normalizeSubparts(subparts)] = String(iconName);
  });

  const iconName = (subparts) => bySubparts[normalizeSubparts(subparts)] || defaultIconName;

  return {
    iconName,
    url: (name) => `../${baseDir}/${iconNameToFile(name)}`,
    label: (name) => labels[name] || 'Other reporting facility',
    icon: (feature) => ({
      url: `../${baseDir}/${iconNameToFile(iconName(feature?.properties?.subparts))}`,
      width: 128,
      height: 128,
      anchorY: 128,
      mask: false
    })
  };
}

/** Legend entries for the facility icons that actually appear in the data. */
function buildIconLegend(features, iconIndex) {
  const groups = new Map();
  features.forEach((feature) => {
    const name = iconIndex.iconName(feature.properties?.subparts);
    const entry = groups.get(name) || {
      name,
      url: iconIndex.url(name),
      label: iconIndex.label(name),
      count: 0,
      tons: 0
    };
    entry.count += 1;
    entry.tons += Number(feature.properties?.ghg_quantity_metric_tons_co2e) || 0;
    groups.set(name, entry);
  });
  return [...groups.values()].sort((a, b) => b.tons - a.tons);
}

/* ------------------------------------------------------------------ basemap */

/**
 * Resolve the raster basemap tile template, or null to use the key-free
 * shaded-relief surface.
 *
 * CARTO's basemap tiles require an API key; without one they render an
 * "API KEY REQUIRED" watermark, so an unkeyed texture config is refused here
 * rather than drawn. The key lives in config.yml (web.basemap.api_key) and is
 * published in the deck manifest: like every credential in a static site it is
 * visible to visitors, so restrict it by domain in the CARTO dashboard.
 */
function resolveBasemapTexture(basemapConfig) {
  const config = basemapConfig || {};
  if (String(config.mode || 'relief').toLowerCase() !== 'texture') {
    return null;
  }

  const template = String(config.url || '').trim();
  const apiKey = String(config.api_key || '').trim();
  if (!template) {
    console.warn('basemap.mode is "texture" but basemap.url is empty; using shaded relief.');
    return null;
  }
  if (template.includes('{api_key}') && !apiKey) {
    console.warn(
      'basemap.mode is "texture" but no basemap.api_key is set. ' +
        'Get a key at https://carto.com/basemaps/apikey/ or leave mode as "relief". ' +
        'Falling back to shaded relief.'
    );
    return null;
  }
  return template.replace('{api_key}', encodeURIComponent(apiKey));
}

/* -------------------------------------------------------------- view state */

function fitViewState(bounds, padding) {
  const container = document.getElementById('app');
  const width = Math.max(container?.clientWidth || window.innerWidth, 320);
  const height = Math.max(container?.clientHeight || window.innerHeight, 320);
  const [minLon, minLat, maxLon, maxLat] = bounds;

  const viewport = new WebMercatorViewport({width, height});
  const fitted = viewport.fitBounds(
    [
      [minLon, minLat],
      [maxLon, maxLat]
    ],
    {padding: Math.min(padding, Math.floor(Math.min(width, height) / 4))}
  );
  return {longitude: fitted.longitude, latitude: fitted.latitude, zoom: fitted.zoom};
}

function clampToVirginia(viewState, bounds, zoomRange) {
  const [minLon, minLat, maxLon, maxLat] = bounds;
  return {
    ...viewState,
    longitude: clamp(viewState.longitude, minLon - 0.2, maxLon + 0.2),
    latitude: clamp(viewState.latitude, minLat - 0.2, maxLat + 0.2),
    zoom: clamp(viewState.zoom, zoomRange[0], zoomRange[1]),
    pitch: clamp(viewState.pitch, 0, 75)
  };
}

/**
 * Show the current camera as zoom (level and percentage of the allowed range),
 * bearing and tilt, so a view worth keeping can be read off the map and set as
 * web.initial_* / web.max_zoom in config.yml.
 */
function makeViewReadout(zoomRange) {
  const zoomElement = document.getElementById('zoom-readout');
  const cameraElement = document.getElementById('camera-readout');
  return (viewState) => {
    const [min, max] = zoomRange;
    const zoom = viewState.zoom;
    const bearing = Math.round(viewState.bearing || 0);
    const pitch = Math.round(viewState.pitch || 0);

    if (zoomElement) {
      const span = Math.max(max - min, 1e-6);
      const percent = Math.round(clamp((zoom - min) / span, 0, 1) * 100);
      zoomElement.textContent = `z ${zoom.toFixed(1)} · ${percent}%`;
      zoomElement.title =
        `Zoom ${zoom.toFixed(2)} of ${min.toFixed(2)}–${max.toFixed(2)} (web.max_zoom in config.yml)`;
    }
    if (cameraElement) {
      cameraElement.textContent = `↻ ${bearing}° · ∡ ${pitch}°`;
      cameraElement.title =
        `Bearing ${bearing}°, tilt ${pitch}° (web.initial_bearing / web.initial_pitch in config.yml)`;
    }
  };
}

/* ---------------------------------------------------------------------- app */

(async () => {
  try {
    Object.values(DATA_WEIGHTS).forEach((weight) => progress.reserve(weight));
    progress.reserve(TERRAIN_WEIGHT);
    progress.reserve(RENDER_WEIGHT);
    progress.message('Loading map configuration…');

    const manifest = await loadJson('../output/deck-data/manifest.json');
    progress.advance(DATA_WEIGHTS.manifest, 'Loading Virginia layers…');

    const webCfg = manifest.web || {};
    const styleCfg = manifest.style || {};
    const bounds = manifest.bounds;

    const meshColor = hexToRgb(webCfg.terrain_mesh_color || '#28323d').slice(0, 3);
    const basemapTexture = resolveBasemapTexture(webCfg.basemap);
    const pipelineCore = hexToRgb(styleCfg.pipelines_color || '#c46bff', 255);
    const pipelineGlow = hexToRgb(styleCfg.pipelines_glow_color || '#9D00FF', 90);

    const fetchLayer = async (key, message) => {
      const data = await loadJson(`../${manifest.files[key]}`);
      progress.advance(DATA_WEIGHTS[key] || 1, message);
      return data;
    };

    // Vector layers are fetched here rather than by deck.gl so the progress bar
    // reflects real work and the map only appears once everything is in hand.
    const [boundaryGeoJson, ghgGeoJson, portsGeoJson, pipelinesGeoJson] = await Promise.all([
      fetchLayer('boundary', 'Loading facilities…'),
      fetchLayer('ghg', 'Loading pipelines…'),
      fetchLayer('principal_ports'),
      fetchLayer('pipelines', 'Loading roads and rail…')
    ]);
    const [placesGeoJson, roadsGeoJson, railroadsGeoJson] = await Promise.all([
      fetchLayer('incorporated_places'),
      fetchLayer('primary_roads'),
      fetchLayer('railroads', 'Building terrain relief…')
    ]);

    const ghgFeatures = ghgGeoJson.features || [];
    const boundaryFeatures = boundaryGeoJson.features || [];
    const iconIndex = buildIconIndex(manifest);
    const maxTons = Math.max(
      1,
      ...ghgFeatures.map((f) => Number(f.properties?.ghg_quantity_metric_tons_co2e) || 0)
    );

    // Hand the panel its data as soon as it exists; charts render while the
    // terrain is still being shaded.
    window.__ghgFeatures = ghgFeatures;
    window.__ghgLegend = {
      layers: [
        {label: 'Terrain relief (low \u2192 high)', type: 'relief'},
        {label: 'State boundary', type: 'line', color: rgba(COLORS.boundary)},
        {label: 'Natural gas pipelines', type: 'line', color: rgba(pipelineCore), glow: true},
        {label: 'Primary roads', type: 'line', color: rgba(COLORS.roads)},
        {label: 'Railroads', type: 'line', color: rgba(COLORS.railroads)},
        {label: 'Incorporated places', type: 'line', color: rgba(COLORS.places)},
        {label: 'Principal ports', type: 'circle', color: rgba(COLORS.ports)}
      ],
      icons: buildIconLegend(ghgFeatures, iconIndex),
      sizeScale: {
        minTons: Math.min(...ghgFeatures.map((f) => f.properties.ghg_quantity_metric_tons_co2e || 0)),
        maxTons,
        minPx: ICON_SIZE_MIN_PX,
        maxPx: ICON_SIZE_MAX_PX
      }
    };
    window.dispatchEvent(new Event('ghg-data-ready'));

    /* ------------------------------------------------------------- terrain */

    const terrainZoom = Number(webCfg.terrain_tile_zoom ?? 8);
    const terrainExaggeration = manifest.terrain_exaggeration || 1.8;
    const expectedTiles = Math.max(1, terrainTileCount(bounds, terrainZoom));

    // Terrain progress comes either from relief tiles or from mesh tiles,
    // whichever basemap mode is configured.
    let terrainProgressLeft = TERRAIN_WEIGHT;
    const advanceTerrain = (weight) => {
      const step = Math.min(weight, terrainProgressLeft);
      terrainProgressLeft -= step;
      if (step > 0) progress.advance(step);
    };

    // With a raster basemap the tiles are textured onto the 3D mesh; without
    // one the shaded relief is built in the background so the map paints right
    // away and is draped in when ready.
    const surfacePromise = basemapTexture
      ? Promise.resolve(null)
      : buildTerrainSurface({
          bounds,
          zoom: terrainZoom,
          boundaryFeatures,
          verticalExaggeration: terrainExaggeration,
          onTileSettled: () => advanceTerrain(TERRAIN_WEIGHT / expectedTiles)
        }).catch((error) => {
          console.warn('Terrain surface unavailable:', error);
          return null;
        });

    progress.message('Drawing the map…');

    /* -------------------------------------------------------------- layers */

    let surface = null;

    const buildLayers = () => [
      // Raster basemap path: clip the textured 3D mesh to Virginia.
      basemapTexture &&
        new GeoJsonLayer({
          id: 'va-mask',
          data: boundaryFeatures,
          operation: 'mask',
          stroked: false,
          filled: true,
          getFillColor: [0, 0, 0, 255],
          pickable: false
        }),
      basemapTexture &&
        new TerrainLayer({
          id: 'terrain',
          elevationData: ELEVATION_TILE_URL,
          texture: basemapTexture,
          bounds,
          extent: bounds,
          extensions: MaskExtension ? [new MaskExtension()] : [],
          maskId: 'va-mask',
          elevationDecoder: {rScaler: 256, gScaler: 1, bScaler: 1 / 256, offset: -32768},
          strategy: 'no-overlap',
          minZoom: 0,
          maxZoom: Number(webCfg.terrain_max_tile_zoom ?? 13),
          wireframe: false,
          color: meshColor,
          material: {ambient: 0.45, diffuse: 0.6, shininess: 8, specularColor: [90, 100, 115]},
          operation: 'terrain+draw',
          elevationScale: terrainExaggeration,
          onTileLoad: () => {
            advanceTerrain(TERRAIN_WEIGHT / 12);
            noteMapActivity();
          },
          onTileError: () => noteMapActivity()
        }),
      // Key-free path: shaded relief computed from the same elevation tiles.
      surface &&
        new BitmapLayer({
          id: 'terrain-surface',
          image: surface.image,
          bounds: surface.bounds,
          pickable: false
        }),
      new GeoJsonLayer({
        id: 'boundary',
        data: boundaryFeatures,
        stroked: true,
        filled: false,
        getLineColor: COLORS.boundary,
        getLineWidth: 120,
        lineWidthMinPixels: 1.2,
        parameters: OVERLAY_PARAMETERS,
        pickable: false
      }),
      new GeoJsonLayer({
        id: 'incorporated-places',
        data: placesGeoJson,
        stroked: true,
        filled: false,
        getLineColor: COLORS.places,
        getLineWidth: 40,
        lineWidthMinPixels: 1,
        parameters: OVERLAY_PARAMETERS,
        pickable: true
      }),
      new GeoJsonLayer({
        id: 'railroads',
        data: railroadsGeoJson,
        stroked: true,
        filled: false,
        getLineColor: COLORS.railroads,
        getLineWidth: 50,
        lineWidthMinPixels: 1,
        parameters: OVERLAY_PARAMETERS,
        pickable: true
      }),
      new GeoJsonLayer({
        id: 'primary-roads',
        data: roadsGeoJson,
        stroked: true,
        filled: false,
        getLineColor: COLORS.roads,
        getLineWidth: 95,
        lineWidthMinPixels: 1,
        parameters: OVERLAY_PARAMETERS,
        pickable: true
      }),
      // Pipelines read as a single bright line with a soft halo underneath.
      new GeoJsonLayer({
        id: 'pipelines-glow',
        data: pipelinesGeoJson,
        stroked: true,
        filled: false,
        getLineColor: pipelineGlow,
        getLineWidth: 900,
        lineWidthMinPixels: 6,
        lineWidthMaxPixels: 14,
        lineJointRounded: true,
        lineCapRounded: true,
        parameters: OVERLAY_PARAMETERS,
        pickable: false
      }),
      new GeoJsonLayer({
        id: 'pipelines',
        data: pipelinesGeoJson,
        stroked: true,
        filled: false,
        getLineColor: pipelineCore,
        getLineWidth: 220,
        lineWidthMinPixels: 2,
        lineWidthMaxPixels: 5,
        lineJointRounded: true,
        lineCapRounded: true,
        parameters: OVERLAY_PARAMETERS,
        pickable: true
      }),
      new GeoJsonLayer({
        id: 'ports',
        data: portsGeoJson,
        pointType: 'circle',
        filled: true,
        getPointRadius: 1600,
        pointRadiusMinPixels: 3,
        getFillColor: COLORS.ports,
        parameters: OVERLAY_PARAMETERS,
        pickable: true
      }),
      new IconLayer({
        id: 'ghg-facilities',
        data: ghgFeatures,
        getPosition: (d) => d.geometry.coordinates,
        getIcon: iconIndex.icon,
        // Icon area tracks reported emissions.
        getSize: (d) => {
          const tons = Math.max(Number(d.properties?.ghg_quantity_metric_tons_co2e) || 0, 0);
          const normalized = Math.sqrt(tons) / Math.sqrt(maxTons);
          return ICON_SIZE_MIN_PX + normalized * (ICON_SIZE_MAX_PX - ICON_SIZE_MIN_PX);
        },
        sizeUnits: 'pixels',
        parameters: OVERLAY_PARAMETERS,
        pickable: true
      })
    ].filter(Boolean);

    /* ----------------------------------------------------------- view state */

    const fitPadding = Number(webCfg.fit_padding_px ?? 56);
    const zoomOutAllowance = Number(webCfg.zoom_out_allowance ?? 0.6);
    const fitted = fitViewState(bounds, fitPadding);
    let zoomRange = [fitted.zoom - zoomOutAllowance, Number(webCfg.max_zoom ?? 12.5)];

    const initialViewState = {
      ...fitted,
      minZoom: zoomRange[0],
      maxZoom: zoomRange[1],
      pitch: Number(webCfg.initial_pitch ?? 0),
      bearing: Number(webCfg.initial_bearing ?? 0)
    };
    let viewState = {...initialViewState};
    let showView = makeViewReadout(zoomRange);
    showView(initialViewState);

    /* ---------------------------------------------------- readiness tracking */

    let firstRenderDone = false;
    let surfaceSettled = false;
    let settleTimer = null;
    const hardStop = setTimeout(() => progress.finish(), READY_TIMEOUT_MS);

    function noteMapActivity() {
      if (!firstRenderDone || !surfaceSettled) return;
      clearTimeout(settleTimer);
      settleTimer = setTimeout(() => {
        clearTimeout(hardStop);
        progress.finish();
      }, READY_SETTLE_MS);
    }

    const deckInstance = new DeckGL({
      container: 'app',
      mapStyle: null,
      controller: {dragRotate: true, touchRotate: true, keyboard: true},
      pickingRadius: 8,
      initialViewState,
      layers: buildLayers(),
      onViewStateChange: ({viewState: next}) => {
        viewState = clampToVirginia(next, bounds, zoomRange);
        deckInstance.setProps({viewState});
        showView(viewState);
        return viewState;
      },
      onAfterRender: () => {
        if (firstRenderDone) return;
        firstRenderDone = true;
        progress.advance(RENDER_WEIGHT);
        noteMapActivity();
      },
      onClick: ({object, layer}) => {
        if (!object || !layer) return;
        if (layer.id === 'ghg-facilities') {
          const props = object.properties || {};
          if (window.__onFacilityClick) {
            window.__onFacilityClick(props.facility_name, props.subparts);
          }
        }
      },
      getTooltip: ({object, layer}) => {
        if (!object || !layer) return null;
        if (layer.id === 'ghg-facilities') {
          const props = object.properties || {};
          const iconName = iconIndex.iconName(props.subparts);
          return {
            html: `<strong>${props.facility_name || 'Facility'}</strong><br/>${iconIndex.label(iconName)}<br/>Subparts: ${props.subparts || 'N/A'}<br/>GHG: ${formatTons(props.ghg_quantity_metric_tons_co2e)} tCO2e<br/><em style="color:#7a8a9e;font-size:10px">Click for emissions history</em>`
          };
        }
        const label = LAYER_LABELS[layer.id];
        return label ? {text: label} : null;
      }
    });

    /* --------------------------------------------------------- view controls */

    const resetView = () => {
      const refit = fitViewState(bounds, fitPadding);
      zoomRange = [refit.zoom - zoomOutAllowance, Number(webCfg.max_zoom ?? 12.5)];
      showView = makeViewReadout(zoomRange);
      viewState = {
        ...refit,
        minZoom: zoomRange[0],
        maxZoom: zoomRange[1],
        pitch: Number(webCfg.initial_pitch ?? 0),
        bearing: Number(webCfg.initial_bearing ?? 0)
      };
      deckInstance.setProps({viewState});
      showView(viewState);
    };

    // Flatten to straight-down without moving the camera.
    const topDownView = () => {
      viewState = {...viewState, pitch: 0, bearing: 0};
      deckInstance.setProps({viewState});
      showView(viewState);
    };

    document.getElementById('top-down')?.addEventListener('click', topDownView);
    document.getElementById('reset-view')?.addEventListener('click', resetView);

    // Drape the shaded relief over the mesh as soon as it has been built.
    surfacePromise.then((result) => {
      surface = result;
      surfaceSettled = true;
      if (surface) {
        deckInstance.setProps({layers: buildLayers()});
      }
      noteMapActivity();
    });

    window.addEventListener('resize', () => {
      const refit = fitViewState(bounds, fitPadding);
      zoomRange = [refit.zoom - zoomOutAllowance, Number(webCfg.max_zoom ?? 12.5)];
      showView = makeViewReadout(zoomRange);
      viewState = {
        ...viewState,
        minZoom: zoomRange[0],
        maxZoom: zoomRange[1],
        zoom: clamp(viewState.zoom, zoomRange[0], zoomRange[1])
      };
      deckInstance.setProps({viewState});
      showZoom(viewState.zoom);
    });
  } catch (error) {
    console.error(error);
    progress.fail(error.message);
    const app = document.getElementById('app');
    if (app) {
      app.innerHTML = `<div style="color:#d8e2ee;padding:16px;">${error.message}</div>`;
    }
  }
})();
