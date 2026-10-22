// Live mode: polls the JSON endpoints every 2 s (paused while the tab is hidden).
import {
  config, createOverview, describeState, addAlertDetails, computeChanges, parseSegments,
  getJSON, showError, STATE_NAMES,
} from 'ms/overview.js';
import * as fmt from 'ms/format.js';

const view = createOverview();
const eq = encodeURIComponent(config.equipmentId);
let minutes = 5;
let timer = null;
let loadedOnce = false;
let inFlight = false;

// ---------------------------------------------------------------- controls
document.querySelectorAll('#range button').forEach((btn) => {
  btn.addEventListener('click', () => {
    minutes = Number(btn.dataset.minutes);
    document.querySelectorAll('#range button').forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
    pollNow();
  });
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    clearTimeout(timer);
    timer = null;
  } else {
    pollNow();
  }
});

// ---------------------------------------------------------------- polling
function schedule() {
  clearTimeout(timer);
  if (!document.hidden) timer = setTimeout(poll, config.pollMs);
}

function pollNow() {
  clearTimeout(timer);
  poll();
}

async function poll() {
  if (inFlight) return;
  inFlight = true;
  try {
    const [status, scores, history, timeline] = await Promise.all([
      getJSON(`${config.urls.status}?equipment_id=${eq}`),
      getJSON(`${config.urls.scores}?equipment_id=${eq}&minutes=${minutes}`),
      getJSON(`${config.urls.history}?equipment_id=${eq}&seconds=${config.tileWindowSeconds}`),
      getJSON(`${config.urls.timeline}?equipment_id=${eq}&minutes=${minutes}`),
    ]);
    showError(null);
    render(status, scores, history, timeline);
  } catch (err) {
    showError(`Could not load live data: ${err.message}. Retrying every ${config.pollMs / 1000} s.`);
    if (!loadedOnce) {
      view.clearSkeletons();
      view.renderHero(
        { kind: 'error', label: 'No connection', detail: 'The dashboard could not load any data yet. See the message above.' },
        [{ value: '—' }, { value: '—' }, { value: '—' }],
      );
    }
  } finally {
    inFlight = false;
    schedule();
  }
}

// ---------------------------------------------------------------- model
function isOffline(status) {
  const age = status.seconds_since_last_reading;
  return age === null || age > config.liveMaxAgeSeconds;
}

function heroState(status) {
  const age = status.seconds_since_last_reading;
  if (age === null) {
    return { kind: 'offline', label: 'Offline', detail: 'No readings yet. Start the logger on the Pi.' };
  }
  if (age > config.liveMaxAgeSeconds) {
    return { kind: 'offline', label: 'Offline', detail: `No readings for ${fmt.duration(age)}. Start the logger on the Pi.` };
  }
  if (!status.scorer_alive) {
    return {
      kind: 'offline', label: 'Scorer stopped',
      detail: 'Readings are arriving, but nothing is scoring them. Start the scorer with python manage.py score_live.',
    };
  }
  if (!status.machine_state) {
    return { kind: 'loading', label: 'Waiting for the scorer', detail: 'The scorer is running but has not scored a reading yet.' };
  }
  return describeState({
    machine_state: status.machine_state,
    alert_active: status.alert_active,
    score: status.latest_score,
    threshold: status.threshold,
    warmupElapsed: status.warmup_elapsed_seconds,
    scoringStartsIn: status.scoring_starts_in_seconds,
    consecutiveAbove: status.consecutive_seconds_above_threshold,
  });
}

function heroFacts(status, state, nowMs) {
  const age = status.seconds_since_last_reading;
  const lastMs = age === null ? null : nowMs - age * 1000;
  let inState;
  if (state.kind === 'offline' && state.label === 'Offline') {
    inState = age === null
      ? { label: 'Offline for', value: '—' }
      : { label: 'Offline for', value: fmt.duration(age), small: `since ${fmt.clock(lastMs)}` };
  } else if (status.seconds_in_state !== null && status.machine_state) {
    inState = {
      label: `${STATE_NAMES[status.machine_state] || 'In this state'} for`,
      value: fmt.duration(status.seconds_in_state), small: `since ${fmt.clock(Date.parse(status.state_since))}`,
    };
  } else {
    inState = { label: 'In this state', value: '—' };
  }
  const last = age === null ? { value: 'Never' } : { value: fmt.ago(age), small: fmt.clock(lastMs) };
  const poll = status.scorer_last_poll_seconds_ago;
  const scorer = status.scorer_alive
    ? { value: 'Running', small: `polled ${fmt.ago(poll)}` }
    : { value: 'Not running', small: poll === null ? 'never started' : `last poll ${fmt.ago(poll)}` };
  return [inState, last, scorer];
}

function emptyChartMessage(status, scores, range) {
  if (isOffline(status)) {
    const age = status.seconds_since_last_reading;
    return age === null ? 'No readings yet. Start the logger on the Pi.'
      : `No scores to show: no readings for ${fmt.duration(age)}. Start the logger on the Pi.`;
  }
  if (!status.scorer_alive) return 'Readings are arriving, but the scorer is not running: start it with python manage.py score_live.';
  switch (status.machine_state) {
    case 'idle':
      return `Idle: current at or below ${config.idleCurrentA} A, so nothing is scored. Scores appear after the motors run and warm up.`;
    case 'warming_up':
      return `Warming up: scoring starts ${config.warmupSeconds} s after the motors start, once ${config.sequenceLength} s of running data are buffered.`;
    case 'running':
      return `Running: filling the ${config.sequenceLength} s buffer; the first score follows.`;
    default:
      return scores.scores.length ? `No scored seconds in the last ${range}.` : `No scores in the last ${range}.`;
  }
}

function render(status, scores, history, timeline) {
  const nowMs = Date.parse(timeline.range_end);   // server time, shared by chart, strip and panels
  const xMin = Date.parse(timeline.range_start);
  if (!loadedOnce) {
    view.clearSkeletons();
    loadedOnce = true;
  }

  // readings
  const d = history.data;
  const readings = {
    t: d.timestamps.map((x) => Date.parse(x)),
    vibration_rms: d.vibration_rms, vibration_peak: d.vibration_peak, current: d.current,
    bus_voltage: d.bus_voltage, temperature: d.temperature,
  };
  const changes = computeChanges(readings, nowMs);

  // hero
  let state = heroState(status);
  state = addAlertDetails(state, {
    alertSinceMs: status.alert_since ? Date.parse(status.alert_since) : NaN,
    nowMs, score: status.latest_score, threshold: status.threshold, changes,
  });
  view.renderHero(state, heroFacts(status, state, nowMs));

  // score chart and state timeline (alert bands and markers come from the stored alert seconds)
  const rows = scores.scores.map((s) => ({ t: Date.parse(s.timestamp), score: s.score }));
  const points = rows.map((r) => ({ x: r.t, y: r.score }));
  const threshold = status.threshold ?? (scores.scores.length ? scores.scores[scores.scores.length - 1].threshold : config.threshold);
  const segments = parseSegments(timeline.segments);
  const alerts = segments.filter((s) => s.kind === 'alert');
  const scored = rows.filter((r) => r.score !== null).length;
  const range = minutes < 60 ? `${minutes} min` : `${minutes / 60} h`;
  const latest = rows.length ? rows[rows.length - 1].score : null;
  view.renderChart({
    points, threshold,
    episodes: alerts.map((s) => ({ start: s.start, end: s.end })),
    alertStarts: alerts.map((s) => s.start),
    playhead: NaN, xMin, xMax: nowMs, segments,
    emptyMessage: emptyChartMessage(status, scores, range),
    summary: `Last ${range}: ${scored} scored seconds, latest score ${fmt.score(latest)}, ` +
             `threshold ${fmt.score(threshold)}, ${alerts.length} alert episode${alerts.length === 1 ? '' : 's'}. ` +
             `States: ${segments.map((s) => s.label).join(', ') || 'none stored'}.`,
  });

  // what changed and tiles
  let inactive = null;
  if (isOffline(status)) inactive = 'Offline';
  else if (status.machine_state === 'idle' || status.machine_state === 'warming_up') inactive = 'Not running';
  view.renderChanges(changes, `No readings in the last ${config.changesWindowSeconds} s`, inactive);
  const age = status.seconds_since_last_reading;
  view.renderTiles(readings, nowMs, 'No readings in the last 5 min',
    age !== null && age > config.liveMaxAgeSeconds ? age : null);
}

poll();
