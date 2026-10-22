# Dashboard screenshots

Captured on 2026-10-22 at 1440 px and 390 px width, dark theme, with headless Google Chrome
156 driven over the Chrome DevTools protocol (Playwright was not installed), browser cache
disabled. Code: idle and warm-up as of commit `69dd450`; the other shots as of `e28b142`.
`69dd450` changes only the empty score chart, which the other shots do not show. Times on
screen are local time (UTC+3).

## Live screenshots

**Every Live screenshot shows the live code path fed from a recorded session, not a live
measurement.** No Raspberry Pi was connected. How they were made:

- A throwaway database (`motorsense_screens`) and its own dev server, separate from the real
  database.
- A feeder posted recorded rows, one per second, to the real ingest endpoint `/api/ingest/`, so
  each row got the current time as its timestamp. Every fed row has the run label
  `screenshot_feed`. The source rows came from the recorded sessions `labeltest_01_warmup` and
  `labeltest_01` (motors off; 66 rows), then `r5_normal_05_warmup` and `r5_normal_05` (659 rows).
- The real `python manage.py score_live` command scored the fed rows with the saved model.
- The fed rows were deleted afterwards.

The idle rows and the normal session are two different recordings played back to back, so the
step in the temperature and pack voltage sparklines (for example 31.8 °C to 25.3 °C) comes from
switching recordings, not from the rig. The Offline segment at the start of the idle and warm-up
strips is the real gap between an earlier feed of the same fixture and this one: no readings
were stored in it.

| File | What it shows |
|---|---|
| `live_idle_1440.png`, `live_idle_390.png` | Live, state Idle: current at or below 0.5 A, not scored. The state strip shows Offline then Idle; with nothing to score, the chart area shows the same segments and the sentence "Idle: current at or below 0.5 A, so nothing is scored…". "What changed" is dimmed and marked "Not running". Fed from `labeltest_01_warmup`. |
| `live_warming_1440.png`, `live_warming_390.png` | Live, state Warming up: progress ring (107 of 180 s at 1440 px, 113 at 390 px), strip Offline, Idle, Warm-up, chart area explaining that scoring starts after warm-up, "What changed" marked "Not running". Fed from `r5_normal_05_warmup`. |
| `live_running_1440.png`, `live_running_390.png` | Live, state Normal: running for about 8 minutes, strip Normal, the last 5 minutes of scores (about 0.6 to 2, below the threshold 2.95), no alert. Fed from `r5_normal_05`. |
| `live_offline_1440.png`, `live_offline_390.png` | Live, state Offline: the feeder had stopped about 31 to 37 s before the capture; the scorer was still running. The strip ends with an Offline segment, "What changed" is marked "Offline", and the tiles show the last values dimmed with "Last reading … ago". |

## Replay screenshots

These show recorded scores and readings read from the real database. They are replays, not live
data, and the violet banner says so. "Show whole session" is off, so the chart and the strip
stop at the playhead.

| File | What it shows |
|---|---|
| `replay_fault_open_01_alert_1440.png`, `replay_fault_open_01_alert_390.png` | Replay of `r5_fault_open_01` (one motor disconnected) at second 219 of 632 (`?pos=218`), the second the first alert fires: "Alert since 16:16:47, lasting 0:00", score 189 against the threshold 2.95, largest deviation Current −23.6 σ (baseline 0.818 A, latest 0.697 A), "This is data, not a diagnosis". Marker "Alert started 16:16:47"; strip Warm-up, Running, Normal, Alert (the alert segment is one second wide at this moment). |
| `replay_normal_05_1440.png`, `replay_normal_05_390.png` | Replay of `r5_normal_05` (normal test session) at second 401 of 659 (`?pos=400`): state Normal, score 1.32, no alert in the session; strip Idle (the first seconds below 0.5 A), Warm-up, Running, Normal. |

## Part 2: the five tabs (and the Overview during a live alert)

Captured on 2026-10-22 at 1440 px and 390 px, dark theme, headless Google Chrome 156, cache
disabled, code as of commit `a512fe9` (the Overview during the alert was captured earlier in the
same session; nothing it uses changed afterwards). Only the throwaway database
`motorsense_screens` was used; no server ran against `motorsense_db`.

**Every Live screenshot below shows the live code path fed from recorded sessions, not a live
measurement.** The feeder posted recorded rows once per second to `/api/ingest/` with the run label
`screenshot_feed`: `labeltest_01_warmup` and `labeltest_01` (motors off, 66 rows), then
`r5_normal_05_warmup` and `r5_normal_05` (659 rows), then `r5_fault_open_01` (one motor
disconnected, 480 rows, taken from the raw CSV log). The real `score_live` scored them. Because the
fault rows directly follow the normal rows, the alert below is a recorded fault played through
the live path, not a fault on the rig at that time. The fed rows and the maintenance fixture were
deleted afterwards.

| File | What it shows |
|---|---|
| `overview_live_alert_1440.png`, `overview_live_alert_390.png` | Live Overview during the alert: "Alert since 07:23:31", largest deviation Current about −23.7 σ, "This is data, not a diagnosis"; strip Normal then Alert; marker "Alert started 07:23:31". |
| `sensors_1440.png`, `sensors_390.png` | Live Sensors, 30 min range, after the feed ended: five trend charts with minimum, mean and maximum over the range, data quality (1205 rows, 0 gaps above 5 s between readings, time since the last reading) and the CSV button. The steps at about 07:12 and 07:23 are the switches between the fed recordings. |
| `alerts_1440.png`, `alerts_390.png` | Live Alerts with the alert's detail open: start 07:23:31, still open after the feed stopped (no reading has closed it), peak score, run label `screenshot_feed`, largest deviation in the 60 s before the start (Current −5.6 σ: only the last seconds of that window already carry the fault), the score 2 min either side of the start and the three deviations. |
| `maintenance_1440.png`, `maintenance_390.png` | Maintenance with a fixture entry (an inspection logged at 07:10 by the throwaway user `screens`, its note saying it is a screenshot fixture) and a 14-day interval: "Next inspection due" with "Set by the operator. Not a prediction.", and the live alert listed as having no inspection logged afterwards. |
| `evaluation_1440.png`, `evaluation_390.png` | Evaluation from `results/metrics.json`, `results/negative_findings.json` and the evaluation's score files: the scope caveat, per-second and per-session tables with the seed spread, the statements derived from them, the five small multiples (each marked "Recorded, not live"), the negative findings with their reference sessions, and the environment. |
| `setup_1440.png`, `setup_390.png` | Setup: testbed and sensors, the reserved place for the testbed photo (not in the repository), the pipeline diagram (horizontal at 1440 px, vertical at 390 px), model inputs, states, alert rule, data retention and known limitations. |

Replay mode of Sensors and Alerts is not shown: it needs replays stored in the database, and the
only stored replays are in `motorsense_db`, which was not used for these screenshots.
