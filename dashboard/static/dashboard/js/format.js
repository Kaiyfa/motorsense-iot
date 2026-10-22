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

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const shortTimeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
const dateFmt = new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric' });

export const clock = (ms) => timeFmt.format(new Date(ms));
export const shortClock = (ms) => shortTimeFmt.format(new Date(ms));
export const date = (ms) => dateFmt.format(new Date(ms));

export function timezoneLabel() {
  const minutes = -new Date().getTimezoneOffset();
  const sign = minutes >= 0 ? '+' : MINUS;
  const h = Math.floor(Math.abs(minutes) / 60);
  const m = Math.abs(minutes) % 60;
  return `UTC${sign}${h}${m ? ':' + String(m).padStart(2, '0') : ''}`;
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
