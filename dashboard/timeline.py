"""
State timeline: consecutive segments (Offline, Idle, Warm-up, Running, Normal,
Alert, Not scored) derived only from stored scores and readings.

Pure functions, no database access; the views pass the rows in.

Every stored score row stands for the one-second window that starts at its
timestamp. Consecutive rows of the same kind are merged. Two consecutive rows
more than MAX_GAP_SECONDS apart leave a gap: it is "Offline" when no reading at
all was stored in it, and "Not scored" when readings exist but were not scored
(for example while the scorer was stopped). Nothing outside the stored rows is
invented: time before the first row is only marked Offline when an earlier row
proves the machine had been reporting before, and time after the last row only
when the reading is older than the live offline limit.
"""
from datetime import timedelta

from dashboard.ml.constants import MAX_GAP_SECONDS

ROW = timedelta(seconds=1)

LABELS = {
    'offline': 'Offline',
    'unscored': 'Not scored',
    'idle': 'Idle',
    'warming': 'Warm-up',
    'running': 'Running',
    'normal': 'Normal',
    'alert': 'Alert',
}


def row_kind(machine_state, score, alert_active):
    """Kind of one stored second."""
    if alert_active:
        return 'alert'
    if machine_state == 'idle':
        return 'idle'
    if machine_state == 'warming_up':
        return 'warming'
    if machine_state == 'running':
        return 'running' if score is None else 'normal'
    return 'unscored'


def build_segments(rows, range_start, range_end, *, previous_ts=None, offline_after=None,
                   readings_between=None, max_gap=MAX_GAP_SECONDS):
    """
    rows: (timestamp, machine_state, score, alert_active) sorted by timestamp,
          all inside [range_start, range_end].
    previous_ts: timestamp of the last stored row before range_start, if any.
    offline_after: seconds without a row after which the time up to range_end is
          Offline (live only; None for a finished recording).
    readings_between(start, end) -> bool: whether readings were stored in a gap.
    Returns a list of {'kind', 'label', 'start', 'end'} clipped to the range.
    """
    gap_limit = timedelta(seconds=max_gap)

    def gap_kind(start, end):
        return 'unscored' if readings_between and readings_between(start, end) else 'offline'

    segments = []

    def add(kind, start, end):
        start, end = max(start, range_start), min(end, range_end)
        if end <= start:
            return
        if segments and segments[-1]['kind'] == kind and segments[-1]['end'] >= start:
            segments[-1]['end'] = max(segments[-1]['end'], end)
        else:
            segments.append({'kind': kind, 'start': start, 'end': end})

    # Before the first row: only when an earlier row shows the machine was reporting.
    first_ts = rows[0][0] if rows else None
    if previous_ts is not None:
        gap_start = previous_ts + ROW
        gap_end = first_ts if first_ts is not None else range_end
        if (gap_end - previous_ts) > gap_limit and (
                first_ts is not None or offline_after is None
                or (range_end - previous_ts).total_seconds() > offline_after):
            add(gap_kind(gap_start, gap_end), gap_start, gap_end)

    prev_ts = None
    for ts, machine_state, score, alert_active in rows:
        if prev_ts is not None and ts - prev_ts > gap_limit:
            add(gap_kind(prev_ts + ROW, ts), prev_ts + ROW, ts)
        elif prev_ts is not None and segments and segments[-1]['end'] < min(ts, range_end):
            segments[-1]['end'] = min(ts, range_end)   # a short gap belongs to the previous second's state
        kind = row_kind(machine_state, score, alert_active)
        end = ts + ROW
        add(kind, ts, end)
        prev_ts = ts

    # After the last row: Offline once the newest reading is older than the live limit.
    if prev_ts is not None and offline_after is not None:
        if (range_end - prev_ts).total_seconds() > offline_after:
            add(gap_kind(prev_ts + ROW, range_end), prev_ts + ROW, range_end)

    for s in segments:
        s['label'] = LABELS[s['kind']]
    return segments


def to_json(segments):
    return [{
        'kind': s['kind'], 'label': s['label'],
        'start': s['start'].isoformat(), 'end': s['end'].isoformat(),
        'seconds': round((s['end'] - s['start']).total_seconds(), 1),
    } for s in segments]
