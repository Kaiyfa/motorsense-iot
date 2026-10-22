"""
Calculations behind the Sensors, Alerts, Maintenance and Evaluation tabs.

Pure functions, no database access: the views pass stored rows in. Nothing here
invents a value; every result is derived from the rows or files it is given.
"""
import math
from datetime import timedelta

from dashboard.ml import dataset
from dashboard.ml.constants import MAX_GAP_SECONDS

# Model feature -> (SensorData field, display name, unit, digits)
FEATURES = {
    'vib_rms_g': ('vibration_rms', 'Vibration RMS', 'g', 3),
    'vib_peak_g': ('vibration_peak', 'Vibration peak', 'g', 3),
    'current': ('current', 'Current', 'A', 3),
}
assert list(FEATURES) == dataset.FEATURES

DEVIATION_WINDOW_SECONDS = 60


# --------------------------------------------------------------------------- deviations

def window_deviations(readings, baseline, end, seconds=DEVIATION_WINDOW_SECONDS):
    """
    The "What changed" calculation: for each model feature, the mean of the readings
    in (end - seconds, end] minus the training mean, in training standard deviations.

    readings: iterable of dicts with 'timestamp' and the SensorData fields.
    baseline: {feature: {'mean', 'std'}} from the saved model's scaler.
    Returns a list of {feature, name, unit, n, mean, latest, z, baseline_mean}.
    """
    start = end - timedelta(seconds=seconds)
    rows = [r for r in readings if start < r['timestamp'] <= end]
    rows.sort(key=lambda r: r['timestamp'])
    out = []
    for feature, (field, name, unit, digits) in FEATURES.items():
        values = [r[field] for r in rows if r[field] is not None and math.isfinite(r[field])]
        base = (baseline or {}).get(feature)
        mean = sum(values) / len(values) if values else None
        out.append({
            'feature': feature, 'name': name, 'unit': unit, 'digits': digits,
            'n': len(values),
            'mean': mean,
            'latest': values[-1] if values else None,
            'baseline_mean': base['mean'] if base else None,
            'z': (mean - base['mean']) / base['std'] if base and mean is not None else None,
        })
    return out


def largest_deviation(deviations):
    usable = [d for d in deviations if d['z'] is not None]
    return max(usable, key=lambda d: abs(d['z'])) if usable else None


# --------------------------------------------------------------------------- sensors

def data_quality(timestamps, range_start, range_end, last_reading, max_gap=MAX_GAP_SECONDS):
    """
    timestamps: sorted reading times inside [range_start, range_end].
    Returns readings per minute over the range, the number of gaps longer than
    max_gap seconds between consecutive readings, the longest gap, and the seconds
    from the last reading to range_end.
    """
    minutes = max((range_end - range_start).total_seconds() / 60, 1e-9)
    gaps = [(b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:])]
    long_gaps = [g for g in gaps if g > max_gap]
    return {
        'readings': len(timestamps),
        'readings_per_minute': round(len(timestamps) / minutes, 2),
        'gaps_over_limit': len(long_gaps),
        'gap_limit_seconds': max_gap,
        'longest_gap_seconds': round(max(gaps), 1) if gaps else None,
        'seconds_since_last_reading': (round((range_end - last_reading).total_seconds(), 1)
                                       if last_reading is not None else None),
    }


def downsample(times, values, max_points):
    """
    Reduce a series to at most about max_points by keeping, per bucket, the minimum
    and the maximum (so peaks stay visible). Gaps (None) are kept as breaks.
    Returns (times, values). Series that are short enough are returned unchanged.
    """
    n = len(times)
    if n <= max_points:
        return list(times), list(values)
    buckets = max(max_points // 2, 1)
    size = math.ceil(n / buckets)
    out_t, out_v = [], []
    for start in range(0, n, size):
        idx = [i for i in range(start, min(start + size, n)) if values[i] is not None]
        if not idx:
            out_t.append(times[start])
            out_v.append(None)
            continue
        lo = min(idx, key=lambda i: values[i])
        hi = max(idx, key=lambda i: values[i])
        for i in sorted({lo, hi}):
            out_t.append(times[i])
            out_v.append(values[i])
    return out_t, out_v


# --------------------------------------------------------------------------- maintenance

def next_inspection_due(last_inspection_at, interval_days):
    """Last logged inspection plus the operator's interval, or None if either is missing."""
    if last_inspection_at is None or not interval_days:
        return None
    return last_inspection_at + timedelta(days=interval_days)


def alerts_without_inspection(alerts, inspection_times):
    """
    alerts: iterable of objects or dicts with 'started_at'.
    inspection_times: performed_at of logged inspections.
    Returns the alerts that have no inspection logged at or after their start.
    """
    latest = max(inspection_times, default=None)

    def started(a):
        return a['started_at'] if isinstance(a, dict) else a.started_at

    return [a for a in alerts if latest is None or latest < started(a)]


# --------------------------------------------------------------------------- evaluation

METHOD_NAMES = {
    'ae_all': 'Autoencoder, all features',
    'ae_vibration': 'Autoencoder, vibration only',
    'ae_current': 'Autoencoder, current only',
    'z_current': '|z| of current',
    'z_vib_rms': '|z| of vib_rms_g',
}
METHOD_INPUTS = {
    'ae_all': 'vib_rms_g, vib_peak_g, current',
    'ae_vibration': 'vib_rms_g, vib_peak_g',
    'ae_current': 'current',
    'z_current': 'current',
    'z_vib_rms': 'vib_rms_g',
}
SUMMARY_COLUMNS = [
    # key in metrics summary, column title, digits
    ('threshold', 'Threshold', 3),
    ('per_second.tp', 'TP', 1),
    ('per_second.fp', 'FP', 1),
    ('per_second.fn', 'FN', 1),
    ('per_second.tn', 'TN', 1),
    ('per_second.precision', 'Precision', 3),
    ('per_second.recall', 'Recall', 3),
    ('per_second.false_positive_rate', 'FPR', 3),
    ('validation_episodes', 'Validation episodes', 1),
    ('normal_test_episodes', 'Normal test episodes', 1),
    ('fault_sessions_alerted', 'Fault sessions alerted (of 3)', 1),
    ('mean_delay_alerted_faults', 'Delay s', 1),
    ('per_session.precision', 'Session precision', 3),
    ('per_session.recall', 'Session recall', 3),
]


def _fmt(value, digits):
    if value is None:
        return 'n/a'
    if float(value).is_integer():
        return f'{value:g}'
    return f'{value:.{digits}f}'


def method_rows(metrics):
    """One row per method: cells as 'mean' and, for seeded methods, '±std' and 'min–max'."""
    rows = []
    for key, data in metrics['methods'].items():
        seeded = 'seeds' in data
        cells = []
        for col, title, digits in SUMMARY_COLUMNS:
            s = data['summary'][col]
            if s['mean'] is None:
                cells.append({'value': 'n/a', 'spread': ''})
                continue
            spread = ''
            if seeded and s.get('std') is not None:
                spread = (f"±{s['std']:.{digits}f} ({_fmt(s['min'], digits)}–{_fmt(s['max'], digits)})"
                          if s['std'] else 'same for all seeds')
            cells.append({'value': _fmt(s['mean'], digits), 'spread': spread})
        rows.append({
            'key': key, 'name': METHOD_NAMES.get(key, key), 'inputs': METHOD_INPUTS.get(key, ''),
            'seeded': seeded, 'seeds': len(data['seeds']) if seeded else 0, 'cells': cells,
        })
    return rows


def comparison_statements(metrics):
    """
    Plain statements derived from metrics.json, so the wording follows the numbers.
    Returns a list of sentences.
    """
    m = metrics['methods']

    def mean(method, key):
        return m[method]['summary'][key]['mean']

    out = []
    z_alerted, ae_alerted = mean('z_current', 'fault_sessions_alerted'), mean('ae_all', 'fault_sessions_alerted')
    z_normal, ae_normal = mean('z_current', 'normal_test_episodes'), mean('ae_all', 'normal_test_episodes')
    if z_alerted == ae_alerted == 3 and z_normal == ae_normal == 0:
        out.append(
            'Per session, a fixed threshold on current (|z| of current) performs as well as the autoencoder on '
            'this fault: both alert on all 3 fault sessions and raise no alert on the normal test session, with '
            f"a delay of {_fmt(mean('z_current', 'mean_delay_alerted_faults'), 1)} s and "
            f"{_fmt(mean('ae_all', 'mean_delay_alerted_faults'), 1)} s.")
    else:
        out.append('Per session, the fixed threshold on current and the autoencoder differ on this fault; '
                   'see the table.')
    z_fp, ae_fp = mean('z_current', 'per_second.fp'), mean('ae_all', 'per_second.fp')
    if z_fp != ae_fp:
        out.append(
            f"Per second, the fixed threshold on current has {_fmt(z_fp, 1)} false-positive seconds on the normal "
            f"test session (rate {_fmt(mean('z_current', 'per_second.false_positive_rate'), 3)}) and the "
            f"autoencoder {_fmt(ae_fp, 1)}; neither turns them into an alert.")
    v = m['ae_vibration']['summary']['fault_sessions_alerted']
    zv = mean('z_vib_rms', 'fault_sessions_alerted')
    out.append(
        f"Vibration alone detects the fault only partly: the vibration-only autoencoder alerts on "
        f"{_fmt(v['min'], 1)} to {_fmt(v['max'], 1)} of 3 fault sessions depending on the seed "
        f"(per-second recall {_fmt(mean('ae_vibration', 'per_second.recall'), 3)}), and |z| of vib_rms_g on "
        f"{_fmt(zv, 1)} of 3.")
    return out


def score_path(scores, threshold, width, height, pad=4):
    """
    SVG geometry for a small multiple: the score on a logarithmic axis.
    scores: list of float or None (unscored). Returns dict with 'path', 'threshold_y',
    'alert_spans' (x ranges) and the axis range.
    """
    values = [s for s in scores if s is not None and s > 0]
    if not values:
        return None
    lo = 10 ** math.floor(math.log10(min(values + [threshold])))
    hi = 10 ** math.ceil(math.log10(max(values + [threshold]) * 1.05))
    n = max(len(scores) - 1, 1)

    def y(v):
        frac = (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        return round(pad + (1 - frac) * (height - 2 * pad), 2)

    d, pen = [], False
    for i, s in enumerate(scores):
        if s is None or s <= 0:
            pen = False
            continue
        x = round(i / n * width, 2)
        d.append(f"{'L' if pen else 'M'}{x},{y(s)}")
        pen = True
    return {'path': ''.join(d), 'threshold_y': y(threshold), 'lo': lo, 'hi': hi}
