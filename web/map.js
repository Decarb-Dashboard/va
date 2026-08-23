const {DeckGL, TerrainLayer, GeoJsonLayer, IconLayer, MaskExtension} = deck;

const COLORS = {
  boundary: [143, 166, 189, 220],
  pipelines: [157, 0, 255, 120],
  railroads: [215, 221, 230, 92],
  roads: [255, 210, 122, 120],
  places: [154, 167, 180, 60],
  ports: [77, 208, 225, 160]
};

const LAYER_LABELS = {
  boundary: 'Virginia state boundary',
  pipelines: 'Natural gas pipelines',
  railroads: 'Railroads',
  'primary-roads': 'Primary roads',
  'incorporated-places': 'Incorporated places',
  ports: 'Principal ports'
};

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadManifest() {
  return loadJson('../output/deck-data/manifest.json');
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
    return 'manufacturing.jpg';
  }
  if (iconName.includes('.')) {
    return iconName;
  }
  return `${iconName}.png`;
}

function buildFacilityIconResolver(manifest) {
  const iconConfig = manifest.icons || {};
  const iconsBaseDir = iconConfig.base_dir || 'geo-icons';
  const bySubpartsRaw = iconConfig.by_subparts || {};
  const defaultIconName = iconConfig.default || 'manufacturing';

  const bySubparts = {};
  Object.entries(bySubpartsRaw).forEach(([subparts, iconName]) => {
    bySubparts[normalizeSubparts(subparts)] = iconNameToFile(iconName);
  });

  const defaultIconFile = iconNameToFile(defaultIconName);

  return (feature) => {
    const subparts = normalizeSubparts(feature?.properties?.subparts);
    const iconFile = bySubparts[subparts] || defaultIconFile;
    return {
      url: `../${iconsBaseDir}/${iconFile}`,
      width: 128,
      height: 128,
      anchorY: 128,
      mask: false
    };
  };
}

function clampToVirginia(viewState, bounds) {
  const [minLon, minLat, maxLon, maxLat] = bounds;
  return {
    ...viewState,
    longitude: clamp(viewState.longitude, minLon - 0.2, maxLon + 0.2),
    latitude: clamp(viewState.latitude, minLat - 0.2, maxLat + 0.2),
    zoom: clamp(viewState.zoom, 7.1, 11.5)
  };
}

(async () => {
  try {
    const manifest = await loadManifest();
    const ghgGeoJson = await loadJson(`../${manifest.files.ghg}`);
    const boundaryGeoJson = await loadJson(`../${manifest.files.boundary}`);
    const ghgFeatures = ghgGeoJson.features || [];
    const boundaryFeatures = boundaryGeoJson.features || [];
    const terrainBounds = manifest.bounds;
    const terrainExtensions = MaskExtension ? [new MaskExtension()] : [];
    const getFacilityIcon = buildFacilityIconResolver(manifest);

    const viewState = {
      longitude: manifest.center[0],
      latitude: manifest.center[1],
      zoom: 6.0,
      minZoom: 7.1,
      maxZoom: 11.5,
      pitch: 90,
      bearing: 30
    };

    const layers = [
      new GeoJsonLayer({
        id: 'va-mask',
        data: boundaryFeatures,
        operation: 'mask',
        stroked: false,
        filled: true,
        getFillColor: [0, 0, 0, 255],
        pickable: false
      }),
      new TerrainLayer({
        id: 'terrain',
        elevationData: 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png',
        texture: 'https://basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png',
        bounds: terrainBounds,
        extensions: terrainExtensions,
        maskId: 'va-mask',
        elevationDecoder: {rScaler: 256, gScaler: 1, bScaler: 1 / 256, offset: -32768},
        strategy: 'no-overlap',
        minZoom: 0,
        maxZoom: 12,
        wireframe: false,
        color: [255, 255, 255],
        material: {ambient: 0.4, diffuse: 0.6, shininess: 12, specularColor: [120, 120, 120]},
        operation: 'terrain+draw',
        elevationScale: manifest.terrain_exaggeration || 1.8
      }),
      new GeoJsonLayer({
        id: 'boundary',
        data: boundaryFeatures,
        stroked: true,
        filled: true,
        getFillColor: [0, 0, 0, 0],
        getLineColor: COLORS.boundary,
        getLineWidth: 120,
        lineWidthMinPixels: 1,
        pickable: true
      }),
      new GeoJsonLayer({
        id: 'pipelines',
        data: `../${manifest.files.pipelines}`,
        stroked: true,
        filled: false,
        getLineColor: COLORS.pipelines,
        getLineWidth: 80,
        lineWidthMinPixels: 1,
        pickable: true
      }),
      new GeoJsonLayer({
        id: 'railroads',
        data: `../${manifest.files.railroads}`,
        stroked: true,
        filled: false,
        getLineColor: COLORS.railroads,
        getLineWidth: 50,
        lineWidthMinPixels: 1,
        pickable: true
      }),
      new GeoJsonLayer({
        id: 'primary-roads',
        data: `../${manifest.files.primary_roads}`,
        stroked: true,
        filled: false,
        getLineColor: COLORS.roads,
        getLineWidth: 95,
        lineWidthMinPixels: 1,
        pickable: true
      }),
      new GeoJsonLayer({
        id: 'incorporated-places',
        data: `../${manifest.files.incorporated_places}`,
        stroked: true,
        filled: false,
        getLineColor: COLORS.places,
        getLineWidth: 40,
        lineWidthMinPixels: 1,
        pickable: true
      }),
      new GeoJsonLayer({
        id: 'ports',
        data: `../${manifest.files.principal_ports}`,
        pointType: 'circle',
        filled: true,
        getPointRadius: 1200,
        pointRadiusMinPixels: 2,
        getFillColor: COLORS.ports,
        pickable: true
      }),
      new IconLayer({
        id: 'ghg-facilities',
        data: ghgFeatures,
        getPosition: (d) => d.geometry.coordinates,
        getIcon: getFacilityIcon,
        getSize: (d) => clamp(Math.sqrt(d.properties.radius_m || 600) * 1.1, 22, 56),
        sizeUnits: 'pixels',
        pickable: true
      })
    ];

    // Expose GHG data for the dashboard panel
    window.__ghgFeatures = ghgFeatures;
    window.dispatchEvent(new Event('ghg-data-ready'));

    new DeckGL({
      container: 'app',
      mapStyle: null,
      controller: true,
      pickingRadius: 8,
      initialViewState: viewState,
      onViewStateChange: ({viewState: next}) => clampToVirginia(next, manifest.bounds),
      layers,
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
        if (!object) return null;
        if (layer.id === 'ghg-facilities') {
          const props = object.properties || {};
          return {
            html: `<strong>${props.facility_name || 'Facility'}</strong><br/>Subparts: ${props.subparts || 'N/A'}<br/>GHG: ${formatTons(props.ghg_quantity_metric_tons_co2e)} tCO2e<br/><em style="color:#7a8a9e;font-size:10px">Click for emissions history</em>`
          };
        }
        if (layer.id === 'boundary') {
          return null;
        }
        return {text: LAYER_LABELS[layer.id] || layer.id};
      }
    });
  } catch (error) {
    document.getElementById('app').innerHTML = `<div style="color:#d8e2ee;padding:16px;">${error.message}</div>`;
    console.error(error);
  }
})();
