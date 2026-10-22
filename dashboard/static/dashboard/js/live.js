// Live mode: polls the existing JSON endpoints every 2 s (paused while the tab is hidden).
import { config, createOverview, describeState, computeChanges, episodesFromRows, getJSON, showError, STATE_NAMES } from './overview.js';
import * as fmt from './format.js';

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
    const [status, scores, history] = await Promise.all([
      getJSON(`${config.urls.status}?equipment_id=${eq}`),
      getJSON(`${config.urls.scores}?equipment_id=${eq}&minutes=${minutes}`),
      getJSON(`${config.urls.history}?equipment_id=${eq}&seconds=${config.tileWindowSeconds}`),
    ]);
    showError(null);
    render(status, scores, history);
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

function heroFacts(status, state) {
  const age = status.seconds_since_last_reading;
  const lastMs = age === null ? null : Date.now() - age * 1000;
  const offline = state.kind === 'offline' && state.label === 'Offline';
  let inState;
  if (offline) {
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

function render(status, scores, history) {
  const now = Date.now();
  if (!loadedOnce) {
    view.clearSkeletons();
    loadedOnce = true;
  }

  const state = heroState(status);
  view.renderHero(state, heroFacts(status, state));

  // score chart
  const rows = scores.scores.map((s) => ({ t: Date.parse(s.timestamp), score: s.score, alert_active: s.alert_active }));
  const points = rows.map((r) => ({ x: r.t, y: r.score }));
  const threshold = status.threshold ?? (scores.scores.length ? scores.scores[scores.scores.length - 1].threshold : config.threshold);
  const episodes = episodesFromRows(rows);
  const scored = rows.filter((r) => r.score !== null).length;
  const range = minutes < 60 ? `${minutes} min` : `${minutes / 60} h`;
  let emptyMessage;
  if (!rows.length) {
    emptyMessage = status.scorer_alive
      ? `No scores in the last ${range}.`
      : `No scores in the last ${range}. The scorer is not running: start it with python manage.py score_live.`;
  } else {
    emptyMessage = `No scored seconds in the last ${range}: the machine was idle, warming up or filling the ${config.sequenceLength} s buffer.`;
  }
  const latest = rows.length ? rows[rows.length - 1].score : null;
  view.renderChart({
    points, threshold, episodes, playhead: NaN,
    xMin: now - minutes * 60000, xMax: now,
    emptyMessage,
    summary: `Last ${range}: ${scored} scored seconds, latest score ${fmt.score(latest)}, ` +
             `threshold ${fmt.score(threshold)}, ${episodes.length} alert episode${episodes.length === 1 ? '' : 's'}.`,
  });

  // readings
  const d = history.data;
  const readings = {
    t: d.timestamps.map((x) => Date.parse(x)),
    vibration_rms: d.vibration_rms, vibration_peak: d.vibration_peak, current: d.current,
    bus_voltage: d.bus_voltage, temperature: d.temperature,
  };
  view.renderChanges(computeChanges(readings, now), `No readings in the last ${config.changesWindowSeconds} s`,
    status.machine_state);
  const age = status.seconds_since_last_reading;
  view.renderTiles(readings, now, 'No readings in the last 5 min',
    age !== null && age > config.liveMaxAgeSeconds ? age : null);
}

poll();
