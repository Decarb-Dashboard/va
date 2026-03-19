// Dashboard panel: legend, summary stats, and charts
// Waits for map.js to expose GHG feature data via window.__ghgFeatures

const LAYER_LEGEND = [
  {label: 'State boundary', color: 'rgba(143,166,189,0.86)', type: 'line'},
  {label: 'Natural gas pipelines', color: 'rgba(157,0,255,0.47)', type: 'line'},
  {label: 'Railroads', color: 'rgba(215,221,230,0.36)', type: 'line'},
  {label: 'Primary roads', color: 'rgba(255,210,122,0.47)', type: 'line'},
  {label: 'Incorporated places', color: 'rgba(154,167,180,0.24)', type: 'line'},
  {label: 'Principal ports', color: 'rgba(77,208,225,0.63)', type: 'circle'},
  {label: 'GHG facilities', color: null, type: 'icon'}
];

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

function buildLegend() {
  const list = document.getElementById('legend-list');
  if (!list) return;
  LAYER_LEGEND.forEach(item => {
    const row = document.createElement('div');
    row.className = 'legend-item';

    const swatch = document.createElement('span');
    swatch.className = 'legend-swatch' + (item.type === 'circle' ? ' circle' : '') + (item.type === 'icon' ? ' icon' : '');
    if (item.type === 'icon') {
      swatch.style.backgroundImage = 'url(../geo-icons/small/icon_v2_C.png)';
    } else {
      swatch.style.background = item.color;
    }

    const label = document.createElement('span');
    label.textContent = item.label;

    row.appendChild(swatch);
    row.appendChild(label);
    list.appendChild(row);
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

function buildTopEmittersChart(features) {
  const sorted = [...features].sort((a, b) =>
    (b.properties.ghg_quantity_metric_tons_co2e || 0) - (a.properties.ghg_quantity_metric_tons_co2e || 0)
  );
  const top10 = sorted.slice(0, 10);
  const labels = top10.map(f => {
    const name = f.properties.facility_name || 'Unknown';
    return name.length > 22 ? name.slice(0, 20) + '...' : name;
  });
  const data = top10.map(f => (f.properties.ghg_quantity_metric_tons_co2e || 0) / 1000);

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

function buildDistributionChart(features) {
  const bins = [
    {label: '<10k', min: 0, max: 10000},
    {label: '10k-50k', min: 10000, max: 50000},
    {label: '50k-100k', min: 50000, max: 100000},
    {label: '100k-500k', min: 100000, max: 500000},
    {label: '500k-1M', min: 500000, max: 1000000},
    {label: '>1M', min: 1000000, max: Infinity}
  ];

  const counts = bins.map(bin =>
    features.filter(f => {
      const v = f.properties.ghg_quantity_metric_tons_co2e || 0;
      return v >= bin.min && v < bin.max;
    }).length
  );

  new Chart(document.getElementById('chart-distribution'), {
    type: 'bar',
    data: {
      labels: bins.map(b => b.label),
      datasets: [{
        data: counts,
        backgroundColor: 'rgba(157, 0, 255, 0.5)',
        borderColor: 'rgba(157, 0, 255, 0.9)',
        borderWidth: 1,
        borderRadius: 3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {display: false},
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.raw} facilities`
          }
        }
      },
      scales: {
        x: {
          grid: {display: false},
          ticks: {color: '#7a8a9e', font: {size: 10}},
          title: {display: true, text: 'tCO2e / year', color: '#7a8a9e', font: {size: 10}}
        },
        y: {
          grid: {color: 'rgba(162,186,212,0.08)'},
          ticks: {color: '#7a8a9e', font: {size: 10}, stepSize: 1},
          title: {display: true, text: 'Count', color: '#7a8a9e', font: {size: 10}}
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
  buildLegend();
  populateStats(features);
  buildTopEmittersChart(features);
  buildSectorChart(features);
  buildDistributionChart(features);
  loadAllYearsData();
}

// Wait for map.js to signal data is ready
if (window.__ghgFeatures) {
  init(window.__ghgFeatures);
} else {
  window.addEventListener('ghg-data-ready', () => init(window.__ghgFeatures));
}
