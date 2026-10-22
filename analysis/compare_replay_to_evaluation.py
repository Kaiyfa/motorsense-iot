"""
Side by side: replayed sessions (mode replay) against results/metrics.json for
the three-feature autoencoder, seed 0.

    python analysis/compare_replay_to_evaluation.py

The evaluation cut the warm-up by label; the live scorer cuts it by time (180 s
after the current first exceeds 0.5 A), so a replay starts scoring a few rows
later. The offset is the number of rows between the evaluation's first scored
second and the replay's. Expected: equal episode counts, scored seconds
smaller by exactly the offset, and the first alert later by exactly the offset
(in rows; in wall-clock seconds within a few milliseconds, because rows are not
exactly 1 s apart). Exit code 1 otherwise.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(REPO)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'monitor.settings')

import django  # noqa: E402
django.setup()

from dashboard.ml import dataset  # noqa: E402
from dashboard.ml import evaluation as ev  # noqa: E402
from dashboard.ml.constants import SEQUENCE_LENGTH  # noqa: E402
from dashboard.models import AlertEpisode, AnomalyScore  # noqa: E402

SESSIONS = list(dataset.VALIDATION_LABELS + dataset.TEST_NORMAL_LABELS + dataset.TEST_FAULT_LABELS)


def hms(x):
    return x.strftime('%H:%M:%S.%f')[:-3] if x else '-'


def main():
    seed0 = json.load(open('results/metrics.json'))['methods']['ae_all']['seeds']['0']
    sessions = ev.load_sessions('data/dataset')
    first = SEQUENCE_LENGTH - 1
    failed = False

    header = (f"{'session':18} | {'eval scored':>11} {'eval ep':>7} {'eval 1st scored':>15} {'eval 1st alert':>14} | "
              f"{'replay scored':>13} {'replay ep':>9} {'replay 1st scored':>17} {'replay 1st alert':>16} | "
              f"{'offset s':>8} {'offset rows':>11} {'alert diff s':>12} {'alert diff rows':>15} check")
    print(header)
    print('-' * len(header))
    for label in SESSIONS:
        ts = [datetime.fromisoformat(t) for t in sessions[label]['timestamps']]
        if label in seed0['sessions']:
            e = seed0['sessions'][label]
            e_scored, e_ep, e_delay = e['scored_seconds'], e['episodes'], e['delay_seconds']
        else:  # validation session
            e_scored, e_ep, e_delay = len(ts) - first, seed0['validation_episodes'], None
        e_alert_row = first + e_delay if e_delay is not None else None

        labels = [label + dataset.WARMUP_SUFFIX, label]
        scored = AnomalyScore.objects.filter(mode='replay', run_label__in=labels, score__isnull=False).order_by('timestamp')
        if not scored.exists():
            print(f'{label}: no replay stored; run replay_session first')
            failed = True
            continue
        r_first = scored.first().timestamp
        episodes = list(AlertEpisode.objects.filter(mode='replay', run_label__in=labels).order_by('started_at'))
        r_alert = episodes[0].started_at if episodes else None

        offset_rows = ts.index(r_first) - first
        offset_s = (r_first - ts[first]).total_seconds()
        r_alert_row = ts.index(r_alert) if r_alert else None
        alert_rows = r_alert_row - e_alert_row if (r_alert_row is not None and e_alert_row is not None) else None
        alert_s = (r_alert - ts[e_alert_row]).total_seconds() if alert_rows is not None else None

        ok = (len(episodes) == e_ep and e_scored - scored.count() == offset_rows and
              ((r_alert is None and e_alert_row is None) or alert_rows == offset_rows))
        failed |= not ok
        print(f"{label:18} | {e_scored:>11} {e_ep:>7} {hms(ts[first]):>15} "
              f"{hms(ts[e_alert_row]) if e_alert_row is not None else '-':>14} | "
              f"{scored.count():>13} {len(episodes):>9} {hms(r_first):>17} {hms(r_alert):>16} | "
              f"{offset_s:>8.3f} {offset_rows:>11} {'-' if alert_s is None else f'{alert_s:.3f}':>12} "
              f"{'-' if alert_rows is None else alert_rows:>15} {'ok' if ok else 'MISMATCH'}")
    print('\nTimes are UTC. Evaluation first alert = evaluation first scored second + delay_seconds from metrics.json.')
    print('RESULT:', 'MISMATCH' if failed else 'episodes equal; scored seconds and first alert differ by exactly the offset in rows')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
