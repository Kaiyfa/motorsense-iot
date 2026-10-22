// Number, time and duration formatting. All values are shown with tabular numerals (CSS).

const MINUS = '−';
// Non-breaking space: a number and its unit never end up on different lines.
export const NBSP = '\u00a0';

export function fixed(value, digits) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const text = Math.abs(value).toFixed(digits);
  return (value < 0 && Number(text) !== 0 ? MINUS : '') + text;
}

export function signed(value, digits) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const text = Math.abs(value).toFixed(digits);
  if (Number(text) === 0) return text;
  return (value < 0 ? MINUS : '+') + text;
}

// Scores span several orders of magnitude: three significant digits.
export function score(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (value >= 100) return value.toFixed(0);
  if (value >= 10) return value.toFixed(1);
  if (value >= 1) return value.toFixed(2);
  return value.toPrecision(3);
}

export function duration(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}${NBSP}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}${NBSP}min ${String(s % 60).padStart(2, '0')}${NBSP}s`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}${NBSP}h ${String(m % 60).padStart(2, '0')}${NBSP}min`;
  return `${Math.floor(h / 24)}${NBSP}days`;
}

export function ago(seconds) {
  if (seconds === null || seconds === undefined) return 'never';
  return `${duration(seconds)} ago`;
}

// Every date and time is shown in one time zone: the server's (settings.TIME_ZONE), which
// base.html puts on <body data-timezone> and names once in the header. One format
// everywhere: 22 Oct 2026, 07:23:31 (the same as the server-side |msdatetime filter).
export const TIME_ZONE = globalThis.document?.body?.dataset.timezone || undefined;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const partsFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIME_ZONE, year: 'numeric', month: 'numeric', day: 'numeric',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});

function parts(ms) {
  const out = {};
  for (const p of partsFmt.formatToParts(new Date(ms))) if (p.type !== 'literal') out[p.type] = p.value;
  return out;
}

export const clock = (ms) => { const p = parts(ms); return `${p.hour}:${p.minute}:${p.second}`; };
export const shortClock = (ms) => { const p = parts(ms); return `${p.hour}:${p.minute}`; };
export const date = (ms) => { const p = parts(ms); return `${Number(p.day)} ${MONTHS[Number(p.month) - 1]} ${p.year}`; };
export const dateTime = (ms) => `${date(ms)}, ${clock(ms)}`;

// Offset of the display time zone from UTC at ms, in milliseconds (for round tick times).
export function zoneOffsetMs(ms) {
  const p = parts(ms);
  const asUTC = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute),
    Number(p.second));
  return asUTC - Math.floor(ms / 1000) * 1000;
}

// Elapsed time as m:ss (or h:mm:ss)
export function mmss(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${rest}` : `${m}:${rest}`;
}
