# Live-rig screenshots (23 Oct 2026)

These screenshots come from the real rig, not from a recorded session:
- **Logger:** ran on the Raspberry Pi with the run label `live_demo` and posted to the dashboard.
- **Scorer:** `score_live` ran against the real database.
- **Times:** shown in Asia/Riyadh (UTC+3).

They are single demonstration runs, **not part of the evaluation**: the numbers in
`results/metrics.json` and `docs/evaluation_plan.md` come from the recorded r5 sessions
only. The screenshots were taken in the browser at different window sizes; some are cropped.

| File | What it shows |
|---|---|
| `live_rig_warmup.png` | 02:53:28. State **Warming up**, 17 of 180 s, after the motors started. The chart has no scores yet (Offline, then Idle, then Warm-up), and "What changed" is marked Not running. |
| `live_rig_running.png` | 02:56:13. State **Running** for 3 s after the warm-up: "Scoring starts in 27 s, once 30 s of running data are buffered". |
| `live_rig_normal.png` | 02:58:39. State **Normal**, score 0.609, below the threshold 2.95. The scores so far stay between about 0.6 and 1.3. Cropped: the header is not visible. |
| `live_rig_false_alarm.png` | 03:00:28. Back to **Normal** after a false alert that started at 02:59:25 and lasted 21 s (peak score 5.03). A single second had a vibration peak of 1.0214 g while the vibration RMS was only 0.1475 g, with no I2C errors in that second. Probably one bad sample out of 200; the cause is not established. Cropped: the header is not visible. |
| `live_rig_sensors.png` | 03:00:51. **Sensors**, last 30 min: the spike in vibration peak (maximum 1.021 g in the range) next to an unremarkable vibration RMS (maximum 0.148 g). There is one gap above 5 s (10 min 35 s) before the run. Cropped below the current chart. |
| `live_rig_idle.png` | 03:15:00. State **Idle** for 17 s (current at or below 0.5 A, not scored), before the next run; the earlier part of the 5-minute window is Offline. |
| `live_rig_after_disconnect.png` | 03:21:39. The motor lead had already been disconnected, and the motors were restarted at 03:21:13; the screenshot shows the state **Running** before the alert. "What changed" shows current at −96.9 σ (latest 0.703 A), but the new sequence is not scored yet ("Scoring starts in 3 s"). The chart also shows an earlier alert at 03:19:04, lasting 1 min 00 s. In that run the score was between 8.67 and 10.43 in every scored second, from the first one at 03:18:55, and the alert ended at 03:20:04 when the current fell to 0.001 A and the state changed to Idle. The cause was not recorded. |
| `live_rig_alert.png` | 03:22:25. State **Alert** with the motor lead still disconnected: alert since 03:21:51, score 212 against the threshold 2.95, largest deviation Current −23.6 σ (baseline 0.818 A, latest 0.725 A). "This is data, not a diagnosis." |
| `live_rig_alerts_tab.png` | The **Alerts** tab with the three live `live_demo` episodes: 02:59:25 (21 s, peak 5.03, closed), 03:19:04 (1 min 00 s, peak 10.2, closed) and 03:21:51 (open, peak 231 at that moment). |

The score range and the state change of the 03:19:04 alert are not readable in a screenshot; they come from the
live scores stored in the database for that run (warm-up from 03:15:25, running from 03:18:26, first score at
03:18:55, idle from 03:20:04, running again from 03:21:13).

In the six screenshots that show the header, the logged-in user name (top right) is covered with a
rectangle in the header's background colour; nothing else in the images was changed.
