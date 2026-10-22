// Alerts tab: table of stored alert episodes; a row expands to the scores around its start
// and the three feature deviations in the 60 s before it and in the first 60 s of the alert.
import * as fmt from 'ms/format.js';
import { createScoreChart } from 'ms/charts.js';
import { getJSON, showError } from 'ms/net.js';

const config = JSON.parse(document.getElementById('page-config').textContent);
const $ = (id) => document.getElementById(id);
const nb = fmt.NBSP;

let mode = ['live', 'replay', 'all'].includes(config.filter) ? config.filter : 'live';
let days = 7;
let lastJSON = '';
let openId = config.open ? Number(config.open) : null;
let timer = null;

function press(groupId, attr, value) {
  document.querySelectorAll(`#${groupId} button`).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset[attr] === String(value))));
}
press('mode-filter', 'mode', mode);

document.querySelectorAll('#mode-filter button').forEach((b) => b.addEventListener('click', () => {
  mode = b.dataset.mode; press('mode-filter', 'mode', mode); lastJSON = ''; load();
}));
document.querySelectorAll('#days-filter button').forEach((b) => b.addEventListener('click', () => {
  days = Number(b.dataset.days); press('days-filter', 'days', days); lastJSON = ''; load();
}));
document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(timer); else load(); });

function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function deviationText(d) {
  if (!d) return 'No readings in the 60 s before the start';
  return `${d.name} ${fmt.signed(d.z, 1)}${nb}σ (baseline ${fmt.fixed(d.baseline_mean, 3)}${nb}${d.unit}, ` +
         `latest ${fmt.fixed(d.latest, 3)}${nb}${d.unit})`;
}

function statusCell(e) {
  if (e.open) return '<span class="status-chip open">Open</span>';
  let html = '<span class="status-chip">Closed</span>';
  if (e.open_at_end_of_recording) html += '<span class="cell-note">Still open when the recording ended</span>';
  return html;
}

function startCell(e) {
  const t = Date.parse(e.started_at);
  let html = `<span class="num">${fmt.dateTime(t)}</span>`;
  if (e.mode === 'replay') {
    html += `<span class="replay-chip">Replay</span><span class="cell-note">${esc(e.session_name)}</span>`;
  }
  return html;
}

async function load() {
  clearTimeout(timer);
  try {
    const data = await getJSON(`${config.urls.table}?mode=${mode}&days=${days}`);
    showError(null);
    const json = JSON.stringify(data.episodes);
    if (json !== lastJSON) {
      lastJSON = json;
      render(data);
    }
  } catch (err) {
    showError(`Could not load the alerts: ${err.message}.`);
  } finally {
    if (!document.hidden && mode !== 'replay') timer = setTimeout(load, 10000);
  }
}

function render(data) {
  const body = $('alert-rows');
  if (!data.episodes.length) {
    const what = mode === 'replay' ? 'No replayed alerts are stored. Replays are made with python manage.py replay_session.'
      : `No alerts in this range (${mode === 'all' ? 'live alerts in the last ' : 'last '}${data.range_label}).`;
    body.innerHTML = `<tr><td colspan="6" class="empty-cell">${esc(what)}</td></tr>`;
    return;
  }
  body.innerHTML = data.episodes.map((e) => `
    <tr class="alert-row${e.mode === 'replay' ? ' is-replay' : ''}" data-id="${e.id}" tabindex="0" aria-expanded="false"
        aria-controls="detail-${e.id}">
      <td data-label="Start"><div>${startCell(e)}</div></td>
      <td data-label="Duration" class="num"><div>${fmt.duration(e.duration_seconds)}${e.open ? ' so far' : ''}</div></td>
      <td data-label="Peak score" class="num num-col"><div>${fmt.score(e.peak_score)}</div></td>
      <td data-label="Status"><div>${statusCell(e)}</div></td>
      <td data-label="Run label"><div class="mono">${esc(e.run_label)}</div></td>
      <td data-label="Largest deviation"><div>${esc(deviationText(e.largest_deviation))}</div></td>
    </tr>
    <tr class="detail-row" id="detail-${e.id}" hidden><td colspan="6"><div class="alert-detail"></div></td></tr>`).join('');
  body.querySelectorAll('.alert-row').forEach((row) => {
    const toggle = () => toggleRow(row);
    row.addEventListener('click', toggle);
    row.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); } });
  });
  if (openId !== null) {
    const row = body.querySelector(`.alert-row[data-id="${openId}"]`);
    if (row) toggleRow(row, true);
  }
}

async function toggleRow(row, forceOpen = false) {
  const id = Number(row.dataset.id);
  const detail = $(`detail-${id}`);
  const open = forceOpen || row.getAttribute('aria-expanded') !== 'true';
  row.setAttribute('aria-expanded', String(open));
  detail.hidden = !open;
  openId = open ? id : (openId === id ? null : openId);
  if (!open) return;
  const box = detail.querySelector('.alert-detail');
  box.innerHTML = '<p class="card-note"><span class="skeleton">Loading the scores around this alert</span></p>';
  try {
    const data = await getJSON(config.urls.detail.replace('/0/', `/${id}/`));
    renderDetail(box, data);
  } catch (err) {
    box.innerHTML = `<p class="notice error">Could not load this alert: ${esc(err.message)}.</p>`;
  }
}

// One deviation panel: the "What changed" bars for one 60 s window.
function deviationPanel(title, devs, scale, seconds) {
  const n = Math.max(0, ...devs.map((d) => d.n));
  const coverage = n < seconds ? `<p class="card-note">${n} of ${seconds} seconds have readings.</p>` : '';
  return `<div>
    <h3 class="detail-title">${esc(title)}</h3>
    <div class="changes">${devs.map((d) => {
      const half = d.z === null ? 0 : Math.min(Math.abs(d.z) / scale, 1) * 50;
      const left = d.z === null || d.z >= 0 ? 50 : 50 - half;
      return `<div class="change-row">
        <div class="change-head"><span class="change-name">${esc(d.name)}</span>
          <span class="change-z num">${d.z === null ? '—' : `${fmt.signed(d.z, 1)}${nb}σ`}</span></div>
        <div class="change-bar" aria-hidden="true"><div class="change-fill" style="left:${left}%;width:${half}%"></div></div>
        <div class="change-meta num"><span>Baseline ${fmt.fixed(d.baseline_mean, d.digits)}${nb}${d.unit}</span>
          <span>${d.n ? `Latest ${fmt.fixed(d.latest, d.digits)}${nb}${d.unit}` : 'No readings'}</span></div>
      </div>`;
    }).join('')}</div>
    ${coverage}
  </div>`;
}

function renderDetail(box, data) {
  const start = Date.parse(data.episode.started_at);
  const end = data.episode.ended_at ? Date.parse(data.episode.ended_at) : Date.parse(data.window_end);
  const xMin = Date.parse(data.window_start);
  const xMax = Date.parse(data.window_end);
  const seconds = data.deviation_seconds;
  const all = [...data.deviations, ...data.deviations_after].filter((d) => d.z !== null).map((d) => Math.abs(d.z));
  const scale = Math.max(5, Math.ceil(Math.max(0, ...all)));
  const shortAlert = data.episode.ended_at && data.episode.duration_seconds < seconds
    ? ` The alert lasted ${fmt.duration(data.episode.duration_seconds)}; the window still covers the ${seconds}${nb}s after its start.` : '';
  box.innerHTML = `
    <div class="detail-grid">
      <div>
        <h3 class="detail-title">Score from ${data.episode.mode === 'replay' ? 'the recording, ' : ''}2 min before to 2 min after the start</h3>
        <div class="chart-box small"><canvas role="img" aria-label="Score around the alert start"></canvas></div>
        <p class="card-note">${data.scores.length} stored seconds in this window${data.episode.mode === 'replay' ? ' (replay, not live data)' : ''}.</p>
      </div>
      ${deviationPanel(`Deviation in the ${seconds} s before the start`, data.deviations, scale, seconds)}
      ${deviationPanel(`Deviation in the first ${seconds} s of the alert`, data.deviations_after, scale, seconds)}
      <p class="card-note detail-foot">Both windows use the same calculation: the mean over the window minus the training mean, in training standard deviations. Before: the ${seconds}${nb}s up to and including the start. First ${seconds}${nb}s of the alert: the ${seconds}${nb}s after the start.${shortAlert} Bar scale ±${scale}${nb}σ. This is data, not a diagnosis.</p>
    </div>`;
  const chart = createScoreChart(box.querySelector('canvas'), () => {});
  chart.update({
    points: data.scores.map((s) => ({ x: Date.parse(s.timestamp), y: s.score })),
    threshold: data.threshold,
    episodes: [{ start, end: Math.min(end, xMax) }],
    alertStarts: [start],
    playhead: NaN, xMin, xMax, narrow: window.matchMedia('(max-width: 600px)').matches,
  });
}

load();
