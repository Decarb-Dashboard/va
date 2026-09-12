// Dashboard panel: legend, summary stats, and charts
// Waits for map.js to expose GHG feature data via window.__ghgFeatures

// Sector labels derived from EPA GHGRP subpart codes
const SECTOR_MAP = {
  C: 'General Combustion',
  D: 'Power Plants',
  HH: 'Landfills',
  FF: 'Coal Mines',
  W: 'Natural Gas Distribution',
  NN: 'Natural Gas Distribution',
  Q: 'Steel / Iron',
  PP: 'Chemical Mfg',
  G: 'Chemical Mfg',
  TT: 'Industrial Processes',
  II: 'Industrial Processes',
  H: 'Cement',
  AA: 'Petroleum Refining',
  Y: 'Petroleum Refining',
  BB: 'Silicon Carbide',
  S: 'Lime Manufacturing',
  X: 'Petrochemical',
  DD: 'Electrical Equipment',
  OO: 'Data Centers / HVAC'
};

const SECTOR_COLORS = [
  '#4dd0e1', '#9D00FF', '#ffd27a', '#ff6b6b',
  '#69db7c', '#b197fc', '#ffa94d', '#74c0fc',
  '#e599f7', '#8fa6bd', '#f783ac', '#a9e34b'
];

function classifyFacility(subparts) {
  const parts = String(subparts || '').split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
  // Pick the most specific subpart (not C which is generic combustion)
  const specific = parts.find(p => p !== 'C') || parts[0] || 'C';
  return SECTOR_MAP[specific] || 'Other';
}

const compactTons = (tons) => {
  const value = Number(tons) || 0;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `${Math.round(value / 1e3)}k`;
  return String(Math.round(value));
};

function legendRow(swatch, label, trailing) {
  const row = document.createElement('div');
  row.className = 'legend-item';
  row.appendChild(swatch);

  const text = document.createElement('span');
  text.textContent = label;
  row.appendChild(text);

  if (trailing) {
    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = trailing;
    row.appendChild(count);
  }
  return row;
}

function legendSection(title) {
  const section = document.createElement('div');
  section.className = 'legend-section';
  const heading = document.createElement('h3');
  heading.textContent = title;
  section.appendChild(heading);
  const list = document.createElement('div');
  list.className = 'legend-list';
  section.appendChild(list);
  return {section, list};
}

/**
 * Render the map legend into the overlay chip. Everything the map draws is
 * listed: facility icon categories present in the data, the size encoding and
 * the reference layers.
 */
function buildLegend(legend) {
  const host = document.getElementById('legend-inner');
  if (!host || !legend) return;
  host.innerHTML = '';

  const icons = legend.icons || [];
  const facilities = legendSection(`Facilities (${icons.reduce((n, i) => n + i.count, 0)})`);
  if (icons.length > 10) {
    facilities.list.classList.add('two-col');
  }
  icons.forEach((entry) => {
    const swatch = document.createElement('img');
    swatch.className = 'legend-swatch icon';
    swatch.src = entry.url;
    swatch.alt = '';
    facilities.list.appendChild(legendRow(swatch, entry.label, `${entry.count}`));
  });
  host.appendChild(facilities.section);

  const scale = legend.sizeScale;
  if (scale) {
    const sizing = legendSection('Icon size');
    const row = document.createElement('div');
    row.className = 'legend-size-scale';
    const stops = [
      {tons: scale.minTons, frac: 0},
      {tons: (scale.maxTons || 0) / 8, frac: Math.sqrt(1 / 8)},
      {tons: scale.maxTons, frac: 1}
    ];
    stops.forEach((stop) => {
      const wrap = document.createElement('div');
      wrap.style.textAlign = 'center';
      const dot = document.createElement('div');
      const px = Math.round((scale.minPx + stop.frac * (scale.maxPx - scale.minPx)) * 0.42);
      dot.className = 'dot';
      dot.style.width = `${px}px`;
      dot.style.height = `${px}px`;
      dot.style.margin = '0 auto 3px';
      const label = document.createElement('div');
      label.style.fontSize = '9px';
      label.style.color = '#6d7f95';
      label.textContent = compactTons(stop.tons);
      wrap.appendChild(dot);
      wrap.appendChild(label);
      row.appendChild(wrap);
    });
    sizing.list.appendChild(row);
    const note = document.createElement('div');
    note.className = 'legend-size-note';
    note.textContent = 'Icon area scales with reported tCO2e.';
    sizing.list.appendChild(note);
    host.appendChild(sizing.section);
  }

  const layers = legendSection('Reference layers');
  (legend.layers || []).forEach((item) => {
    const swatch = document.createElement('span');
    if (item.type === 'relief') {
      swatch.className = 'legend-swatch relief';
    } else if (item.type === 'circle') {
      swatch.className = 'legend-swatch circle';
      swatch.style.background = item.color;
    } else {
      swatch.className = 'legend-swatch' + (item.glow ? ' glow' : '');
      swatch.style.background = item.color;
    }
    layers.list.appendChild(legendRow(swatch, item.label));
  });
  host.appendChild(layers.section);
}

// The legend opens on hover; a click pins it open for touch input.
const legendEl = document.getElementById('legend');
const legendToggle = document.getElementById('legend-toggle');
if (legendEl && legendToggle) {
  legendToggle.addEventListener('click', () => {
    const open = legendEl.classList.toggle('open');
    legendToggle.setAttribute('aria-expanded', String(open));
  });
}

function populateStats(features) {
  const count = features.length;
  const totalEmissions = features.reduce((sum, f) => sum + (f.properties.ghg_quantity_metric_tons_co2e || 0), 0);
  const sectors = new Set(features.map(f => classifyFacility(f.properties.subparts)));

  document.getElementById('stat-facilities').textContent = count;
  document.getElementById('stat-emissions').textContent = (totalEmissions / 1e6).toFixed(1);
  document.getElementById('stat-sectors').textContent = sectors.size;
}

const TOP_EMITTER_COUNT = 5;

function buildTopEmittersChart(features) {
  const sorted = [...features].sort((a, b) =>
    (b.properties.ghg_quantity_metric_tons_co2e || 0) - (a.properties.ghg_quantity_metric_tons_co2e || 0)
  );
  const top = sorted.slice(0, TOP_EMITTER_COUNT);
  const labels = top.map(f => {
    const name = f.properties.facility_name || 'Unknown';
    return name.length > 22 ? name.slice(0, 20) + '...' : name;
  });
  const data = top.map(f => (f.properties.ghg_quantity_metric_tons_co2e || 0) / 1000);

  new Chart(document.getElementById('chart-top-emitters'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: 'rgba(77, 208, 225, 0.7)',
        borderColor: 'rgba(77, 208, 225, 1)',
        borderWidth: 1,
        borderRadius: 3
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {display: false},
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.raw.toLocaleString()} kt CO2e`
          }
        }
      },
      scales: {
        x: {
          grid: {color: 'rgba(162,186,212,0.08)'},
          ticks: {color: '#7a8a9e', font: {size: 10}, callback: v => v.toLocaleString()},
          title: {display: true, text: 'kt CO2e', color: '#7a8a9e', font: {size: 10}}
        },
        y: {
          grid: {display: false},
          ticks: {color: '#b0bfcf', font: {size: 10}}
        }
      }
    }
  });
}

function buildSectorChart(features) {
  const sectorTotals = {};
  features.forEach(f => {
    const sector = classifyFacility(f.properties.subparts);
    sectorTotals[sector] = (sectorTotals[sector] || 0) + (f.properties.ghg_quantity_metric_tons_co2e || 0);
  });

  const sorted = Object.entries(sectorTotals).sort((a, b) => b[1] - a[1]);
  const labels = sorted.map(([s]) => s);
  const data = sorted.map(([, v]) => v / 1000);

  new Chart(document.getElementById('chart-sectors'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: SECTOR_COLORS.slice(0, labels.length),
        borderColor: '#101520',
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '55%',
      plugins: {
        legend: {
          position: 'right',
          labels: {
            color: '#b0bfcf',
            font: {size: 10},
            boxWidth: 12,
            padding: 8
          }
        },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.label}: ${ctx.raw.toLocaleString()} kt CO2e`
          }
        }
      }
    }
  });
}

// --- Facility timeline modal ---

// Parse CSV text into array of objects
function parseCSV(text) {
  const lines = text.split('\n');
  const headers = lines[0].split(',').map(h => h.trim());
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    // Handle commas inside quoted fields
    const values = [];
    let current = '';
    let inQuotes = false;
    for (let c = 0; c < line.length; c++) {
      if (line[c] === '"') {
        inQuotes = !inQuotes;
      } else if (line[c] === ',' && !inQuotes) {
        values.push(current.trim());
        current = '';
      } else {
        current += line[c];
      }
    }
    values.push(current.trim());
    const obj = {};
    headers.forEach((h, idx) => { obj[h] = values[idx] || ''; });
    rows.push(obj);
  }
  return rows;
}

let allYearsData = null;
let timelineChart = null;

async function loadAllYearsData() {
  const resp = await fetch('../ghg-data/flight_cleaned_va_all_years.csv');
  const text = await resp.text();
  allYearsData = parseCSV(text);
}

function openFacilityModal(facilityName, subparts) {
  if (!allYearsData) return;

  const modal = document.getElementById('facility-modal');
  const titleEl = document.getElementById('modal-title');
  const subtitleEl = document.getElementById('modal-subtitle');
  const statsEl = document.getElementById('modal-stats');

  // Find all records for this facility across years
  const records = allYearsData
    .filter(r => r.facility_name === facilityName)
    .map(r => ({
      year: parseInt(r.reporting_year, 10),
      ghg: parseFloat(r.ghg_quantity_metric_tons_co2e) || 0
    }))
    .sort((a, b) => a.year - b.year);

  if (records.length === 0) {
    // Try partial match if exact match fails
    const nameLower = facilityName.toLowerCase();
    const partial = allYearsData
      .filter(r => r.facility_name && r.facility_name.toLowerCase().includes(nameLower.split(' ')[0]))
      .map(r => ({
        year: parseInt(r.reporting_year, 10),
        ghg: parseFloat(r.ghg_quantity_metric_tons_co2e) || 0,
        name: r.facility_name
      }));
    if (partial.length === 0) return;
  }

  titleEl.textContent = facilityName;
  subtitleEl.textContent = `Sector: ${classifyFacility(subparts)} · Subparts: ${subparts || 'N/A'}`;

  // Compute stats
  const years = records.map(r => r.year);
  const ghgValues = records.map(r => r.ghg);
  const latest = ghgValues[ghgValues.length - 1] || 0;
  const peak = Math.max(...ghgValues);
  const peakYear = years[ghgValues.indexOf(peak)];
  const first = ghgValues[0] || 0;
  const changePct = first > 0 ? (((latest - first) / first) * 100).toFixed(1) : 'N/A';

  statsEl.innerHTML = `
    <div class="modal-stat">Latest: <strong>${(latest / 1000).toLocaleString(undefined, {maximumFractionDigits: 1})} kt CO2e</strong></div>
    <div class="modal-stat">Peak: <strong>${(peak / 1000).toLocaleString(undefined, {maximumFractionDigits: 1})} kt</strong> (${peakYear})</div>
    <div class="modal-stat">Change: <strong>${changePct === 'N/A' ? changePct : changePct + '%'}</strong> (${years[0]}–${years[years.length - 1]})</div>
  `;

  // Destroy previous chart
  if (timelineChart) {
    timelineChart.destroy();
    timelineChart = null;
  }

  const canvas = document.getElementById('chart-facility-timeline');
  timelineChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: years,
      datasets: [{
        data: ghgValues.map(v => v / 1000),
        borderColor: '#4dd0e1',
        backgroundColor: 'rgba(77, 208, 225, 0.1)',
        borderWidth: 2,
        pointRadius: 4,
        pointBackgroundColor: '#4dd0e1',
        pointBorderColor: '#141a24',
        pointBorderWidth: 2,
        fill: true,
        tension: 0.3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.raw.toLocaleString(undefined, {maximumFractionDigits: 1})} kt CO2e`
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(162,186,212,0.08)' },
          ticks: { color: '#7a8a9e', font: { size: 11 } },
          title: { display: true, text: 'Year', color: '#7a8a9e', font: { size: 10 } }
        },
        y: {
          grid: { color: 'rgba(162,186,212,0.08)' },
          ticks: { color: '#7a8a9e', font: { size: 10 }, callback: v => v.toLocaleString() },
          title: { display: true, text: 'kt CO2e', color: '#7a8a9e', font: { size: 10 } }
        }
      }
    }
  });

  modal.style.display = 'flex';
  requestAnimationFrame(() => modal.classList.add('visible'));
}

function closeFacilityModal() {
  const modal = document.getElementById('facility-modal');
  modal.classList.remove('visible');
  setTimeout(() => { modal.style.display = 'none'; }, 200);
}

// Modal close handlers
document.getElementById('modal-close').addEventListener('click', closeFacilityModal);
document.getElementById('facility-modal').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) closeFacilityModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeFacilityModal();
});

// Expose click handler for map.js
window.__onFacilityClick = openFacilityModal;

function init(features) {
  buildLegend(window.__ghgLegend);
  populateStats(features);
  buildTopEmittersChart(features);
  buildSectorChart(features);
  loadAllYearsData();
}

// Wait for map.js to signal data is ready
if (window.__ghgFeatures) {
  init(window.__ghgFeatures);
} else {
  window.addEventListener('ghg-data-ready', () => init(window.__ghgFeatures));
}
