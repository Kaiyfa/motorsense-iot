// Score chart (Chart.js, vendored) and SVG sparklines.
import * as fmt from './format.js';

const Chart = window.Chart;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function palette() {
  return {
    text: cssVar('--text'),
    muted: cssVar('--text-muted'),
    faint: cssVar('--text-faint'),
    grid: cssVar('--border'),
    alert: cssVar('--alert'),
    alertTint: cssVar('--alert-tint'),
    replay: cssVar('--replay'),
    surface: cssVar('--surface-2'),
  };
}

// Draws alert episodes as shaded bands behind the data.
const episodesPlugin = {
  id: 'msEpisodes',
  beforeDatasetsDraw(chart, _args, opts) {
    const { ctx, chartArea: area, scales: { x } } = chart;
    if (!opts.episodes || !opts.episodes.length) return;
    ctx.save();
    ctx.fillStyle = opts.fill;
    ctx.strokeStyle = opts.edge;
    ctx.lineWidth = 1;
    for (const ep of opts.episodes) {
      const x0 = Math.max(area.left, x.getPixelForValue(ep.start));
      const x1 = Math.min(area.right, x.getPixelForValue(ep.end));
      if (x1 <= area.left || x0 >= area.right || x1 <= x0) continue;
      ctx.fillRect(x0, area.top, x1 - x0, area.bottom - area.top);
      ctx.beginPath();
      ctx.moveTo(x0 + 0.5, area.top); ctx.lineTo(x0 + 0.5, area.bottom);
      ctx.stroke();
    }
    ctx.restore();
  },
};

// Dashed threshold line with its value, and an optional playhead.
const overlayPlugin = {
  id: 'msOverlay',
  afterDatasetsDraw(chart, _args, opts) {
    const { ctx, chartArea: area, scales: { x, y } } = chart;
    ctx.save();
    if (Number.isFinite(opts.threshold) && opts.threshold > 0) {
      const py = y.getPixelForValue(opts.threshold);
      if (py >= area.top && py <= area.bottom) {
        ctx.strokeStyle = opts.alert;
        ctx.setLineDash([6, 5]);
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(area.left, py); ctx.lineTo(area.right, py); ctx.stroke();
        ctx.setLineDash([]);
        const label = `Threshold ${fmt.score(opts.threshold)}`;
        ctx.font = '600 12px system-ui, -apple-system, "Segoe UI", sans-serif';
        const w = ctx.measureText(label).width + 12;
        const lx = area.right - w - 4;
        const ly = py - 22 < area.top ? py + 4 : py - 22;
        ctx.fillStyle = opts.surface;
        ctx.fillRect(lx, ly, w, 18);
        ctx.fillStyle = opts.alert;
        ctx.textBaseline = 'middle';
        ctx.fillText(label, lx + 6, ly + 9);
      }
    }
    if (Number.isFinite(opts.playhead)) {
      const px = x.getPixelForValue(opts.playhead);
      if (px >= area.left && px <= area.right) {
        ctx.strokeStyle = opts.replay;
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(px, area.top); ctx.lineTo(px, area.bottom); ctx.stroke();
      }
    }
    ctx.restore();
  },
};

// Ticks on round clock times (local time), at most maxCount of them.
const TICK_STEPS = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200].map((s) => s * 1000);
function timeTicks(min, max, maxCount) {
  const offset = new Date(min).getTimezoneOffset() * 60000;
  const step = TICK_STEPS.find((s) => (max - min) / s <= maxCount) || TICK_STEPS[TICK_STEPS.length - 1];
  const values = [];
  for (let v = Math.ceil((min - offset) / step) * step + offset; v <= max; v += step) values.push(v);
  return { step, values };
}

export function createScoreChart(canvas) {
  let colours = palette();
  let threshold = null;
  let tickStep = 60000;
  let maxTicks = 7;

  const chart = new Chart(canvas, {
    type: 'line',
    data: { datasets: [{ data: [], parsing: false, normalized: true, spanGaps: false,
      borderWidth: 1.6, pointRadius: 0, pointHoverRadius: 3, tension: 0 }] },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      scales: {
        x: {
          type: 'linear',
          ticks: { maxRotation: 0, callback: (v) => (tickStep < 60000 ? fmt.clock(v) : fmt.shortClock(v)) },
          afterBuildTicks: (axis) => {
            const { step, values } = timeTicks(axis.min, axis.max, maxTicks);
            tickStep = step;
            axis.ticks = values.map((value) => ({ value }));
          },
          grid: { display: false },
        },
        y: {
          type: 'logarithmic',
          title: { display: true, text: 'Score (log)' },
          ticks: {
            autoSkip: true,
            callback: (v) => {
              const exp = Math.log10(v);
              if (Math.abs(exp - Math.round(exp)) > 1e-9) return '';
              const e = Math.round(exp);
              return e >= 0 ? String(10 ** e) : (10 ** e).toFixed(-e);
            },
          },
        },
      },
      plugins: {
        legend: { display: false },
        decimation: { enabled: true, algorithm: 'min-max' },
        tooltip: {
          callbacks: {
            title: (items) => (items.length ? fmt.clock(items[0].parsed.x) : ''),
            label: (item) => {
              const v = item.parsed.y;
              const where = threshold === null ? '' : v > threshold ? ' (above threshold)' : ' (below threshold)';
              return `Score ${fmt.score(v)}${where}`;
            },
          },
        },
        msEpisodes: { episodes: [] },
        msOverlay: {},
      },
    },
    plugins: [episodesPlugin, overlayPlugin],
  });

  function applyColours() {
    const o = chart.options;
    const ds = chart.data.datasets[0];
    ds.borderColor = colours.muted;
    ds.segment = {
      borderColor: (ctx) => (threshold !== null && ctx.p1.parsed.y > threshold ? colours.alert : colours.muted),
    };
    for (const axis of [o.scales.x, o.scales.y]) {
      axis.ticks.color = colours.muted;
      axis.border = { color: colours.grid };
    }
    o.scales.y.grid = { color: colours.grid };
    o.scales.y.title.color = colours.muted;
    o.plugins.msEpisodes.fill = colours.alertTint;
    o.plugins.msEpisodes.edge = colours.alert;
    Object.assign(o.plugins.msOverlay, { alert: colours.alert, replay: colours.replay, surface: colours.surface });
    o.plugins.tooltip.backgroundColor = colours.surface;
    o.plugins.tooltip.titleColor = colours.text;
    o.plugins.tooltip.bodyColor = colours.text;
    o.plugins.tooltip.borderColor = colours.grid;
    o.plugins.tooltip.borderWidth = 1;
  }
  applyColours();

  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    colours = palette();
    applyColours();
    chart.update('none');
  });

  return {
    update({ points, threshold: t, episodes, playhead, xMin, xMax, narrow }) {
      threshold = Number.isFinite(t) ? t : null;
      chart.data.datasets[0].data = points;
      const o = chart.options;
      o.scales.x.min = xMin;
      o.scales.x.max = xMax;
      maxTicks = narrow ? 4 : 7;
      const values = points.map((p) => p.y).filter((v) => v !== null && v > 0);
      if (threshold !== null) values.push(threshold);
      if (values.length) {
        o.scales.y.min = 10 ** Math.floor(Math.log10(Math.min(...values)));
        o.scales.y.max = 10 ** Math.ceil(Math.log10(Math.max(...values) * 1.05));
      }
      o.plugins.msEpisodes.episodes = episodes || [];
      o.plugins.msOverlay.threshold = threshold;
      o.plugins.msOverlay.playhead = Number.isFinite(playhead) ? playhead : NaN;
      chart.update('none');
    },
  };
}

// Sparkline into an SVG path (viewBox 0 0 100 40). Gaps (null) break the line.
// minSpan keeps small sensor noise from being stretched to the full height.
export function sparkPath(series, xMin, xMax, minSpan = 0) {
  const values = series.map((p) => p.y).filter((v) => v !== null && Number.isFinite(v));
  if (!values.length || !(xMax > xMin)) return '';
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const span = Math.max(hi - lo, minSpan, 1e-9);
  const mid = (hi + lo) / 2;
  lo = mid - span / 2;
  hi = mid + span / 2;
  const pad = 3;
  let d = '';
  let pen = false;
  for (const p of series) {
    if (p.y === null || !Number.isFinite(p.y)) { pen = false; continue; }
    const x = ((p.x - xMin) / (xMax - xMin)) * 100;
    const y = pad + (1 - (p.y - lo) / (hi - lo)) * (40 - 2 * pad);
    d += `${pen ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`;
    pen = true;
  }
  return d;
}
