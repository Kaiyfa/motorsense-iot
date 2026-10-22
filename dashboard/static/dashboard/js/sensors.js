// Sensors tab: one trend chart per sensor, exact statistics, data quality and the CSV link.
// Live polls every 2 s (every 10 s for ranges of 2 h and more) and pauses while the tab is hidden.
import * as fmt from 'ms/format.js';
import { createSeriesChart } from 'ms/charts.js';
import { getJSON, showError } from 'ms/net.js';

const config = JSON.parse(document.getElementById('page-config').textContent);
const $ = (id) => document.getElementById(id);
const narrow = window.matchMedia('(max-width: 600px)');

const charts = {};
for (const t of config.tiles) {
  charts[t.key] = createSeriesChart($(`chart-${t.key}`), { unit: t.unit, digits: t.digits });
}

let minutes = 30;
let timer = null;
let loaded = false;

function query() {
  const p = new URLSearchParams({ equipment_id: config.equipmentId });
  if (config.mode === 'replay') {
    p.set('mode', 'replay');
    p.set('session', config.session);
    if (config.pos !== null && config.pos !== undefined && config.pos !== '') p.set('pos', config.pos);
  } else {
    p.set('minutes', String(minutes));
  }
  return p.toString();
}

document.querySelectorAll('#range button').forEach((btn) => {
  btn.addEventListener('click', () => {
    minutes = Number(btn.dataset.minutes);
    document.querySelectorAll('#range button').forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
    refresh();
  });
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { clearTimeout(timer); timer = null; } else if (config.mode === 'live') refresh();
});

function schedule() {
  clearTimeout(timer);
  if (config.mode === 'live' && !document.hidden) timer = setTimeout(refresh, minutes >= 120 ? 10000 : 2000);
}

async function refresh() {
  clearTimeout(timer);
  const q = query();
  $('csv-link').href = `${config.urls.csv}?${q}`;
  try {
    const data = await getJSON(`${config.urls.data}?${q}`);
    showError(null);
    render(data);
  } catch (err) {
    showError(`Could not load the sensor data: ${err.message}.${config.mode === 'live' ? ' Retrying.' : ''}`);
  } finally {
    schedule();
  }
}

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

function render(data) {
  if (!loaded) {
    document.querySelectorAll('.skeleton').forEach((el) => el.replaceWith(document.createTextNode('')));
    loaded = true;
  }
  const xMin = Date.parse(data.range_start);
  const xMax = Date.parse(data.range_end);
  const q = data.quality;
  setText($('q-rows'), String(data.rows));
  setText($('q-rpm'), data.rows ? fmt.fixed(q.readings_per_minute, 1) : '0');
  setText($('q-gaps'), String(q.gaps_over_limit) +
    (q.gaps_over_limit ? ` (longest ${fmt.duration(q.longest_gap_seconds)})` : ''));
  if (config.mode === 'replay') {
    setText($('q-last'), `Second ${data.pos + 1}`);
    setText($('range-label'), `Recorded session ${data.session}, from its start to the Overview's playhead ` +
      `(${fmt.clock(xMax)}). Not live data.`);
  } else {
    setText($('q-last'), q.seconds_since_last_reading === null ? 'never' : fmt.ago(q.seconds_since_last_reading));
    setText($('range-label'), `Stored readings of EQ-001, ${data.label} (${fmt.clock(xMin)} to ${fmt.clock(xMax)})`);
  }
  $('reduced-note').hidden = !data.reduced_for_drawing;

  for (const t of config.tiles) {
    const row = document.querySelector(`.sensor-row[data-key="${t.key}"]`);
    const series = data.series[t.key];
    const points = series.t.map((ts, i) => ({ x: Date.parse(ts), y: series.v[i] }));
    charts[t.key].update({ points, xMin, xMax, playhead: config.mode === 'replay' ? xMax : NaN, narrow: narrow.matches });
    const s = data.stats[t.key];
    const empty = row.querySelector('[data-role="empty"]');
    empty.hidden = s.n > 0;
    if (!s.n) {
      empty.textContent = config.mode === 'live'
        ? `No readings in the ${data.label}. Start the logger on the Pi.`
        : 'No readings in this part of the recording.';
    }
    for (const key of ['min', 'mean', 'max']) {
      setText(row.querySelector(`[data-role="${key}"]`),
        s[key] === null ? '—' : `${fmt.fixed(s[key], t.digits)}${fmt.NBSP}${t.unit}`);
    }
  }
}

refresh();
