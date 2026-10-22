// Replay mode: steps through the recorded scores and readings of one session.
// Reads /api/replay/<label>/ and /api/replay/<label>/readings/ only; nothing here is live.
// By default the chart and the state strip show nothing after the playhead.
import {
  config, createOverview, describeState, addAlertDetails, computeChanges, parseSegments,
  getJSON, showError, STATE_NAMES,
} from 'ms/overview.js';
import * as fmt from 'ms/format.js';

const view = createOverview();
const $ = (id) => document.getElementById(id);

const playBtn = $('play-btn');
const scrubber = $('scrubber');
const jumpBtn = $('jump-alert');
const wholeToggle = $('show-whole');

let rows = [];
let readings = null;
let episodes = [];
let timeline = [];
let threshold = null;
let index = 0;
let speed = 1;
let playTimer = null;
let carry = 0;
let firstAlert = -1;

// ---------------------------------------------------------------- picker and controls
$('session-picker').addEventListener('change', (e) => {
  const url = new URL(window.location.href);
  url.searchParams.set('session', e.target.value);
  url.searchParams.delete('pos');
  window.location.assign(url.toString());
});

document.querySelectorAll('#speed button').forEach((btn) => {
  btn.addEventListener('click', () => {
    speed = Number(btn.dataset.speed);
    document.querySelectorAll('#speed button').forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
  });
});

playBtn.addEventListener('click', () => (playTimer ? pause() : play()));
scrubber.addEventListener('input', () => { pause(); go(Number(scrubber.value)); });
scrubber.addEventListener('change', rememberPosition);
jumpBtn.addEventListener('click', () => { pause(); go(firstAlert); rememberPosition(); });
wholeToggle.addEventListener('change', () => go(index));

document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });

function play() {
  if (!rows.length) return;
  if (index >= rows.length - 1) go(0);
  carry = 0;
  playTimer = setInterval(() => {
    carry += speed * 0.1;
    const steps = Math.floor(carry);
    if (!steps) return;
    carry -= steps;
    if (index + steps >= rows.length - 1) {
      go(rows.length - 1);
      pause();
    } else {
      go(index + steps);
    }
  }, 100);
  setPlayButton(true);
}

function pause() {
  if (!playTimer) return;
  clearInterval(playTimer);
  playTimer = null;
  setPlayButton(false);
  rememberPosition();
}

function setPlayButton(playing) {
  playBtn.setAttribute('aria-pressed', String(playing));
  playBtn.innerHTML = playing
    ? '<svg aria-hidden="true"><use href="#i-pause"/></svg><span>Pause</span>'
    : '<svg aria-hidden="true"><use href="#i-play"/></svg><span>Play</span>';
}

function rememberPosition() {
  const url = new URL(window.location.href);
  url.searchParams.set('session', config.session);
  url.searchParams.set('pos', String(index));
  window.history.replaceState(null, '', url.toString());
  // tabs that show replayed data open at the same playhead
  document.querySelectorAll('.tabs a[data-mode-tab]').forEach((a) => {
    const target = new URL(a.href);
    target.searchParams.set('pos', String(index));
    a.href = target.toString();
  });
}

// ---------------------------------------------------------------- data
async function load() {
  try {
    const [detail, rec] = await Promise.all([getJSON(config.urls.replay), getJSON(config.urls.replayReadings)]);
    threshold = detail.threshold;
    rows = detail.scores.map((s) => ({
      t: Date.parse(s.timestamp), machine_state: s.machine_state, score: s.score,
      above: s.above_threshold, alert_active: s.alert_active, run_label: s.run_label,
    }));
    const last = rows.length ? rows[rows.length - 1].t : 0;
    episodes = detail.alerts.map((a) => ({
      start: Date.parse(a.started_at),
      end: a.open_at_end_of_recording ? last + 1000 : Date.parse(a.ended_at),
      openAtEnd: a.open_at_end_of_recording,
    }));
    timeline = detail.timeline;
    readings = {
      t: rec.data.timestamps.map((x) => Date.parse(x)),
      vibration_rms: rec.data.vibration_rms, vibration_peak: rec.data.vibration_peak, current: rec.data.current,
      bus_voltage: rec.data.bus_voltage, temperature: rec.data.temperature,
    };
    derive();
    firstAlert = rows.findIndex((r) => r.alert_active);
    if (firstAlert < 0) {
      jumpBtn.disabled = true;
      jumpBtn.querySelector('span').textContent = 'No alert in this session';
    }
    scrubber.max = String(Math.max(rows.length - 1, 0));
    view.clearSkeletons();
    showError(null);
    const start = Number.isInteger(config.pos) ? Math.min(Math.max(config.pos, 0), rows.length - 1) : 0;
    go(start);
    rememberPosition();
  } catch (err) {
    showError(`Could not load the recorded session: ${err.message}.`);
    view.clearSkeletons();
    view.renderHero({ kind: 'error', label: 'Not loaded', detail: 'The recorded session could not be loaded. See the message above.' },
      [{ value: '—' }, { value: '—' }, { value: '—' }]);
  }
}

// Per-second details the live API computes server-side, derived here from the recording.
function derive() {
  let stateStart = 0;
  let above = 0;
  let unscoredRunning = 0;
  rows.forEach((r, i) => {
    if (i > 0 && (r.machine_state !== rows[i - 1].machine_state || r.t - rows[i - 1].t > config.maxGapSeconds * 1000)) {
      stateStart = i;
      unscoredRunning = 0;
    }
    r.stateStart = stateStart;
    above = r.above ? above + 1 : 0;
    r.consecutiveAbove = Math.min(above, config.alertSeconds);
    if (r.machine_state === 'warming_up') r.warmupElapsed = (r.t - rows[stateStart].t) / 1000;
    if (r.machine_state === 'running' && r.score === null) {
      unscoredRunning += 1;
      r.scoringStartsIn = Math.max(0, config.sequenceLength - unscoredRunning);
    }
  });
}

// ---------------------------------------------------------------- render
function go(i) {
  if (!rows.length || i < 0) return;
  index = i;
  const r = rows[i];
  const t0 = rows[0].t;
  const tEnd = rows[rows.length - 1].t + 1000;
  const whole = wholeToggle.checked;
  const visibleEnd = whole ? tEnd : r.t + 1000;   // nothing after the playhead unless asked

  const changes = computeChanges(readings, r.t);
  const episode = episodes.find((e) => e.start <= r.t && r.t < e.end);
  let state = describeState({ ...r, threshold });
  state = addAlertDetails(state, {
    alertSinceMs: episode ? episode.start : NaN, nowMs: r.t, score: r.score, threshold, changes,
  });
  view.renderHero(state, [
    { label: `${STATE_NAMES[r.machine_state] || 'In this state'} for`,
      value: fmt.duration((r.t - rows[r.stateStart].t) / 1000), small: `since ${fmt.clock(rows[r.stateStart].t)}` },
    { value: fmt.clock(r.t), small: fmt.date(r.t) },
    { value: `${i + 1} / ${rows.length}`, small: `${fmt.duration((r.t - t0) / 1000)} into the recording` },
  ]);

  const visible = rows.filter((x) => x.t < visibleEnd);
  const visibleEpisodes = episodes.filter((e) => e.start < visibleEnd)
    .map((e) => ({ ...e, end: Math.min(e.end, visibleEnd) }));
  const segments = parseSegments(timeline, whole ? null : visibleEnd);
  const scored = rows.filter((x) => x.score !== null).length;
  const open = visibleEpisodes.some((e) => e.openAtEnd && e.end >= tEnd);
  view.renderChart({
    points: visible.map((x) => ({ x: x.t, y: x.score })),
    threshold, episodes: visibleEpisodes, alertStarts: visibleEpisodes.map((e) => e.start),
    playhead: r.t, xMin: t0, xMax: tEnd, segments,
    emptyMessage: r.machine_state === 'warming_up'
      ? `Warming up: nothing is scored for the first ${config.warmupSeconds} s after the motors start.`
      : r.machine_state === 'idle' ? `Idle: current at or below ${config.idleCurrentA} A, so nothing is scored.`
        : `Running: filling the ${config.sequenceLength} s buffer; the first score follows.`,
    summary: `Replay of ${config.session}: ${scored} scored seconds in the recording, threshold ${fmt.score(threshold)}. ` +
             `${whole ? 'Whole session shown' : 'Shown up to the playhead'}, ${visibleEpisodes.length} alert ` +
             `episode${visibleEpisodes.length === 1 ? '' : 's'} visible. Playhead at ${fmt.clock(r.t)}, score ${fmt.score(r.score)}.`,
  });
  const note = $('chart-note');
  if (note) note.hidden = !open;

  const inactive = r.machine_state === 'idle' || r.machine_state === 'warming_up' ? 'Not running' : null;
  view.renderChanges(changes, `No readings in the ${config.changesWindowSeconds} s before the playhead`, inactive);
  view.renderTiles(readings, r.t, 'No readings in the 5 min before the playhead');

  scrubber.value = String(i);
  scrubber.setAttribute('aria-valuetext', `${fmt.clock(r.t)}, ${state.label}`);
  $('scrub-time').textContent = `${fmt.clock(r.t)} (${fmt.timezoneLabel()})`;
  $('scrub-pos').textContent = `Second ${i + 1} of ${rows.length}`;
}

load();
