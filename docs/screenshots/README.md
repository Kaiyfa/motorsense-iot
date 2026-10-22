# Dashboard screenshots (part 1)

Captured on 2026-10-22 at 1440 px and 390 px width, dark theme, with headless Google Chrome
156 driven over the Chrome DevTools protocol (Playwright was not installed). Code as of commit
`455f1f9`. Times on screen are local time (UTC+3).

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
switching recordings, not from the rig.

| File | What it shows |
|---|---|
| `live_running_1440.png`, `live_running_390.png` | Live, state Normal: running for about 8 minutes, the last 5 minutes of scores (about 0.6 to 2, below the threshold 2.95), no alert. Fed from `r5_normal_05`. |
| `live_idle_1440.png`, `live_idle_390.png` | Live, state Idle: current at or below 0.5 A, not scored, so the score chart is empty and says why. "What changed" shows large deviations with the note that the baseline comes from running data. Fed from `labeltest_01_warmup`. |
| `live_warming_1440.png`, `live_warming_390.png` | Live, state Warming up: progress ring at 107 of 180 s and "Scoring starts after warm-up". Fed from `r5_normal_05_warmup`. |
| `live_offline_1440.png`, `live_offline_390.png` | Live, state Offline: the feeder had stopped about 1 min 40 s before the capture; the scorer was still running. The chart ends at the last reading, "What changed" has no readings in the last 60 s, and the tiles show the last values dimmed with "Last reading ... ago". |

## Replay screenshots

These show recorded scores and readings read from the real database. They are replays, not live
data, and the violet banner says so.

| File | What it shows |
|---|---|
| `replay_fault_open_01_alert_1440.png`, `replay_fault_open_01_alert_390.png` | Replay of `r5_fault_open_01` (one motor disconnected) with the playhead at second 219 of 632 (`?pos=218`), the second the first alert fires: state Alert, score 189 against the threshold 2.95. The shaded alert episode runs to the end of the recording, flagged as still active when the recording ended. |
| `replay_normal_05_1440.png`, `replay_normal_05_390.png` | Replay of `r5_normal_05` (normal test session) with the playhead at second 401 of 659 (`?pos=400`): state Normal, score 1.32, no alert in the session. |
