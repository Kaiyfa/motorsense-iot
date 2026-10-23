"""
Print the results table of the README from results/metrics.json.

    python -m dashboard.ml.render_readme_results [--metrics results/metrics.json]

The README holds this output between the markers
<!-- results-table:start --> and <!-- results-table:end -->; a test fails if they differ.
Autoencoder cells give the mean over the seeds, and the range when the seeds differ.
"""
import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
START = '<!-- results-table:start -->'
END = '<!-- results-table:end -->'

METHODS = [
    ('ae_all', 'LSTM autoencoder, all three features'),
    ('ae_vibration', 'LSTM autoencoder, vibration only'),
    ('ae_current', 'LSTM autoencoder, current only'),
    ('z_current', 'Fixed threshold on the current z-score'),
    ('z_vib_rms', 'Fixed threshold on the vibration RMS z-score'),
]
# metrics key, column title, decimals
COLUMNS = [
    ('fault_sessions_alerted', 'Fault sessions alerted (of 3)', 1),
    ('normal_test_episodes', 'Alerts on the normal test session', 1),
    ('mean_delay_alerted_faults', 'Mean delay to the first alert (s)', 1),
    ('per_second.recall', 'Per-second recall', 3),
    ('per_second.fp', 'False-positive seconds on the normal test session', 1),
]


def _number(value, decimals):
    text = f'{value:.{decimals}f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text


def cell(summary, decimals):
    mean, low, high = summary['mean'], summary.get('min'), summary.get('max')
    if mean is None:
        return 'n/a'
    if low is None or high is None or low == high:
        return _number(mean, decimals)
    return f'{_number(mean, decimals)} ({_number(low, decimals)} to {_number(high, decimals)})'


def render(metrics):
    seeds = metrics['settings']['seeds']
    lines = ['| Detector | Seeds | ' + ' | '.join(title for _, title, _ in COLUMNS) + ' |',
             '|---|---|' + '---|' * len(COLUMNS)]
    for key, name in METHODS:
        method = metrics['methods'][key]
        seeded = 'seeds' in method
        cells = [cell(method['summary'][column], decimals) for column, _, decimals in COLUMNS]
        lines.append(f"| {name} | {len(seeds) if seeded else 'none (no training)'} | " + ' | '.join(cells) + ' |')
    return '\n'.join(lines) + '\n'


def readme_table(readme_text):
    """The text between the markers in the README, or None."""
    if START not in readme_text or END not in readme_text:
        return None
    return readme_text.split(START, 1)[1].split(END, 1)[0].strip('\n') + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--metrics', default=str(REPO / 'results' / 'metrics.json'))
    args = parser.parse_args()
    with open(args.metrics) as f:
        print(render(json.load(f)), end='')


if __name__ == '__main__':
    main()
