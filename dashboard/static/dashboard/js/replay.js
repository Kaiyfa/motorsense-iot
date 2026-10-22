// Replay mode: steps through the recorded scores and readings of one session.
// Reads /api/replay/<label>/ and /api/replay/<label>/readings/ only; nothing here is live.
import { config, createOverview, describeState, computeChanges, getJSON, showError } from './overview.js';
import * as fmt from './format.js';

const view = createOverview();
const $ = (id) => document.getElementById(id);

const playBtn = $('play-btn');
const scrubber = $('scrubber');
const jumpBtn = $('jump-alert');

let rows = [];
let readings = null;
let episodes = [];
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
  const tEnd = rows[rows.length - 1].t;

  const state = describeState({ ...r, threshold });
  view.renderHero(state, [
    { value: fmt.duration((r.t - rows[r.stateStart].t) / 1000), small: `since ${fmt.clock(rows[r.stateStart].t)}` },
    { value: fmt.clock(r.t), small: fmt.date(r.t) },
    { value: `${i + 1} / ${rows.length}`, small: `${fmt.duration((r.t - t0) / 1000)} into the recording` },
  ]);

  const scored = rows.filter((x) => x.score !== null).length;
  const open = episodes.some((e) => e.openAtEnd);
  view.renderChart({
    points: rows.map((x) => ({ x: x.t, y: x.score })),
    threshold, episodes, playhead: r.t, xMin: t0, xMax: tEnd + 1000,
    emptyMessage: 'This recording has no scored seconds.',
    summary: `Replay of ${config.session}: ${scored} scored seconds, threshold ${fmt.score(threshold)}, ` +
             `${episodes.length} alert episode${episodes.length === 1 ? '' : 's'}` +
             `${open ? ', the last one still active when the recording ended' : ''}. ` +
             `Playhead at ${fmt.clock(r.t)}, score ${fmt.score(r.score)}.`,
  });
  const note = $('chart-note');
  if (note) note.hidden = !open;

  view.renderChanges(computeChanges(readings, r.t), `No readings in the ${config.changesWindowSeconds} s before the playhead`);
  view.renderTiles(readings, r.t, 'No readings in the 5 min before the playhead');

  scrubber.value = String(i);
  scrubber.setAttribute('aria-valuetext', `${fmt.clock(r.t)}, ${state.label}`);
  $('scrub-time').textContent = `${fmt.clock(r.t)} (${fmt.timezoneLabel()})`;
  $('scrub-pos').textContent = `Second ${i + 1} of ${rows.length}`;
}

load();
