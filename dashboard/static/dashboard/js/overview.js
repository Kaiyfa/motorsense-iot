// Shared Overview rendering for Live and Replay. The controllers (live.js,
// replay.js) build a plain model from the JSON endpoints; this module only draws it.
import * as fmt from './format.js';
import { createScoreChart, sparkPath } from './charts.js';

export const config = JSON.parse(document.getElementById('overview-config').textContent);

const $ = (id) => document.getElementById(id);

const STATE_ICONS = {
  normal: 'i-normal', running: 'i-running', alert: 'i-alert', warming: 'i-warming',
  idle: 'i-idle', offline: 'i-offline', error: 'i-error', loading: 'i-loading',
};

const FEATURE_KEYS = { vib_rms_g: 'vibration_rms', vib_peak_g: 'vibration_peak', current: 'current' };

// --------------------------------------------------------------------- state

/**
 * Machine state of one scored second, in words. `row` has machine_state,
 * alert_active, score, threshold, plus the derived run lengths.
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
        return {
          kind: 'alert', label: 'Alert',
          detail: `Score ${fmt.score(row.score)} has been above the threshold ${fmt.score(threshold)} ` +
                  `for ${config.alertSeconds} s or more.`,
        };
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

// --------------------------------------------------------------------- renderer

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

export function createOverview() {
  const hero = $('hero');
  const chart = createScoreChart($('score-chart'));
  const narrow = window.matchMedia('(max-width: 600px)');
  const ringCircumference = 2 * Math.PI * 36;

  function renderHero(state, facts) {
    hero.dataset.state = state.kind;
    $('state-icon').innerHTML = `<svg><use href="#${STATE_ICONS[state.kind] || 'i-loading'}"/></svg>`;
    setText($('state-label'), state.label);
    setText($('state-detail'), state.detail);

    const ring = $('warmup-ring');
    if (state.kind === 'warming' && Number.isFinite(state.warmupElapsed)) {
      const elapsed = Math.min(Math.max(state.warmupElapsed, 0), config.warmupSeconds);
      ring.hidden = false;
      $('ring-value').setAttribute('stroke-dashoffset', String(ringCircumference * (1 - elapsed / config.warmupSeconds)));
      $('ring-label').textContent = `${Math.round(elapsed)} / ${config.warmupSeconds} s`;
      ring.setAttribute('aria-label', `Warm-up ${Math.round(elapsed)} of ${config.warmupSeconds} seconds`);
    } else {
      ring.hidden = true;
    }

    facts.forEach((f, i) => {
      const dd = $(`fact-${i + 1}`);
      const html = f.small ? `${escapeHtml(f.value)}<small>${escapeHtml(f.small)}</small>` : escapeHtml(f.value);
      if (dd.innerHTML !== html) dd.innerHTML = html;
    });
  }

  function renderChart({ points, threshold, episodes, playhead, xMin, xMax, emptyMessage, summary }) {
    const empty = $('chart-empty');
    const hasData = points.some((p) => p.y !== null);
    if (!hasData) {
      empty.textContent = emptyMessage;
      empty.hidden = false;
    } else {
      empty.hidden = true;
    }
    chart.update({ points, threshold, episodes, playhead, xMin, xMax, narrow: narrow.matches });
    $('score-chart').setAttribute('aria-label', summary);
    setText($('chart-summary'), summary);
  }

  function renderChanges(changes, emptyMessage) {
    const usable = changes.filter((c) => c.z !== null);
    const scale = Math.max(5, Math.ceil(Math.max(0, ...usable.map((c) => Math.abs(c.z)))));
    $('changes-scale').textContent = `bar scale ±${scale} σ`;
    for (const c of changes) {
      const row = document.querySelector(`.change-row[data-feature="${c.feature}"]`);
      const digits = config.featureDigits[c.feature];
      const zEl = row.querySelector('[data-role="z"]');
      const bar = row.querySelector('[data-role="bar"]');
      if (c.z === null) {
        setText(zEl, '—');
        bar.style.left = '50%'; bar.style.width = '0';
        setText(row.querySelector('[data-role="latest"]'), emptyMessage);
        continue;
      }
      setText(zEl, `${fmt.signed(c.z, 1)} σ`);
      const half = Math.min(Math.abs(c.z) / scale, 1) * 50;
      bar.style.left = c.z >= 0 ? '50%' : `${50 - half}%`;
      bar.style.width = `${half}%`;
      setText(row.querySelector('[data-role="latest"]'),
        `Latest ${fmt.fixed(c.latest, digits)} ${config.featureUnits[c.feature]}`);
    }
  }

  function renderTiles(readings, endMs, emptyMessage) {
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
        el.querySelector('[data-role="spark"]').setAttribute('d', '');
        setText(el.querySelector('[data-role="foot"]'), emptyMessage);
        continue;
      }
      setText(valueEl, fmt.fixed(values[values.length - 1], tile.digits));
      el.querySelector('[data-role="spark"]').setAttribute('d', sparkPath(series, fromMs, endMs));
      setText(el.querySelector('[data-role="foot"]'),
        `${fmt.fixed(Math.min(...values), tile.digits)} to ${fmt.fixed(Math.max(...values), tile.digits)} over 5 min`);
    }
  }

  function clearSkeletons() {
    document.querySelectorAll('#hero .skeleton, #changes .skeleton, #tiles .skeleton, #chart-empty .skeleton')
      .forEach((el) => el.replaceWith(document.createTextNode('')));
  }

  return { renderHero, renderChart, renderChanges, renderTiles, clearSkeletons };
}

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Contiguous runs of alert_active seconds -> shaded bands
export function episodesFromRows(rows) {
  const episodes = [];
  let start = null;
  let last = null;
  for (const r of rows) {
    if (r.alert_active) {
      if (start === null) start = r.t;
      last = r.t;
    } else if (start !== null) {
      episodes.push({ start, end: r.t });
      start = null;
    }
  }
  if (start !== null) episodes.push({ start, end: last + 1000 });
  return episodes;
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
