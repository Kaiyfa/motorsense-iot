# MotorSense IoT: anomaly detection evaluation

The evaluation plan, including every setting, is in
[evaluation_plan.md](evaluation_plan.md). It was committed before any training code
existed; `git log -- docs/evaluation_plan.md` shows the order.

## Reproducing the results

All commands run from the repository root with the project venv active
(`source venv/bin/activate`) and both `requirements.txt` and `requirements-ml.txt` installed
(see the main README). The database settings come from `.env` (see `.env.example`). Steps 1
and 2 need the recorded sessions in the database; they are not in the repository, so a fresh
clone can run the tests but not the training.

| Step | Command | Output |
|---|---|---|
| 1. Export the sessions from the database | `python manage.py export_dataset` | `data/dataset/{train,validation,test_normal,test_fault}.csv`, `data/dataset/manifest.json` (not committed) |
| 2. Train and evaluate all detectors | `python -m dashboard.ml.run_evaluation` | `results/metrics.json` (committed), `results/scores/<session>.csv` (not committed), `models/motorsense_ae/` (three-feature model, seed 0: `model.keras`, `scaler.json`, `threshold.json`; committed, so a rerun shows up in `git diff`) |
| 3. Negative findings from the raw Pi logs | `python analysis/negative_findings.py` (reads `data/recordings/raw`; `--data DIR` for another folder) | Printed tables and `results/negative_findings.json` |
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

## Dashboard

The web dashboard has two modes, switched in the header. Live shows the newest readings and
scores; Replay steps through a recorded session that was run through the scorer with
`replay_session`, and always shows the banner "REPLAY of recorded session <label>. Not live
data." in violet, so the two cannot be confused.

| Command | Purpose |
|---|---|
| `python manage.py runserver` | Web server; open http://127.0.0.1:8000/ and log in |
| `python manage.py score_live --equipment EQ-001` | Live scorer (separate process; needs EQ-001 to exist, i.e. at least one reading received) |
| `python manage.py replay_session --label r5_fault_open_01` | Store a replay of a recorded session for the Replay mode |

Overview (both modes): the machine state with its icon and how long it has lasted, the time
since the last reading and whether the scorer is alive (Live), a warm-up progress ring, the
anomaly score on a logarithmic axis with the alert threshold and alert episodes, a "What
changed" panel (mean of the last 60 s of each model feature minus the training mean, in
training standard deviations; data, not a diagnosis) and tiles for the five sensors with
5-minute sparklines. Live polls the JSON API every 2 s and pauses while the browser tab is
hidden. Replay plays the recording at 1x, 10x or 30x with a scrubber; `?session=<label>&pos=<n>`
links to a position. The other tabs are described under Tabs below.

Removed in the rebuild: the simulated mode and its endpoints (`/api/prediction/`,
`/api/equipment/`, `/api/`, `/api/live/prediction/`, `/live/`), the C-MAPSS prediction service
(`dashboard/ml/ml_service.py`), and every figure or claim that was not measured on this rig
(model accuracy, remaining useful life, failure probability, costs and savings).

Under the hero, a state timeline strip shares the score chart's time axis: consecutive
segments Offline, Idle, Warm-up, Running (not scored yet), Normal and Alert, plus Not scored
for readings the scorer did not process. They are built only from stored scores and readings
(`dashboard/timeline.py`; `/api/live/timeline/?minutes=N`, and `timeline` in
`/api/replay/<label>/`). A gap of more than 5 s between stored seconds is Offline when no
reading was stored in it. Hover or focus the strip (arrow keys) for each segment's start,
end and duration. When there is nothing to score, the chart area shows the same segments
with a sentence on what is going on. While the machine is idle, warming up or offline,
"What changed" is dimmed and labelled, because deviations from a running baseline mean
nothing then. In an alert, the hero shows when it started, how long it has lasted and the
largest deviation from the "What changed" panel; it never names a cause. In Replay the chart
and the strip stop at the playhead unless "Show whole session" is ticked.

### Tabs

| Tab | What it shows | Source of every number |
|---|---|---|
| Sensors | A trend chart per sensor with minimum, mean and maximum over the range (Live: 5 min, 30 min, 2 h, 24 h; Replay: the recorded session up to the Overview's playhead); data quality (rows, readings per minute, gaps above 5 s, time since the last reading); "Download CSV for this range" | Stored `sensor_data` rows. Charts draw at most 1200 points per series (minimum and maximum of each slice); the statistics and the CSV use every row |
| Alerts | Alert episodes (Live by default; Replay rows carry the replay label and session name) with start, duration, peak score, status, run label and the largest deviation in the 60 s before the start; a row expands to the score 2 min either side of the start and the three deviations | `alert_episodes`, `anomaly_scores`, `sensor_data`; the deviation is the "What changed" calculation (`dashboard/calculations.py`) |
| Maintenance | Operator log (inspection, repair, replacement, other) with add and delete-own; an inspection interval per equipment; "Next inspection due" (last logged inspection plus the interval, labelled "Set by the operator. Not a prediction."); live alerts without a logged inspection afterwards | `maintenance_entries`, `inspection_intervals` (migration 0006), `alert_episodes` |
| Evaluation | The scope caveat, per-second and per-session tables for the five detectors with the seed spread, statements derived from the numbers, the negative findings, score small multiples for the validation and test sessions, the environment | `results/metrics.json`, `results/negative_findings.json` (written by `python analysis/negative_findings.py`), and the evaluation's score files in `results/scores/` (not committed; without them the small multiples say so) |
| Setup | The testbed and sensors, a pipeline diagram, model inputs, machine states, the alert rule, data retention and known limitations | `dashboard/ml/constants.py` and the evaluation plan |

The testbed photo (`docs/media/testbed_photo.jpg`) is not in the repository; the Setup tab
reserves a labelled place for it. Run `python manage.py migrate` once for the maintenance
tables.

### Static files and browser caching

Every static URL carries a content version, so a browser never runs stale JavaScript or CSS
after an update. `{% vstatic 'path' %}` (in `dashboard/templatetags/versioned_static.py`)
appends `?v=<first 12 hex digits of the SHA-256 of the file>`, recomputed whenever the file
changes on disk. The JavaScript modules import each other through bare names such as
`ms/overview.js`, which an import map in the page (`{% js_importmap %}`) resolves to versioned
URLs; a version on the entry script alone would not reach the modules it imports. New
modules must be added to `JS_MODULES` in that file. No build step or extra package is needed.

Screenshots of each state are in [screenshots/](screenshots/README.md).

## Live scoring and alerts

The live scorer applies the saved three-feature autoencoder (seed 0, `models/motorsense_ae/`)
to new readings. It is a separate process, so the web server never runs the model; it
reuses the evaluation's own functions (scaling, sequence building, score, threshold
comparison and alert rule), and the shared settings live in one place,
`dashboard/ml/constants.py`, imported by both the evaluation and the scorer.

| Command | What it does |
|---|---|
| `python manage.py migrate` | Creates the `anomaly_scores`, `alert_episodes` and `scorer_heartbeats` tables |
| `python manage.py score_live [--equipment EQ-001] [--interval 1]` | Polls new `source = pi` readings every second, scores them and records alerts (mode `live`). On its very first start (no live scores yet) it begins at the newest reading and ignores everything older, so stored recordings are never scored as live. After a restart it resumes after the last scored reading |
| `python manage.py replay_session --label r5_fault_open_01 [--label ...]` | Runs a stored session, including its `_warmup` rows, through the same code path and stores the results with mode `replay`, the original timestamps and labels. Running it again replaces the earlier replay of that session |

The saved model is loaded with `compile=False` (inference only). Keras 2.13 on Apple
silicon cannot restore the legacy Adam optimizer the model was trained with; the scorer
needs no optimizer, and the weights and architecture are the same either way.

The web server does not load TensorFlow: the views read only the database, and the old
simulated-mode model (`dashboard/ml/ml_service.py`) is imported only when
`/api/prediction/` is called.

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
episode with its start, end (empty while active) and peak score. In a replay, an alert that
is still active at the last reading of the recording is closed there and flagged
`open_at_end_of_recording`; its end is the end of the data, not the end of the alert.

### Replay against the evaluation

The evaluation cut the warm-up by label; the live state machine cuts it by time (180 s
after the current first exceeds 0.5 A). In the stored sessions that point falls 2 to 27
rows after the session label starts (27 for r5_fault_open_01, whose first warm-up seconds
were never posted). A replay therefore scores fewer seconds than the evaluation and its
first alert comes the same number of rows later. For every second scored by both, the
replayed score equals the evaluation's score to float32 precision.

To rerun the comparison (needs `data/dataset/` from `export_dataset` and
`results/scores/` from `run_evaluation`):

```
python manage.py replay_session --label r5_normal_04_redo --label r5_normal_05 \
    --label r5_fault_open_01 --label r5_fault_open_02 --label r5_fault_open_03
python analysis/compare_replay_scores.py          # scores of every second scored by both
python analysis/compare_replay_to_evaluation.py   # side by side with results/metrics.json, seed 0
```

Both scripts exit with code 1 on a mismatch.

### API (login required, JSON)

| Endpoint | Content |
|---|---|
| `/api/live/status/?equipment_id=EQ-001` | Machine state, latest score and threshold, whether an alert is active, seconds since the last reading, and whether the scorer is alive (polled within the last 10 s) |
| `/api/live/scores/?minutes=N` | Live scores of the last N minutes (default 10, at most 1440) |
| `/api/alerts/?mode=live` | Alert episodes; `mode` is `live` (default), `replay` or `all`; every episode carries its mode and the `open_at_end_of_recording` flag |
| `/api/replay/<label>/` | Scores, threshold and alert periods of a replayed session |

The live endpoints read mode `live` rows only, so a replay is never shown as live.
