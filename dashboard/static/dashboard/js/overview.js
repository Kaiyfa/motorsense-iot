// Shared Overview rendering for Live and Replay. The controllers (live.js,
// replay.js) build a plain model from the JSON endpoints; this module only draws it.
import * as fmt from 'ms/format.js';
import { createScoreChart, sparkPath } from 'ms/charts.js';

export const config = JSON.parse(document.getElementById('overview-config').textContent);

const $ = (id) => document.getElementById(id);

const STATE_ICONS = {
  normal: 'i-normal', running: 'i-running', alert: 'i-alert', warming: 'i-warming',
  idle: 'i-idle', offline: 'i-offline', error: 'i-error', loading: 'i-loading',
};

export const STATE_NAMES = { idle: 'Idle', warming_up: 'Warming up', running: 'Running' };

const FEATURE_KEYS = { vib_rms_g: 'vibration_rms', vib_peak_g: 'vibration_peak', current: 'current' };

// --------------------------------------------------------------------- state

/**
 * Machine state of one second, in words. `row` has machine_state, alert_active,
 * score, threshold, plus the derived run lengths.
 */
export function describeState(row) {
  const threshold = row.threshold;
  switch (row.machine_state) {
    case 'idle':
      return { kind: 'idle', label: 'Idle', detail: `Current at or below ${config.idleCurrentA} A. Not scored.` };
    case 'warming_up':
      return {
        kind: 'warming', label: 'Warming up', detail: 'Scoring starts after warm-up.',
        warmupElapsed: row.warmupElapsed,
      };
    case 'running':
      if (row.alert_active) {
        return { kind: 'alert', label: 'Alert', detail: `Score ${fmt.score(row.score)}, threshold ${fmt.score(threshold)}.` };
      }
      if (row.score === null || row.score === undefined) {
        const left = row.scoringStartsIn;
        return {
          kind: 'running', label: 'Running',
          detail: left !== null && left !== undefined
            ? `Scoring starts in ${left} s, once ${config.sequenceLength} s of running data are buffered.`
            : `Not scored yet: filling the ${config.sequenceLength} s buffer.`,
        };
      }
      if (row.consecutiveAbove > 0) {
        return {
          kind: 'normal', label: 'Normal',
          detail: `Score ${fmt.score(row.score)} above the threshold ${fmt.score(threshold)} for ` +
                  `${row.consecutiveAbove} s. An alert needs ${config.alertSeconds} s in a row.`,
        };
      }
      return {
        kind: 'normal', label: 'Normal',
        detail: `Score ${fmt.score(row.score)}, below the threshold ${fmt.score(threshold)}.`,
      };
    default:
      return { kind: 'loading', label: 'Unknown', detail: 'No machine state recorded yet.' };
  }
}

/**
 * Alert lines for the hero, from the same numbers as the "What changed" panel.
 * Never names a cause.
 */
export function addAlertDetails(state, { alertSinceMs, nowMs, score, threshold, changes }) {
  if (state.kind !== 'alert') return state;
  const since = Number.isFinite(alertSinceMs)
    ? `Alert since ${fmt.clock(alertSinceMs)}, lasting ${fmt.mmss((nowMs - alertSinceMs) / 1000)}. `
    : '';
  const largest = largestDeviation(changes);
  let deviation;
  if (largest) {
    const unit = config.featureUnits[largest.feature];
    const digits = config.featureDigits[largest.feature];
    const base = config.baseline[largest.feature];
    deviation = `Largest deviation: ${config.featureNames[largest.feature]} ${fmt.signed(largest.z, 1)} σ ` +
      `(baseline ${fmt.fixed(base.mean, digits)} ${unit}, latest ${fmt.fixed(largest.latest, digits)} ${unit}).`;
  } else {
    deviation = `Largest deviation: not available (no readings in the last ${config.changesWindowSeconds} s).`;
  }
  return {
    ...state,
    detail: `${since}Score ${fmt.score(score)}, threshold ${fmt.score(threshold)}.`,
    detail2: `${deviation} This is data, not a diagnosis.`,
  };
}

export function largestDeviation(changes) {
  return (changes || []).filter((c) => c.z !== null)
    .reduce((best, c) => (best === null || Math.abs(c.z) > Math.abs(best.z) ? c : best), null);
}

// --------------------------------------------------------------------- what changed

export function computeChanges(readings, endMs) {
  // readings: { t: [ms], vibration_rms: [...], ... } sorted by time
  const fromMs = endMs - config.changesWindowSeconds * 1000;
  const out = [];
  for (const [feature, key] of Object.entries(FEATURE_KEYS)) {
    const values = [];
    for (let i = 0; i < readings.t.length; i++) {
      const v = readings[key][i];
      if (readings.t[i] > fromMs && readings.t[i] <= endMs && v !== null && Number.isFinite(v)) values.push(v);
    }
    const base = config.baseline ? config.baseline[feature] : null;
    const mean = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
    out.push({
      feature,
      n: values.length,
      latest: values.length ? values[values.length - 1] : null,
      z: base && mean !== null ? (mean - base.mean) / base.std : null,
    });
  }
  return out;
}

// --------------------------------------------------------------------- helpers

function setText(el, text) {
  if (!el) return;
  if (el.textContent !== text) {
    el.textContent = text;
    if (el.classList.contains('value')) {
      el.classList.remove('changed');
      void el.offsetWidth; // restart the animation
      el.classList.add('changed');
    }
  }
}

export function showError(message) {
  const box = $('error-notice');
  if (!box) return;
  if (message) {
    box.textContent = message;
    box.hidden = false;
  } else {
    box.hidden = true;
  }
}

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Timeline segments from the API (ISO times) -> ms, clipped at clipMs if given.
export function parseSegments(segments, clipMs = null) {
  const out = [];
  for (const s of segments || []) {
    const start = Date.parse(s.start);
    let end = Date.parse(s.end);
    if (clipMs !== null) {
      if (start >= clipMs) continue;
      end = Math.min(end, clipMs);
    }
    out.push({ kind: s.kind, label: s.label, start, end });
  }
  return out;
}

// --------------------------------------------------------------------- renderer

export function createOverview() {
  const hero = $('hero');
  const strip = $('timeline');
  const tip = $('timeline-tip');
  const fill = $('chart-fill');
  const narrow = window.matchMedia('(max-width: 600px)');
  const ringCircumference = 2 * Math.PI * 36;

  let area = null;            // plot area of the score chart (px, relative to the chart box)
  let stripState = { segments: [], xMin: 0, xMax: 1 };
  let activeIndex = -1;

  const chart = createScoreChart($('score-chart'), (a) => {
    area = a;
    placeStrip();
  });

  // ---------------------------------------------------------------- hero
  function renderHero(state, facts) {
    hero.dataset.state = state.kind;
    $('state-icon').innerHTML = `<svg><use href="#${STATE_ICONS[state.kind] || 'i-loading'}"/></svg>`;
    setText($('state-label'), state.label);
    setText($('state-detail'), state.detail);
    const detail2 = $('state-detail-2');
    detail2.hidden = !state.detail2;
    setText(detail2, state.detail2 || '');

    const ring = $('warmup-ring');
    if (state.kind === 'warming' && Number.isFinite(state.warmupElapsed)) {
      const elapsed = Math.min(Math.max(state.warmupElapsed, 0), config.warmupSeconds);
      ring.hidden = false;
      $('ring-value').setAttribute('stroke-dashoffset', String(ringCircumference * (1 - elapsed / config.warmupSeconds)));
      $('ring-label').innerHTML = `<span class="ring-num">${Math.round(elapsed)} s</span>` +
        `<span class="ring-of">of ${config.warmupSeconds} s</span>`;
      ring.setAttribute('aria-label', `Warm-up ${Math.round(elapsed)} of ${config.warmupSeconds} seconds`);
    } else {
      ring.hidden = true;
    }

    facts.forEach((f, i) => {
      if (f.label) setText($(`fact-${i + 1}-label`), f.label);
      const dd = $(`fact-${i + 1}`);
      const html = f.small ? `${escapeHtml(f.value)}<small>${escapeHtml(f.small)}</small>` : escapeHtml(f.value);
      if (dd.innerHTML !== html) dd.innerHTML = html;
    });
  }

  // ---------------------------------------------------------------- chart and timeline
  function placeStrip() {
    if (!area) return;
    const width = Math.max(area.right - area.left, 0);
    strip.style.marginLeft = `${area.left}px`;
    strip.style.width = `${width}px`;
    Object.assign(fill.style, {
      left: `${area.left}px`, top: `${area.top}px`,
      width: `${width}px`, height: `${Math.max(area.bottom - area.top, 0)}px`,
    });
    drawSegments();
  }

  function segmentText(s) {
    return `${s.label}: ${fmt.clock(s.start)} to ${fmt.clock(s.end)}, ${fmt.duration((s.end - s.start) / 1000)}`;
  }

  function drawSegments() {
    const { segments, xMin, xMax } = stripState;
    const span = Math.max(xMax - xMin, 1);
    const width = strip.clientWidth || 1;
    const fillWidth = fill.clientWidth || width;
    const parts = [];
    const fills = [];
    segments.forEach((s, i) => {
      const left = Math.max(0, (s.start - xMin) / span) * 100;
      const right = Math.min(1, (s.end - xMin) / span) * 100;
      if (right <= left) return;
      const fits = (w) => w >= s.label.length * 7 + 12;
      const style = `left:${left.toFixed(3)}%;width:${(right - left).toFixed(3)}%`;
      const label = fits(((right - left) / 100) * width) ? escapeHtml(s.label) : '';
      const fillLabel = fits(((right - left) / 100) * fillWidth) ? escapeHtml(s.label) : '';
      parts.push(`<div class="seg seg-${s.kind}${i === activeIndex ? ' active' : ''}" style="${style}" data-i="${i}">` +
                 `<span>${label}</span></div>`);
      fills.push(`<div class="fill-seg seg-${s.kind}" style="${style}"><span>${fillLabel}</span></div>`);
    });
    strip.innerHTML = parts.join('');
    $('chart-fill-segs').innerHTML = fills.join('');
    strip.setAttribute('aria-label', segments.length
      ? `State timeline, ${segments.length} segment${segments.length === 1 ? '' : 's'}. Use the arrow keys to read them.`
      : 'State timeline: no stored states in this range.');
  }

  function showTip(i, clientX) {
    const s = stripState.segments[i];
    if (!s) { hideTip(); return; }
    activeIndex = i;
    tip.textContent = segmentText(s);
    tip.hidden = false;
    const box = strip.getBoundingClientRect();
    const parent = tip.parentElement.getBoundingClientRect();
    const span = Math.max(stripState.xMax - stripState.xMin, 1);
    const mid = (Math.max(s.start, stripState.xMin) + Math.min(s.end, stripState.xMax)) / 2;
    const centre = clientX ?? box.left + ((mid - stripState.xMin) / span) * box.width;
    const half = tip.offsetWidth / 2;
    const x = Math.min(Math.max(centre - parent.left, half + 4), parent.width - half - 4);
    tip.style.left = `${x}px`;
    $('timeline-live').textContent = tip.textContent;
    strip.querySelectorAll('.seg').forEach((el) => el.classList.toggle('active', Number(el.dataset.i) === i));
  }

  function hideTip() {
    activeIndex = -1;
    tip.hidden = true;
    strip.querySelectorAll('.seg.active').forEach((el) => el.classList.remove('active'));
  }

  function indexAt(clientX) {
    const box = strip.getBoundingClientRect();
    const t = stripState.xMin + ((clientX - box.left) / Math.max(box.width, 1)) * (stripState.xMax - stripState.xMin);
    return stripState.segments.findIndex((s) => t >= s.start && t < s.end);
  }

  strip.addEventListener('pointermove', (e) => {
    const i = indexAt(e.clientX);
    if (i < 0) hideTip(); else showTip(i, e.clientX);
  });
  strip.addEventListener('pointerleave', hideTip);
  strip.addEventListener('blur', hideTip);
  strip.addEventListener('keydown', (e) => {
    const n = stripState.segments.length;
    if (!n) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const step = e.key === 'ArrowRight' ? 1 : -1;
      const next = activeIndex < 0 ? (step > 0 ? 0 : n - 1) : Math.min(Math.max(activeIndex + step, 0), n - 1);
      showTip(next);
    } else if (e.key === 'Escape') {
      hideTip();
    }
  });
  window.addEventListener('resize', placeStrip);

  /**
   * model: points, threshold, episodes, alertStarts, playhead, xMin, xMax,
   * segments (ms), emptyMessage, summary
   */
  function renderChart(model) {
    const hasData = model.points.some((p) => p.y !== null);
    stripState = { segments: model.segments || [], xMin: model.xMin, xMax: model.xMax };
    if (activeIndex >= stripState.segments.length) hideTip();
    fill.hidden = hasData;
    if (!hasData) $('chart-fill-text').textContent = model.emptyMessage;
    chart.update({ ...model, narrow: narrow.matches });
    placeStrip();
    $('score-chart').setAttribute('aria-label', model.summary);
    setText($('chart-summary'), model.summary);
  }

  // ---------------------------------------------------------------- what changed
  // inactive: null, or a label ("Not running", "Offline") shown instead of deviations
  function renderChanges(changes, emptyMessage, inactive = null) {
    const panel = $('changes-panel');
    panel.classList.toggle('inactive', Boolean(inactive));
    const badge = $('changes-badge');
    badge.hidden = !inactive;
    badge.textContent = inactive || '';
    const note = $('changes-inactive');
    note.hidden = !inactive;
    if (inactive) {
      note.textContent = inactive === 'Offline'
        ? 'No current readings. Deviations are shown again when readings arrive.'
        : 'The baseline comes from running data, so deviations mean nothing while the machine is idle or warming up.';
    }

    const usable = inactive ? [] : changes.filter((c) => c.z !== null);
    const scale = Math.max(5, Math.ceil(Math.max(0, ...usable.map((c) => Math.abs(c.z)))));
    $('changes-scale').textContent = `bar scale ±${scale} σ`;
    for (const c of changes) {
      const row = document.querySelector(`.change-row[data-feature="${c.feature}"]`);
      const digits = config.featureDigits[c.feature];
      const zEl = row.querySelector('[data-role="z"]');
      const bar = row.querySelector('[data-role="bar"]');
      const latestEl = row.querySelector('[data-role="latest"]');
      const latestText = c.latest === null ? emptyMessage
        : `Latest ${fmt.fixed(c.latest, digits)} ${config.featureUnits[c.feature]}`;
      if (inactive || c.z === null) {
        setText(zEl, '—');
        bar.style.left = '50%'; bar.style.width = '0';
        setText(latestEl, latestText);
        continue;
      }
      setText(zEl, `${fmt.signed(c.z, 1)} σ`);
      const half = Math.min(Math.abs(c.z) / scale, 1) * 50;
      bar.style.left = c.z >= 0 ? '50%' : `${50 - half}%`;
      bar.style.width = `${half}%`;
      setText(latestEl, latestText);
    }
  }

  // ---------------------------------------------------------------- tiles
  // staleSeconds: set when no reading arrived recently (offline); the tiles then say so.
  function renderTiles(readings, endMs, emptyMessage, staleSeconds = null) {
    const fromMs = endMs - config.tileWindowSeconds * 1000;
    for (const tile of config.tiles) {
      const el = document.querySelector(`.tile[data-key="${tile.key}"]`);
      const series = [];
      for (let i = 0; i < readings.t.length; i++) {
        if (readings.t[i] > fromMs && readings.t[i] <= endMs) series.push({ x: readings.t[i], y: readings[tile.key][i] });
      }
      const values = series.map((p) => p.y).filter((v) => v !== null && Number.isFinite(v));
      const valueEl = el.querySelector('[data-role="value"]');
      if (!values.length) {
        setText(valueEl, '—');
        el.classList.remove('stale');
        el.querySelector('[data-role="spark"]').setAttribute('d', '');
        setText(el.querySelector('[data-role="foot"]'), emptyMessage);
        continue;
      }
      setText(valueEl, fmt.fixed(values[values.length - 1], tile.digits));
      el.classList.toggle('stale', staleSeconds !== null);
      el.querySelector('[data-role="spark"]').setAttribute('d', sparkPath(series, fromMs, endMs, tile.minSpan));
      const range = `${fmt.fixed(Math.min(...values), tile.digits)} to ` +
                    `${fmt.fixed(Math.max(...values), tile.digits)} ${tile.unit} over 5 min`;
      setText(el.querySelector('[data-role="foot"]'),
        staleSeconds !== null ? `Last reading ${fmt.ago(staleSeconds)}. ${range}` : range);
    }
  }

  function clearSkeletons() {
    document.querySelectorAll('#hero .skeleton, #changes .skeleton, #tiles .skeleton, #chart-fill .skeleton')
      .forEach((el) => el.replaceWith(document.createTextNode('')));
  }

  return { renderHero, renderChart, renderChanges, renderTiles, clearSkeletons };
}

// Fetch JSON; raise readable errors (HTTP status, expired login, network).
export async function getJSON(url, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' }, signal: controller.signal,
      credentials: 'same-origin' });
  } catch (err) {
    throw new Error(err.name === 'AbortError' ? `no answer from ${url} within ${timeoutMs / 1000} s`
      : `network error while loading ${url}`);
  } finally {
    clearTimeout(timer);
  }
  if (response.redirected && response.url.includes('/login')) {
    throw new Error('your login session has expired; reload the page to log in again');
  }
  if (!response.ok) throw new Error(`HTTP ${response.status} from ${url}`);
  const type = response.headers.get('content-type') || '';
  if (!type.includes('application/json')) throw new Error(`unexpected response from ${url}`);
  return response.json();
}
