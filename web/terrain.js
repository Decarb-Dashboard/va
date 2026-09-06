// Builds the map's terrain surface from AWS Terrarium elevation tiles.
//
// The previous basemap raster (CARTO) now requires an API key and renders an
// "API KEY REQUIRED" watermark, so the surface is generated here instead: the
// same Terrarium tiles that drive the 3D mesh are decoded to elevation, shaded
// with a multi-directional hillshade and coloured with the hypsometric ramp
// used by the static PNG render (scripts/render.py).

const TILE_PX = 256;
const ELEVATION_TILE_URL =
  'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
const MAX_PARALLEL_TILES = 6;
const TILE_TIMEOUT_MS = 15000;

// Hypsometric ramp shared with the static render: coast -> peaks.
const RAMP_STOPS = [0.0, 0.15, 0.35, 0.65, 1.0];
const RAMP_COLORS = [
  [0.42, 0.52, 0.6],
  [0.48, 0.58, 0.58],
  [0.55, 0.62, 0.5],
  [0.68, 0.58, 0.45],
  [0.82, 0.74, 0.62]
];

const HILLSHADE_AZIMUTHS = [315, 270, 225, 360];
const HILLSHADE_WEIGHTS = [0.4, 0.25, 0.2, 0.15];
const SUN_ALTITUDE = Math.PI / 4;

const lonToTileX = (lon, zoom) => ((lon + 180) / 360) * 2 ** zoom;

const latToTileY = (lat, zoom) => {
  const radians = (lat * Math.PI) / 180;
  return ((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2) * 2 ** zoom;
};

const tileXToLon = (x, zoom) => (x / 2 ** zoom) * 360 - 180;

const tileYToLat = (y, zoom) => {
  const n = Math.PI - (2 * Math.PI * y) / 2 ** zoom;
  return (180 / Math.PI) * Math.atan(Math.sinh(n));
};

function interpolateRamp(t, channel) {
  for (let i = 1; i < RAMP_STOPS.length; i++) {
    if (t <= RAMP_STOPS[i]) {
      const span = RAMP_STOPS[i] - RAMP_STOPS[i - 1];
      const frac = span > 0 ? (t - RAMP_STOPS[i - 1]) / span : 0;
      return RAMP_COLORS[i - 1][channel] + frac * (RAMP_COLORS[i][channel] - RAMP_COLORS[i - 1][channel]);
    }
  }
  return RAMP_COLORS[RAMP_COLORS.length - 1][channel];
}

async function fetchTileElevation(x, y, zoom, timeoutMs = TILE_TIMEOUT_MS) {
  const url = ELEVATION_TILE_URL.replace('{z}', zoom).replace('{x}', x).replace('{y}', y);
  const controller = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let response;
  try {
    response = await fetch(url, {signal: controller?.signal});
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (!response.ok) {
    throw new Error(`Elevation tile ${zoom}/${x}/${y}: ${response.status}`);
  }
  // Decoding through a blob keeps the canvas untainted regardless of CORS mode.
  const bitmap = await createImageBitmap(await response.blob());
  const canvas = document.createElement('canvas');
  canvas.width = TILE_PX;
  canvas.height = TILE_PX;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  ctx.drawImage(bitmap, 0, 0, TILE_PX, TILE_PX);
  bitmap.close?.();
  const {data} = ctx.getImageData(0, 0, TILE_PX, TILE_PX);

  const elevation = new Float32Array(TILE_PX * TILE_PX);
  for (let i = 0, p = 0; i < elevation.length; i++, p += 4) {
    elevation[i] = data[p] * 256 + data[p + 1] + data[p + 2] / 256 - 32768;
  }
  return elevation;
}

async function runWithConcurrency(items, limit, worker) {
  let cursor = 0;
  const runners = Array.from({length: Math.min(limit, items.length)}, async () => {
    while (cursor < items.length) {
      const index = cursor++;
      await worker(items[index]);
    }
  });
  await Promise.all(runners);
}

function computeHillshade(elevation, width, height, cellSize, verticalExaggeration) {
  const shade = new Float32Array(width * height);
  const scaled = new Float32Array(elevation.length);
  for (let i = 0; i < elevation.length; i++) {
    scaled[i] = Number.isFinite(elevation[i]) ? elevation[i] * verticalExaggeration : 0;
  }

  for (let row = 0; row < height; row++) {
    const rowUp = Math.max(row - 1, 0);
    const rowDown = Math.min(row + 1, height - 1);
    for (let col = 0; col < width; col++) {
      const colLeft = Math.max(col - 1, 0);
      const colRight = Math.min(col + 1, width - 1);

      const dzdx = (scaled[row * width + colRight] - scaled[row * width + colLeft]) /
        ((colRight - colLeft) * cellSize);
      const dzdy = (scaled[rowDown * width + col] - scaled[rowUp * width + col]) /
        ((rowDown - rowUp) * cellSize);

      const slope = Math.atan(Math.sqrt(dzdx * dzdx + dzdy * dzdy));
      const aspect = Math.atan2(-dzdx, dzdy);

      let combined = 0;
      for (let i = 0; i < HILLSHADE_AZIMUTHS.length; i++) {
        const azimuth = (HILLSHADE_AZIMUTHS[i] * Math.PI) / 180;
        const value =
          Math.sin(SUN_ALTITUDE) * Math.cos(slope) +
          Math.cos(SUN_ALTITUDE) * Math.sin(slope) * Math.cos(azimuth - aspect);
        combined += HILLSHADE_WEIGHTS[i] * Math.min(Math.max(value, 0), 1);
      }
      shade[row * width + col] = Math.min(Math.max(combined, 0), 1);
    }
  }
  return shade;
}

function clipToBoundary(canvas, boundaryFeatures, mosaic, zoom) {
  const ctx = canvas.getContext('2d');
  const path = new Path2D();

  const addRing = (ring) => {
    ring.forEach(([lon, lat], index) => {
      const x = (lonToTileX(lon, zoom) - mosaic.xMin) * TILE_PX;
      const y = (latToTileY(lat, zoom) - mosaic.yMin) * TILE_PX;
      if (index === 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    });
    path.closePath();
  };

  boundaryFeatures.forEach((feature) => {
    const geometry = feature.geometry || {};
    if (geometry.type === 'Polygon') {
      geometry.coordinates.forEach(addRing);
    } else if (geometry.type === 'MultiPolygon') {
      geometry.coordinates.forEach((polygon) => polygon.forEach(addRing));
    }
  });

  ctx.globalCompositeOperation = 'destination-in';
  ctx.fillStyle = '#fff';
  ctx.fill(path, 'evenodd');
  ctx.globalCompositeOperation = 'source-over';
}

/**
 * Build a shaded-relief image covering `bounds`, cut out to the state boundary.
 *
 * Returns `{image, bounds}` ready for a deck.gl BitmapLayer, or null when the
 * elevation tiles cannot be fetched (the map then falls back to the flat-shaded
 * terrain mesh).
 */
export async function buildTerrainSurface({
  bounds,
  zoom = 8,
  boundaryFeatures = [],
  verticalExaggeration = 1.8,
  onTileSettled = () => {}
}) {
  const [west, south, east, north] = bounds;
  const xMin = Math.floor(lonToTileX(west, zoom));
  const xMax = Math.floor(lonToTileX(east, zoom));
  const yMin = Math.floor(latToTileY(north, zoom));
  const yMax = Math.floor(latToTileY(south, zoom));

  const tilesWide = xMax - xMin + 1;
  const tilesHigh = yMax - yMin + 1;
  const width = tilesWide * TILE_PX;
  const height = tilesHigh * TILE_PX;

  const elevation = new Float32Array(width * height);
  const tiles = [];
  for (let ty = yMin; ty <= yMax; ty++) {
    for (let tx = xMin; tx <= xMax; tx++) {
      tiles.push({tx, ty});
    }
  }

  let loaded = 0;
  await runWithConcurrency(tiles, MAX_PARALLEL_TILES, async ({tx, ty}) => {
    try {
      const tile = await fetchTileElevation(tx, ty, zoom);
      const originRow = (ty - yMin) * TILE_PX;
      const originCol = (tx - xMin) * TILE_PX;
      for (let row = 0; row < TILE_PX; row++) {
        elevation.set(
          tile.subarray(row * TILE_PX, (row + 1) * TILE_PX),
          (originRow + row) * width + originCol
        );
      }
      loaded++;
    } catch (error) {
      console.warn(error);
    } finally {
      onTileSettled();
    }
  });

  if (loaded === 0) {
    return null;
  }

  const centerLat = (north + south) / 2;
  const cellSize =
    (156543.03392 * Math.cos((centerLat * Math.PI) / 180)) / 2 ** zoom;
  const hillshade = computeHillshade(elevation, width, height, cellSize, verticalExaggeration);

  let maxElevation = 1;
  for (let i = 0; i < elevation.length; i++) {
    if (elevation[i] > maxElevation) maxElevation = elevation[i];
  }

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  const imageData = ctx.createImageData(width, height);
  const pixels = imageData.data;

  for (let i = 0, p = 0; i < elevation.length; i++, p += 4) {
    const normalized = Math.min(Math.max(elevation[i] / maxElevation, 0), 1);
    const shade = 0.2 + hillshade[i] * 0.8;
    pixels[p] = interpolateRamp(normalized, 0) * shade * 255;
    pixels[p + 1] = interpolateRamp(normalized, 1) * shade * 255;
    pixels[p + 2] = interpolateRamp(normalized, 2) * shade * 255;
    // Lowlands stay translucent so the dark ground reads through; ridges are
    // close to opaque, which is what gives the relief its depth.
    const relief = Math.min(normalized * 1.3, 1);
    pixels[p + 3] = (0.5 + relief * 0.45) * 255;
  }
  ctx.putImageData(imageData, 0, 0);

  const mosaic = {xMin, yMin};
  if (boundaryFeatures.length > 0) {
    clipToBoundary(canvas, boundaryFeatures, mosaic, zoom);
  }

  const image = typeof createImageBitmap === 'function'
    ? await createImageBitmap(canvas)
    : canvas;

  return {
    image,
    tileCount: tiles.length,
    bounds: [
      tileXToLon(xMin, zoom),
      tileYToLat(yMax + 1, zoom),
      tileXToLon(xMax + 1, zoom),
      tileYToLat(yMin, zoom)
    ]
  };
}

export const terrainTileCount = (bounds, zoom) => {
  const [west, south, east, north] = bounds;
  const tilesWide = Math.floor(lonToTileX(east, zoom)) - Math.floor(lonToTileX(west, zoom)) + 1;
  const tilesHigh = Math.floor(latToTileY(south, zoom)) - Math.floor(latToTileY(north, zoom)) + 1;
  return tilesWide * tilesHigh;
};
