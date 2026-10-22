// Score chart (Chart.js, vendored) and SVG sparklines.
import * as fmt from 'ms/format.js';

const Chart = window.Chart;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function palette() {
  return {
    text: cssVar('--text'),
    muted: cssVar('--text-muted'),
    grid: cssVar('--border'),
    alert: cssVar('--alert'),
    alertTint: cssVar('--alert-tint'),
    replay: cssVar('--replay'),
    surface: cssVar('--surface-2'),
  };
}

const LABEL_FONT = '600 12px system-ui, -apple-system, "Segoe UI", sans-serif';

function drawLabel(ctx, text, x, y, colour, background, area) {
  ctx.font = LABEL_FONT;
  const w = ctx.measureText(text).width + 12;
  const lx = Math.min(Math.max(x, area.left), area.right - w);
  ctx.fillStyle = background;
  ctx.fillRect(lx, y, w, 18);
  ctx.fillStyle = colour;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, lx + 6, y + 9);
}

// Alert episodes as shaded bands behind the data.
const episodesPlugin = {
  id: 'msEpisodes',
  beforeDatasetsDraw(chart, _args, opts) {
    const { ctx, chartArea: area, scales: { x } } = chart;
    if (!opts.episodes || !opts.episodes.length) return;
    ctx.save();
    ctx.fillStyle = opts.fill;
    for (const ep of opts.episodes) {
      const x0 = Math.max(area.left, x.getPixelForValue(ep.start));
      const x1 = Math.min(area.right, x.getPixelForValue(ep.end));
      if (x1 > x0) ctx.fillRect(x0, area.top, x1 - x0, area.bottom - area.top);
    }
    ctx.restore();
  },
};

// Threshold line with its value, labelled alert-start markers and the replay playhead.
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
        ctx.font = LABEL_FONT;
        const w = ctx.measureText(label).width + 12;
        drawLabel(ctx, label, area.right - w - 4, py - 22 < area.top ? py + 4 : py - 22, opts.alert, opts.surface, area);
      }
    }
    // alert starts: a solid line and a label, stacked when they would overlap
    let row = 0;
    let lastRight = -Infinity;
    for (const start of opts.alertStarts || []) {
      const px = x.getPixelForValue(start);
      if (px < area.left || px > area.right) continue;
      ctx.strokeStyle = opts.alert;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(px + 0.5, area.top); ctx.lineTo(px + 0.5, area.bottom); ctx.stroke();
      const text = `Alert started ${fmt.clock(start)}`;
      ctx.font = LABEL_FONT;
      const w = ctx.measureText(text).width + 12;
      const lx = px + 4 + w > area.right ? px - 4 - w : px + 4;
      row = lx < lastRight ? row + 1 : 0;
      drawLabel(ctx, text, lx, area.top + 4 + row * 20, opts.alert, opts.surface, area);
      lastRight = lx + w;
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

// Reports the plot area so the state strip and the empty-state overlay can align with it.
const layoutPlugin = {
  id: 'msLayout',
  afterLayout(chart, _args, opts) {
    if (opts.onLayout) opts.onLayout({ ...chart.chartArea }, chart.width);
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

export function createScoreChart(canvas, onLayout) {
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
        msLayout: { onLayout },
      },
    },
    plugins: [episodesPlugin, overlayPlugin, layoutPlugin],
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
    Object.assign(o.plugins.msOverlay, { alert: colours.alert, replay: colours.replay, surface: colours.surface });
    Object.assign(o.plugins.tooltip, {
      backgroundColor: colours.surface, titleColor: colours.text, bodyColor: colours.text,
      borderColor: colours.grid, borderWidth: 1,
    });
  }
  applyColours();

  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    colours = palette();
    applyColours();
    chart.update('none');
  });

  return {
    update({ points, threshold: t, episodes, alertStarts, playhead, xMin, xMax, narrow }) {
      threshold = Number.isFinite(t) ? t : null;
      chart.data.datasets[0].data = points;
      const o = chart.options;
      o.scales.x.min = xMin;
      o.scales.x.max = xMax;
      maxTicks = narrow ? 4 : 7;
      const values = points.map((p) => p.y).filter((v) => v !== null && v > 0);
      if (threshold !== null) values.push(threshold);
      if (!values.length) values.push(0.1, 10);
      o.scales.y.min = 10 ** Math.floor(Math.log10(Math.min(...values)));
      o.scales.y.max = 10 ** Math.ceil(Math.log10(Math.max(...values) * 1.05));
      o.plugins.msEpisodes.episodes = episodes || [];
      o.plugins.msOverlay.threshold = threshold;
      o.plugins.msOverlay.alertStarts = alertStarts || [];
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

// Trend chart for one sensor: linear axis, the stored values (reduced for drawing),
// with an optional playhead.
export function createSeriesChart(canvas, { unit, digits }) {
  let colours = palette();
  let tickStep = 60000;
  let maxTicks = 6;
  const chart = new Chart(canvas, {
    type: 'line',
    data: { datasets: [{ data: [], parsing: false, normalized: true, spanGaps: false,
      borderWidth: 1.4, pointRadius: 0, pointHoverRadius: 3, tension: 0 }] },
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
        y: { ticks: { maxTicksLimit: 5, callback: (v) => fmt.fixed(v, digits) }, title: { display: true, text: unit } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => (items.length ? fmt.clock(items[0].parsed.x) : ''),
            label: (item) => `${fmt.fixed(item.parsed.y, digits)}${fmt.NBSP}${unit}`,
          },
        },
        msOverlay: {},
      },
    },
    plugins: [overlayPlugin],
  });

  function applyColours() {
    const o = chart.options;
    chart.data.datasets[0].borderColor = colours.muted;
    for (const axis of [o.scales.x, o.scales.y]) {
      axis.ticks.color = colours.muted;
      axis.border = { color: colours.grid };
    }
    o.scales.y.grid = { color: colours.grid };
    o.scales.y.title.color = colours.muted;
    Object.assign(o.plugins.msOverlay, { alert: colours.alert, replay: colours.replay, surface: colours.surface });
    Object.assign(o.plugins.tooltip, {
      backgroundColor: colours.surface, titleColor: colours.text, bodyColor: colours.text,
      borderColor: colours.grid, borderWidth: 1,
    });
  }
  applyColours();
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    colours = palette();
    applyColours();
    chart.update('none');
  });

  return {
    update({ points, xMin, xMax, playhead, narrow }) {
      chart.data.datasets[0].data = points;
      chart.options.scales.x.min = xMin;
      chart.options.scales.x.max = xMax;
      maxTicks = narrow ? 3 : 6;
      chart.options.plugins.msOverlay.playhead = Number.isFinite(playhead) ? playhead : NaN;
      chart.update('none');
    },
  };
}
