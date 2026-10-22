"""
Reproduce the negative findings in docs/evaluation_plan.md from the raw Pi CSV logs.

    python analysis/negative_findings.py ~/motorsense-raw-data

The raw CSVs live outside the repository and are never committed. Only the
Python standard library is used.

Plateau rule, applied to every session:
  - a session that has a matching "<label>_warmup" segment (the long sessions):
    all windows of the session itself, i.e. everything after the warm-up label;
  - any other session (the 180 s tests, and the shorter or unlabelled-warm-up
    runs): the last 90 windows.
Standard deviations are sample standard deviations (n - 1).

Runs shorter than the warm-up (fewer than WARMUP_WINDOWS rows in total) lie
entirely inside it, while the other sessions are compared at their plateau. For
them only current is reported; vibration and band values are left out (null in
the JSON, n/a in the printed output).
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
# The warm-up in windows (1 window = 1 s). Same value as WARMUP_SECONDS in
# dashboard/ml/constants.py (kept here so the script needs only the standard library;
# a test checks that they agree).
WARMUP_WINDOWS = 180
SHORT_RUN_REASON = 'run shorter than the warm-up'

SIGNALS = ['vib_rms_g', 'vib_peak_g', 'current_ma']
BANDS = ['band_1_6_g', 'band_6_20_g', 'band_20_50_g', 'band_50_100_g']

# (title, reference labels, test labels, minimum current in mA or None)
COMPARISONS = [
    ('Baseline shift after mechanical handling',
     ['r2_normal_01'], ['r3_normal_01', 'r4_band_normal_a'], None),
    ('Imbalance (taped weights)',
     ['r4_test_drag', 'r4_band_normal_a'], ['r3_test_fault', 'r3_test_fault2'], None),
    ('Imbalance, frequency bands',
     ['r4_band_normal_a'], ['r4_band_fault_a'], None),
    ('Loosened motor mount',
     ['r3_normal_01'], ['r3_test_loose'], None),
    ('Friction by hand (only seconds with current above 500 mA)',
     ['r3_normal_01', 'r4_band_normal_a'], ['r4_tune', 'r4_tune2'], FRICTION_MIN_CURRENT_MA),
    ('Open motor lead',
     ['r4_band_normal_a'], ['r4_test_open'], None),
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


def plateau(label, sessions):
    rows = sessions[label]
    if f'{label}_warmup' in sessions:
        return rows, 'all windows after warm-up'
    return rows[-PLATEAU_WINDOWS:], f'last {PLATEAU_WINDOWS} windows'


def summarize(rows, current_only=False):
    """Mean, std, min, max per signal; with current_only, every other signal is left empty."""
    summary = {'n': len(rows)}
    for name in SIGNALS + BANDS:
        values = [r[name] for r in rows if r[name] is not None] if not current_only or name == 'current_ma' else []
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


def run_comparison(title, references, tests, min_current, sessions):
    """Print one comparison and return the same numbers as a dict (for the JSON file)."""
    print(f'\n=== {title} ===')
    record = {'title': title, 'references': references, 'tests': tests,
              'min_current_ma': min_current, 'missing': [], 'sessions': [],
              'changes': [], 'reference_changes': []}
    summaries, short_runs, has_bands = {}, {}, {}
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
        short = run_windows(label, sessions) < WARMUP_WINDOWS
        has_bands[label] = all(any(r[b] is not None for r in rows) for b in BANDS)
        if short:
            short_runs[label] = run_windows(label, sessions)
            rule += f', run of {short_runs[label]} windows: {SHORT_RUN_REASON}, current only'
        summaries[label] = (summarize(rows, current_only=short), rule, label in references)

    if not summaries:
        return record

    print(f"  {'session':<18} {'role':<9} {'n':>3}  {'vib_rms_g':>17}  {'vib_peak_g':>17}  "
          f"{'current_ma':>15}  {'current min..max':>16}  window rule")
    for label, (s, rule, is_ref) in summaries.items():
        cur = s['current_ma']
        span = f"{cur['min']:.0f}..{cur['max']:.0f}" if cur['min'] is not None else 'n/a'
        print(f"  {label:<18} {'reference' if is_ref else 'test':<9} {s['n']:>3}  "
              f"{fmt(s['vib_rms_g'], 4):>17}  {fmt(s['vib_peak_g'], 4):>17}  "
              f"{fmt(cur, 1):>15}  {span:>16}  {rule}")
        record['sessions'].append({
            'label': label, 'role': 'reference' if is_ref else 'test', 'windows': s['n'], 'rule': rule,
            'vib_rms_g': rounded(s['vib_rms_g'], 4), 'vib_peak_g': rounded(s['vib_peak_g'], 4),
            'current_ma': rounded(cur, 1),
            'bands': ({b: round(s[b]['mean'], 4) for b in BANDS}
                      if all(s[b]['mean'] is not None for b in BANDS) else None),
            'run_windows': run_windows(label, sessions),
            'shorter_than_warmup': label in short_runs,
        })

    banded = [label for label, (s, _, _) in summaries.items()
              if all(s[b]['mean'] is not None for b in BANDS)]
    if banded:
        print(f"\n  Band means (g)     {'1-6 Hz':>9} {'6-20 Hz':>9} {'20-50 Hz':>9} {'50-100 Hz':>9}")
        for label in banded:
            s = summaries[label][0]
            print(f"  {label:<18} " + ' '.join(f"{s[b]['mean']:>9.4f}" for b in BANDS))
    missing_bands = [label for label in summaries if label not in banded and label not in short_runs]
    if missing_bands:
        print(f"  No band columns: {', '.join(missing_bands)}")
    if short_runs:
        print(f"  Vibration and bands n/a ({SHORT_RUN_REASON}, {WARMUP_WINDOWS} windows): "
              + ', '.join(f'{label} ({n} windows)' for label, n in short_runs.items()))

    ref_labels = [label for label, (_, _, is_ref) in summaries.items() if is_ref]
    test_labels = [label for label, (_, _, is_ref) in summaries.items() if not is_ref]
    if ref_labels and test_labels:
        print('\n  Change of the test mean relative to each reference mean:')
        for test in test_labels:
            t = summaries[test][0]
            for ref in ref_labels:
                r = summaries[ref][0]
                short = [label for label in (test, ref) if label in short_runs]
                if short:
                    print(f"    {test} vs {ref}: current_ma {pct(t['current_ma']['mean'], r['current_ma']['mean'])}; "
                          f"vibration and bands n/a ({SHORT_RUN_REASON}: {', '.join(short)})")
                    record['changes'].append({
                        'test': test, 'reference': ref,
                        'percent': {n: (pct_value(t[n]['mean'], r[n]['mean']) if n == 'current_ma' else None)
                                    for n in SIGNALS},
                        'not_compared': ([n for n in SIGNALS if n != 'current_ma']
                                         + (BANDS if has_bands[test] and has_bands[ref] else [])),
                        'not_compared_reason': SHORT_RUN_REASON,
                        'shorter_than_warmup': short,
                    })
                    continue
                parts = [f"{name} {pct(t[name]['mean'], r[name]['mean'])}" for name in SIGNALS]
                if test in banded and ref in banded:
                    parts += [f"{b} {pct(t[b]['mean'], r[b]['mean'])}" for b in BANDS]
                print(f"    {test} vs {ref}: " + ', '.join(parts))
                names = SIGNALS + (BANDS if test in banded and ref in banded else [])
                record['changes'].append({'test': test, 'reference': ref,
                                          'percent': {n: pct_value(t[n]['mean'], r[n]['mean']) for n in names}})

    if len(ref_labels) > 1:
        print('\n  Change between the references (no fault applied):')
        for i, first in enumerate(ref_labels):
            for second in ref_labels[i + 1:]:
                a, b = summaries[first][0], summaries[second][0]
                parts = [f"{name} {pct(b[name]['mean'], a[name]['mean'])}" for name in SIGNALS]
                print(f"    {second} vs {first}: " + ', '.join(parts))
                change = {'test': second, 'reference': first,
                          'percent': {n: pct_value(b[n]['mean'], a[n]['mean']) for n in SIGNALS}}
                short = [label for label in (second, first) if label in short_runs]
                if short:
                    change.update({'not_compared': [n for n in SIGNALS if n != 'current_ma'],
                                   'not_compared_reason': SHORT_RUN_REASON, 'shorter_than_warmup': short})
                record['reference_changes'].append(change)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('data_dir', help='Directory with the raw Pi CSV logs (e.g. ~/motorsense-raw-data)')
    parser.add_argument('--json', default=str(Path(__file__).resolve().parents[1] / 'results' / 'negative_findings.json'),
                        help='Where to write the numbers as JSON (default: results/negative_findings.json)')
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser()
    if not data_dir.is_dir():
        sys.exit(f'Not a directory: {data_dir}')

    sessions = load_sessions(data_dir)
    print(f'Raw data: {data_dir} ({len(sessions)} labels)')
    print(f'Plateau: long sessions use all windows after the warm-up label; '
          f'other sessions use the last {PLATEAU_WINDOWS} windows. std = sample std (n - 1).')

    records = [run_comparison(title, references, tests, min_current, sessions)
               for title, references, tests, min_current in COMPARISONS]

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
            'short_runs': (f'runs with fewer than {WARMUP_WINDOWS} windows in total lie inside the warm-up: only '
                           f'current is compared; vibration and band values are null'),
            'comparisons': records,
        }, f, indent=2)
    print(f'\nWrote {out}')


if __name__ == '__main__':
    main()
