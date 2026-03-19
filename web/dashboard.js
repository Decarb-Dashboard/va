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

function init(features) {
  buildLegend();
  populateStats(features);
  buildTopEmittersChart(features);
  buildSectorChart(features);
  buildDistributionChart(features);
}

// Wait for map.js to signal data is ready
if (window.__ghgFeatures) {
  init(window.__ghgFeatures);
} else {
  window.addEventListener('ghg-data-ready', () => init(window.__ghgFeatures));
}
