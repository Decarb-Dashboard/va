import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {buildIconIndex, summarizeSectors, filterFacilities, DEFAULT_FACILITY_TYPES} from '../web/facilities.js';

const readJson = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const features = readJson('../output/deck-data/ghg_2023.geojson').features;
const manifest = readJson('../output/deck-data/manifest.json');
const icons = buildIconIndex(manifest);

test('opening filter includes only the 35 stationary combustion facilities', () => {
  const visible = filterFacilities(features, new Set(DEFAULT_FACILITY_TYPES), icons);
  assert.equal(visible.length, 35);
  assert.ok(visible.every(feature => feature.properties.subparts === 'C'));
  assert.deepEqual(summarizeSectors(visible, icons).map(s => s.label), ['Stationary combustion']);
});

test('all, none, and combined selections preserve facility counts and emissions', () => {
  const sectors = summarizeSectors(features, icons);
  assert.equal(sectors.length, 17);
  assert.equal(filterFacilities(features, new Set(sectors.map(s => s.name)), icons).length, 134);
  assert.deepEqual(filterFacilities(features, new Set(), icons), []);
  assert.equal(sectors.reduce((sum, s) => sum + s.count, 0), features.length);
  assert.equal(sectors.reduce((sum, s) => sum + s.tons, 0),
    features.reduce((sum, f) => sum + f.properties.ghg_quantity_metric_tons_co2e, 0));
  const combined = filterFacilities(features, new Set(['icon_v2_C', 'icon_v2_D']), icons);
  assert.equal(combined.length, 60);
  assert.equal(summarizeSectors(combined, icons).length, 2);
});

test('map, filter, and chart colors stay attached to sectors when ranks change', () => {
  const sectors = summarizeSectors(features, icons);
  for (const sector of sectors) {
    const selected = filterFacilities(features, new Set([sector.name]), icons);
    const [single] = summarizeSectors(selected, icons);
    assert.equal(single.color, sector.color);
    assert.equal(single.label, sector.label);
    assert.deepEqual(icons.rgb(sector.name), sector.color.slice(1).match(/../g).map(c => parseInt(c, 16)));
    assert.equal(icons.icon(selected[0]).mask, true);
  }
  assert.equal(icons.color('icon_v2_C'), '#00d1ff');
  assert.equal(icons.color('icon_v2_D'), '#ffffff');
  assert.notEqual(icons.color('icon_v2_C_N'), icons.color('icon_v2_C'));
  assert.notEqual(icons.color('icon_v2_C_N'), icons.color('icon_v2_D'));
});

test('specific combined subparts use the existing map categories consistently', () => {
  assert.equal(icons.label(icons.iconName(' c, aa, tt ')), 'Pulp & paper');
  assert.equal(icons.label(icons.iconName('N,C')), 'Glass production');
  assert.equal(icons.label(icons.iconName('C,II')), 'Industrial wastewater');
  assert.equal(icons.label(icons.iconName('C,HH')), 'Landfill + combustion');
});

test('city labels use unique Census places with valid Virginia coordinates', () => {
  const cities = readJson('../web/major-cities.geojson');
  assert.equal(cities.features.length, 17);
  assert.equal(new Set(cities.features.map(f => f.properties.geoid)).size, 17);
  for (const city of cities.features) {
    const [longitude, latitude] = city.geometry.coordinates;
    assert.ok(longitude >= -83.7 && longitude <= -75.2);
    assert.ok(latitude >= 36.5 && latitude <= 39.5);
    assert.equal(city.geometry.type, 'Point');
  }
});
