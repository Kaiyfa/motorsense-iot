# MotorSense IoT: anomaly detection evaluation

The evaluation plan, including every setting, is in
[evaluation_plan.md](evaluation_plan.md). It was committed before any training code
existed; `git log -- docs/evaluation_plan.md` shows the order.

## Reproducing the results

All commands run from the repository root with the project venv active
(`source venv/bin/activate`). The database settings come from `.env` (see `.env.example`).

| Step | Command | Output |
|---|---|---|
| 1. Export the sessions from the database | `python manage.py export_dataset` | `data/dataset/{train,validation,test_normal,test_fault}.csv`, `data/dataset/manifest.json` (not committed) |
| 2. Train and evaluate all detectors | `python -m dashboard.ml.run_evaluation` | `results/metrics.json` (committed), `results/scores/<session>.csv` (not committed), `ml_models/motorsense_ae/` (three-feature model, seed 0: `model.keras`, `scaler.json`, `threshold.json`; not committed) |
| 3. Negative findings from the raw Pi logs | `python analysis/negative_findings.py ~/motorsense-raw-data` | Printed tables; the raw CSVs stay outside the repository |
| Tests | `python manage.py test` | Includes the database-free tests below |
| Tests without Django or TensorFlow | `python -m unittest dashboard.tests_dataset dashboard.tests_evaluation` | |

`run_evaluation` accepts `--data`, `--results` and `--models` to change the paths. It trains
15 autoencoders (three feature sets, seeds 0 to 4, 50 epochs each) on the CPU.

## Environment

The results in `results/metrics.json` were produced with Python 3.10.13,
tensorflow-macos 2.13.0, keras 2.13.1 and numpy 1.24.3 on Apple silicon (arm64). The exact
versions, the git commit and whether the working tree was clean are recorded in
`results/metrics.json` under `environment` and `git`.

The venv also lists a `tensorflow 2.20.0` package. It is not the one in use:
`import tensorflow` gives 2.13.0 (from tensorflow-macos). The installation has been left
as it is.

## Live scoring and alerts

The live scorer applies the saved three-feature autoencoder (seed 0, `ml_models/motorsense_ae/`)
to new readings. It is a separate process, so the web server never runs the model; it
reuses the evaluation's own functions (scaling, sequence building, score, threshold
comparison and alert rule), and the shared settings live in one place,
`dashboard/ml/constants.py`, imported by both the evaluation and the scorer.

| Command | What it does |
|---|---|
| `python manage.py migrate` | Creates the `anomaly_scores`, `alert_episodes` and `scorer_heartbeats` tables |
| `python manage.py score_live [--equipment EQ-001] [--interval 1]` | Polls new `source = pi` readings every second, scores them and records alerts (mode `live`). After a restart it resumes after the last scored reading |
| `python manage.py replay_session --label r5_fault_open_01 [--label ...]` | Runs a stored session, including its `_warmup` rows, through the same code path and stores the results with mode `replay`, the original timestamps and labels. Running it again replaces the earlier replay of that session |

### Machine state

| State | Condition | Scored |
|---|---|---|
| idle | current at or below 0.5 A | no |
| warming_up | the first 180 s after the current first exceeds 0.5 A | no |
| running | afterwards | yes, once 30 consecutive running seconds are buffered |

The warm-up exists because every recorded session starts with a 180 s warm-up segment
(label suffix `_warmup`) in which vibration is still low and rising. Those segments were
excluded from training, validation and test, so the model has never seen warm-up data and
its scores there would mean nothing. Only running seconds enter the 30-second buffer, so
every scored sequence contains post-warm-up data only, as in the evaluation. A reading more
than 5 s after the previous one clears the buffer and restarts the state machine (idle,
then a new warm-up). A dip to idle while running empties the buffer and ends an active
alert but does not restart the warm-up.

The alert rule is the evaluation's: an alert fires on the 10th consecutive second above
the threshold and stays active while the score stays above it. Each alert is stored as an
episode with its start, end (empty while active) and peak score.

### Replay against the evaluation

The evaluation cut the warm-up by label; the live state machine cuts it by time (180 s
after the current first exceeds 0.5 A). In the stored sessions that point falls 2 to 27
rows after the session label starts (27 for r5_fault_open_01, whose first warm-up seconds
were never posted). A replay therefore scores fewer seconds than the evaluation and its
first alert comes the same number of rows later. For every second scored by both, the
replayed score equals the evaluation's score to float32 precision.

### API (login required, JSON)

| Endpoint | Content |
|---|---|
| `/api/live/status/?equipment_id=EQ-001` | Machine state, latest score and threshold, whether an alert is active, seconds since the last reading, and whether the scorer is alive (polled within the last 10 s) |
| `/api/live/scores/?minutes=N` | Live scores of the last N minutes (default 10, at most 1440) |
| `/api/alerts/?mode=live` | Alert episodes; `mode` is `live` (default), `replay` or `all`; every episode carries its mode |
| `/api/replay/<label>/` | Scores, threshold and alert periods of a replayed session |

The live endpoints read mode `live` rows only, so a replay is never shown as live.
