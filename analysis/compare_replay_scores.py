"""
Check that replayed scores equal the evaluation's scores for every second
scored by both (three-feature autoencoder, seed 0).

    python manage.py replay_session --label r5_normal_04_redo --label r5_normal_05 \
        --label r5_fault_open_01 --label r5_fault_open_02 --label r5_fault_open_03
    python analysis/compare_replay_scores.py

Two references:
  (a) results/scores/<session>.csv, column ae_all_seed0, written by
      run_evaluation with 6 significant digits (not committed; skipped and
      reported when missing);
  (b) a full-precision recomputation: the saved model applied to the exported
      session with the evaluation's batch code path.
Exit code 1 if any second differs beyond the reference's precision.
"""
import csv
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

import numpy as np  # noqa: E402

from dashboard.ml import dataset, saved_model  # noqa: E402
from dashboard.ml import evaluation as ev  # noqa: E402
from dashboard.models import AnomalyScore  # noqa: E402

SESSIONS = list(dataset.VALIDATION_LABELS + dataset.TEST_NORMAL_LABELS + dataset.TEST_FAULT_LABELS)
FULL_PRECISION_RTOL = 1e-6   # float32 has about 7 significant digits
CSV_DIGITS = 6               # results/scores/*.csv are written with %.6g


def main():
    detector = saved_model.load()
    sessions = ev.load_sessions('data/dataset')
    failed = False
    skipped_a = []
    for label in SESSIONS:
        replay = {r.timestamp: r.score for r in AnomalyScore.objects.filter(
            mode='replay', run_label__in=[label + dataset.WARMUP_SUFFIX, label])}
        if not replay:
            print(f'{label}: no replay stored; run replay_session first')
            failed = True
            continue

        # (a) evaluation CSV, 6 significant digits (skipped when results/scores/ is missing:
        # it is written by run_evaluation and not committed)
        csv_scores = {}
        csv_path = Path(f'results/scores/{label}.csv')
        if csv_path.exists():
            with csv_path.open(newline='') as f:
                for row in csv.DictReader(f):
                    if row['ae_all_seed0']:
                        csv_scores[datetime.fromisoformat(row['timestamp'])] = float(row['ae_all_seed0'])
        else:
            skipped_a.append(label)
        both = [t for t in csv_scores if replay.get(t) is not None]
        # allowed: half a unit in the 6th significant digit (CSV rounding) plus float32
        # precision (the replayed float itself may differ by ~1e-7 from the evaluation's)
        beyond_csv = [t for t in both
                      if abs(replay[t] - csv_scores[t]) >
                      0.5 * 10 ** (np.floor(np.log10(abs(csv_scores[t]))) - CSV_DIGITS + 1)
                      + FULL_PRECISION_RTOL * abs(csv_scores[t])]
        rel_csv = max((abs(replay[t] - csv_scores[t]) / abs(csv_scores[t]) for t in both), default=0.0)

        # (b) full-precision recomputation with the evaluation's batch path
        s = sessions[label]
        seqs = ev.build_sequences(ev.standardise(s, dataset.FEATURES, detector.scaler)).astype('float32')
        full = ev.causal_scores(ev.reconstruction_scores(seqs, detector.reconstruct(seqs)), len(s['timestamps']))
        pairs = np.array([(replay[datetime.fromisoformat(t)], full[i]) for i, t in enumerate(s['timestamps'])
                          if not np.isnan(full[i]) and replay.get(datetime.fromisoformat(t)) is not None])
        rel_full = np.abs(pairs[:, 0] - pairs[:, 1]) / np.abs(pairs[:, 1])
        identical = int(np.sum(pairs[:, 0] == pairs[:, 1]))

        only_replay = ([t for t, v in replay.items() if v is not None and t not in csv_scores]
                       if csv_scores else [])
        only_eval = [t for t in csv_scores if replay.get(t) is None]
        bad = bool(beyond_csv) or rel_full.max() > FULL_PRECISION_RTOL or bool(only_replay)
        failed |= bad
        part_a = (f"(a) CSV: {len(beyond_csv)} beyond 6-digit rounding, max rel diff {rel_csv:.2e}"
                  if csv_scores else '(a) CSV: not checked, results/scores/ missing')
        print(f"{label:18} scored by both {len(both):3} | {part_a} "
              f"| (b) full precision: {identical}/{len(pairs)} bit-identical, "
              f"max rel diff {rel_full.max():.2e} | scored only by replay {len(only_replay)}, "
              f"only by evaluation {len(only_eval)}{'  <-- MISMATCH' if bad else ''}")
    if skipped_a:
        print(f"\n(a) not checked for {', '.join(skipped_a)}: results/scores/ is written by run_evaluation and "
              f"not committed; (b) was checked.")
    print('\nRESULT:', 'MISMATCH' if failed else 'all shared seconds equal within float precision'
          + (' (full-precision recomputation only)' if len(skipped_a) == len(SESSIONS) else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
