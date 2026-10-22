# Dashboard screenshots (part 1.5)

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
