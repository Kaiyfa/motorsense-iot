"""
Reproduce the negative findings in docs/evaluation_plan.md from the raw Pi CSV logs.

    python analysis/negative_findings.py [--data DIR]

By default it reads the published recordings in data/recordings/raw (the raw Pi
CSV logs, copied unchanged). Only the Python standard library is used.

Plateau rule, applied to every session:
  - a session that has a matching "<label>_warmup" segment (the long sessions):
    all windows of the session itself, i.e. everything after the warm-up label;
  - any other session (the 180 s tests, and the shorter or unlabelled-warm-up
    runs): the last 90 windows.
Standard deviations are sample standard deviations (n - 1).

Like with like: vibration and frequency bands are compared only between runs in the
same phase, i.e. both measured after their warm-up segment, or both short runs of the
same length (so the last 90 windows sit at the same time after the motors start).
Otherwise the vibration and band cells are null ("n/a, runs not comparable"); current
is always compared. Each comparison names why its reference was chosen.

Normal spread: for the five valid normal sessions (r5_normal_01, 02, 03, 04_redo, 05;
windows after the warm-up segment only), the mean of each signal per session and,
across the sessions, the minimum, maximum and relative spread
(maximum - minimum) / mean of the session means.
"""
import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

PLATEAU_WINDOWS = 90
FRICTION_MIN_CURRENT_MA = 500.0
NOT_COMPARABLE = 'runs not comparable'

SIGNALS = ['vib_rms_g', 'vib_peak_g', 'current_ma']
BANDS = ['band_1_6_g', 'band_6_20_g', 'band_20_50_g', 'band_50_100_g']
VIBRATION = ['vib_rms_g', 'vib_peak_g'] + BANDS

NORMAL_SESSIONS = ['r5_normal_01', 'r5_normal_02', 'r5_normal_03', 'r5_normal_04_redo', 'r5_normal_05']

COMPARISONS = [
    {'title': 'Baseline shift after mechanical handling',
     'references': ['r2_normal_01'], 'tests': ['r3_normal_01', 'r4_band_normal_a'], 'min_current': None,
     'reason': 'r2_normal_01 is the normal session recorded before the rig was handled; r3_normal_01 and '
               'r4_band_normal_a are later normal runs with no fault applied. Vibration is compared only with '
               'r3_normal_01, which is also measured after its warm-up segment; r4_band_normal_a is a 240 s run.'},
    {'title': 'Imbalance (taped weights)',
     'references': ['r2_test_baseline'], 'tests': ['r3_test_fault', 'r3_test_fault2'], 'min_current': None,
     'reason': 'r2_test_baseline is the normal 180 s run recorded the same morning, before the imbalance runs: '
               'same period and same run length, so the last 90 windows sit at the same time after the start.'},
    {'title': 'Imbalance, frequency bands',
     'references': ['r4_band_normal_a'], 'tests': ['r4_band_fault_a'], 'min_current': None,
     'reason': 'r4_band_normal_a is the normal 240 s run with frequency bands recorded just before '
               'r4_band_fault_a: same period and same run length.'},
    {'title': 'Loosened motor mount',
     'references': ['r2_test_baseline'], 'tests': ['r3_test_loose'], 'min_current': None,
     'reason': 'r2_test_baseline is the normal 180 s run recorded the same morning, before the loose-mount run: '
               'same period and same run length.'},
    {'title': 'Friction by hand (only seconds with current above 500 mA)',
     'references': ['r4_band_normal_a'], 'tests': ['r4_tune', 'r4_tune2'], 'min_current': FRICTION_MIN_CURRENT_MA,
     'reason': 'r4_band_normal_a is the normal run of the same period. The friction runs are 60 s long and the '
               'reference 240 s, so only current is compared.'},
    {'title': 'Open motor lead',
     'references': ['r4_band_normal_a'], 'tests': ['r4_test_open'], 'min_current': None,
     'reason': 'r4_band_normal_a is the normal run of the same period. r4_test_open is a 180 s run and the '
               'reference 240 s, so only current is compared.'},
]


def to_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_sessions(data_dir):
    """Return {label: [row, ...]} sorted by timestamp, from every CSV in data_dir."""
    sessions = {}
    files = sorted(Path(data_dir).glob('*.csv'))
    if not files:
        sys.exit(f'No CSV files found in {data_dir}')

    for path in files:
        with path.open(newline='') as f:
            reader = csv.reader(f)
            try:
                header = [h.strip().rstrip('\r') for h in next(reader)]
            except StopIteration:
                continue
            for raw in reader:
                if not raw:
                    continue
                values = dict(zip(header, (v.rstrip('\r') for v in raw)))
                label = values.get('label', '').strip()
                if not label:
                    continue
                row = {'timestamp_utc': values.get('timestamp_utc', '')}
                for name in SIGNALS + BANDS:
                    row[name] = to_float(values.get(name))
                sessions.setdefault(label, []).append(row)

    for rows in sessions.values():
        rows.sort(key=lambda r: r['timestamp_utc'])
    return sessions


def run_windows(label, sessions):
    """All windows of the run: the session plus its _warmup segment, if any."""
    return len(sessions[label]) + len(sessions.get(f'{label}_warmup', []))


def phase(label, sessions):
    """When the plateau windows were measured: after a warm-up segment, or at the end of a short run."""
    if f'{label}_warmup' in sessions:
        return 'after the warm-up segment'
    return f'last {PLATEAU_WINDOWS} windows of a {run_windows(label, sessions)} s run'


def plateau(label, sessions):
    rows = sessions[label]
    if f'{label}_warmup' in sessions:
        return rows, 'all windows after warm-up'
    return rows[-PLATEAU_WINDOWS:], f'last {PLATEAU_WINDOWS} windows'


def summarize(rows):
    """Mean, std, min, max per signal."""
    summary = {'n': len(rows)}
    for name in SIGNALS + BANDS:
        values = [r[name] for r in rows if r[name] is not None]
        summary[name] = {
            'mean': statistics.fmean(values) if values else None,
            'std': statistics.stdev(values) if len(values) > 1 else None,
            'min': min(values) if values else None,
            'max': max(values) if values else None,
        }
    return summary


def fmt(stat, digits):
    if stat['mean'] is None:
        return 'n/a'
    std = f"{stat['std']:.{digits}f}" if stat['std'] is not None else 'n/a'
    return f"{stat['mean']:.{digits}f} ± {std}"


def pct(test, ref):
    if test is None or ref is None or ref == 0:
        return 'n/a'
    return f'{(test - ref) / ref * 100:+.1f}%'


def pct_value(test, ref):
    """The printed percentage as a number (one decimal), or None."""
    if test is None or ref is None or ref == 0:
        return None
    return round((test - ref) / ref * 100, 1)


def rounded(stat, digits):
    return {k: (round(v, digits) if isinstance(v, float) else v) for k, v in stat.items()}


def run_comparison(comparison, sessions):
    """Print one comparison and return the same numbers as a dict (for the JSON file)."""
    title, references, tests = comparison['title'], comparison['references'], comparison['tests']
    min_current = comparison['min_current']
    print(f'\n=== {title} ===')
    print(f"  Reference: {comparison['reason']}")
    record = {'title': title, 'references': references, 'tests': tests, 'reference_reason': comparison['reason'],
              'min_current_ma': min_current, 'missing': [], 'sessions': [], 'changes': []}
    summaries, phases = {}, {}
    for label in references + tests:
        if label not in sessions:
            print(f'  MISSING: label {label!r} not found in the raw data, skipped')
            record['missing'].append(label)
            continue
        rows, rule = plateau(label, sessions)
        if min_current is not None:
            rows = [r for r in rows if r['current_ma'] is not None and r['current_ma'] > min_current]
            rule += f', current > {min_current:g} mA'
        if not rows:
            print(f'  {label}: no windows left after the plateau rule ({rule}), skipped')
            continue
        phases[label] = phase(label, sessions)
        summaries[label] = (summarize(rows), rule, label in references)

    if not summaries:
        return record

    print(f"  {'session':<18} {'role':<9} {'n':>3}  {'vib_rms_g':>17}  {'vib_peak_g':>17}  "
          f"{'current_ma':>15}  {'current min..max':>16}  window rule; phase")
    for label, (s, rule, is_ref) in summaries.items():
        cur = s['current_ma']
        span = f"{cur['min']:.0f}..{cur['max']:.0f}" if cur['min'] is not None else 'n/a'
        print(f"  {label:<18} {'reference' if is_ref else 'test':<9} {s['n']:>3}  "
              f"{fmt(s['vib_rms_g'], 4):>17}  {fmt(s['vib_peak_g'], 4):>17}  "
              f"{fmt(cur, 1):>15}  {span:>16}  {rule}; {phases[label]}")
        record['sessions'].append({
            'label': label, 'role': 'reference' if is_ref else 'test', 'windows': s['n'], 'rule': rule,
            'phase': phases[label], 'run_windows': run_windows(label, sessions),
            'vib_rms_g': rounded(s['vib_rms_g'], 4), 'vib_peak_g': rounded(s['vib_peak_g'], 4),
            'current_ma': rounded(cur, 1),
            'bands': ({b: round(s[b]['mean'], 4) for b in BANDS}
                      if all(s[b]['mean'] is not None for b in BANDS) else None),
        })

    banded = [label for label, (s, _, _) in summaries.items()
              if all(s[b]['mean'] is not None for b in BANDS)]
    if banded:
        print(f"\n  Band means (g)     {'1-6 Hz':>9} {'6-20 Hz':>9} {'20-50 Hz':>9} {'50-100 Hz':>9}")
        for label in banded:
            s = summaries[label][0]
            print(f"  {label:<18} " + ' '.join(f"{s[b]['mean']:>9.4f}" for b in BANDS))
    missing_bands = [label for label in summaries if label not in banded]
    if missing_bands:
        print(f"  No band columns: {', '.join(missing_bands)}")

    ref_labels = [label for label, (_, _, is_ref) in summaries.items() if is_ref]
    test_labels = [label for label, (_, _, is_ref) in summaries.items() if not is_ref]
    if ref_labels and test_labels:
        print('\n  Change of the test mean relative to each reference mean:')
        for test in test_labels:
            t = summaries[test][0]
            for ref in ref_labels:
                r = summaries[ref][0]
                both_banded = test in banded and ref in banded
                names = SIGNALS + (BANDS if both_banded else [])
                change = {'test': test, 'reference': ref,
                          'percent': {n: pct_value(t[n]['mean'], r[n]['mean']) for n in names}}
                if phases[test] != phases[ref]:
                    skipped = [n for n in names if n in VIBRATION]
                    change['percent'].update({n: None for n in skipped})
                    change.update({'not_compared': skipped, 'not_compared_reason': NOT_COMPARABLE,
                                   'not_compared_detail': f'{test}: {phases[test]}; {ref}: {phases[ref]}'})
                    print(f"    {test} vs {ref}: current_ma {pct(t['current_ma']['mean'], r['current_ma']['mean'])}; "
                          f"vibration{' and bands' if both_banded else ''} n/a ({NOT_COMPARABLE}: "
                          f"{change['not_compared_detail']})")
                else:
                    parts = [f"{name} {pct(t[name]['mean'], r[name]['mean'])}" for name in names]
                    print(f"    {test} vs {ref}: " + ', '.join(parts))
                record['changes'].append(change)
    return record


def normal_spread(sessions):
    """Per-session means of the five valid normal sessions (after warm-up) and their spread."""
    print('\n=== Spread between normal sessions (windows after the warm-up segment) ===')
    rows, missing = [], []
    for label in NORMAL_SESSIONS:
        if label not in sessions:
            print(f'  MISSING: label {label!r} not found in the raw data, skipped')
            missing.append(label)
            continue
        s = summarize(sessions[label])
        rows.append({'label': label, 'windows': s['n'],
                     **{n: (round(s[n]['mean'], 4 if n != 'current_ma' else 1) if s[n]['mean'] is not None else None)
                        for n in SIGNALS + BANDS},
                     '_exact': {n: s[n]['mean'] for n in SIGNALS + BANDS}})
    print(f"  {'session':<18} {'n':>3}  {'vib_rms_g':>9}  {'vib_peak_g':>10}  {'current_ma':>10}")
    for r in rows:
        print(f"  {r['label']:<18} {r['windows']:>3}  {r['vib_rms_g']:>9.4f}  {r['vib_peak_g']:>10.4f}  "
              f"{r['current_ma']:>10.1f}")
    summary = {}
    for n in SIGNALS + BANDS:
        values = [r['_exact'][n] for r in rows if r['_exact'][n] is not None]
        if len(values) < 2:
            summary[n] = None
            continue
        digits = 1 if n == 'current_ma' else 4
        summary[n] = {'min': round(min(values), digits), 'max': round(max(values), digits),
                      'mean': round(statistics.fmean(values), digits),
                      'spread_percent': round((max(values) - min(values)) / statistics.fmean(values) * 100, 1)}
        print(f"  {n:<14} min {summary[n]['min']:>9}  max {summary[n]['max']:>9}  "
              f"spread {summary[n]['spread_percent']:.1f}%")
    for r in rows:
        del r['_exact']
    return {'sessions': rows, 'missing': missing, 'summary': summary,
            'definition': 'relative spread = (maximum - minimum) / mean of the session means, over the five '
                          'valid normal sessions, windows after the warm-up segment only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data', default=str(Path(__file__).resolve().parents[1] / 'data' / 'recordings' / 'raw'),
                        help='Directory with the raw Pi CSV logs (default: data/recordings/raw)')
    parser.add_argument('--json', default=str(Path(__file__).resolve().parents[1] / 'results' / 'negative_findings.json'),
                        help='Where to write the numbers as JSON (default: results/negative_findings.json)')
    args = parser.parse_args()

    data_dir = Path(args.data).expanduser()
    if not data_dir.is_dir():
        sys.exit(f'Not a directory: {data_dir}')

    sessions = load_sessions(data_dir)
    print(f'Raw data: {data_dir} ({len(sessions)} labels)')
    print(f'Plateau: long sessions use all windows after the warm-up label; '
          f'other sessions use the last {PLATEAU_WINDOWS} windows. std = sample std (n - 1).')

    records = [run_comparison(comparison, sessions) for comparison in COMPARISONS]
    spread = normal_spread(sessions)

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w') as f:
        json.dump({
            'script': 'analysis/negative_findings.py',
            'source': 'raw Pi CSV logs (not in the repository)',
            'plateau_rule': (f'sessions with a _warmup segment: all windows after it; other sessions: the last '
                             f'{PLATEAU_WINDOWS} windows; friction: only seconds with current above '
                             f'{FRICTION_MIN_CURRENT_MA:g} mA'),
            'std': 'sample standard deviation (n - 1)',
            'percent': 'change of the test mean relative to the reference mean, one decimal, as printed',
            'like_with_like': ('vibration and frequency bands are compared only between runs in the same phase '
                               '(both after their warm-up segment, or both short runs of the same length); '
                               'otherwise they are null; current is always compared'),
            'comparisons': records,
            'normal_spread': spread,
        }, f, indent=2)
    print(f'\nWrote {out}')


if __name__ == '__main__':
    main()
