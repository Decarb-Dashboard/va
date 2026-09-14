// One category mapping for map icons, filters, charts, and facility details.
// Labels and subpart combinations come from the existing icon manifest.
export const DEFAULT_FACILITY_TYPES = ['icon_v2_C'];
export const FACILITY_ICON_SIZE = 28;

const ICON_COLORS = {
  icon_v2_C: '#00d1ff',
  icon_v2_D: '#ffffff',
  icon_v2_C_HH: '#ff007a',
  icon_v2_HH: '#ffb200',
  icon_v2_TT: '#ff00dc',
  icon_v2_NN_W: '#8cff00',
  icon_v2_C_W: '#3c78ff',
  icon_v2_AA_C: '#00ff50',
  icon_v2_C_II: '#ffe600',
  icon_v2_C_Q: '#00ffaa',
  icon_v2_C_S: '#ff3c3c',
  icon_v2_C_N: '#e6adff',
  icon_v2_C_I: '#b978ff',
  icon_v2_G_PP: '#00ffd5',
  icon_v2_H: '#ffa64d',
  icon_v2_FF: '#9aa7b4',
  icon_v2_DD: '#ff5a00'
};

export function normalizeSubparts(subparts) {
  return String(subparts || '').split(',')
    .map(part => part.trim().toUpperCase()).filter(Boolean).sort().join(',');
}

export function buildIconIndex(manifest) {
  const config = manifest.icons || {};
  const bySubparts = Object.fromEntries(Object.entries(config.by_subparts || {})
    .map(([parts, name]) => [normalizeSubparts(parts), String(name)]));
  const iconName = subparts => bySubparts[normalizeSubparts(subparts)] || config.default || 'icon_v2_C';
  const url = name => `../${config.base_dir || 'geo-icons'}/${name.includes('.') ? name : `${name}.png`}`;
  const color = name => ICON_COLORS[name] || '#8fa6bd';

  return {
    iconName,
    url,
    color,
    label: name => config.labels?.[name] || 'Other reporting facility',
    rgb: name => color(name).slice(1).match(/../g).map(channel => parseInt(channel, 16)),
    icon: feature => ({
      url: url(iconName(feature.properties?.subparts)),
      width: 128,
      height: 128,
      anchorY: 128,
      mask: true
    })
  };
}

export function summarizeSectors(features, iconIndex) {
  const groups = new Map();
  features.forEach(feature => {
    const name = iconIndex.iconName(feature.properties?.subparts);
    const entry = groups.get(name) || {
      name,
      url: iconIndex.url(name),
      label: iconIndex.label(name),
      color: iconIndex.color(name),
      count: 0,
      tons: 0
    };
    entry.count += 1;
    entry.tons += Number(feature.properties?.ghg_quantity_metric_tons_co2e) || 0;
    groups.set(name, entry);
  });
  return [...groups.values()].sort((a, b) => b.tons - a.tons);
}

export function filterFacilities(features, selectedTypes, iconIndex) {
  return features.filter(feature => selectedTypes.has(iconIndex.iconName(feature.properties?.subparts)));
}
