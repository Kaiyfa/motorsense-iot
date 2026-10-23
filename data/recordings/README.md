# Recorded sessions

The raw logs recorded on the bench rig by `testbed/logger.py`, for every session that the
evaluation (`docs/evaluation_plan.md`) or the negative findings
(`analysis/negative_findings.py`) use, with their warm-up segments.

| Path | Content |
|---|---|
| `raw/log_<UTC start>.csv` | The logger's CSV files, copied unchanged (23 files) |
| `sessions.csv` | One row per label: status, role, rows, rows that reached the database, date, first and last timestamp, file, whether the file has band columns |
| `not_in_database.csv` | Rows in the CSV files that never reached the database (label, timestamp) |
| `SHA256SUMS` | Checksums of every file in this folder; check with `shasum -a 256 -c SHA256SUMS` |

The logger also recorded development tests.
They are listed in `sessions.csv` as "development test, not published" with only their label,
row count and date, and their files are not included.

## Columns and units

One row per one-second window. How each value is computed is described in
[testbed/README.md](../../testbed/README.md).

| Column | Content |
|---|---|
| `timestamp_utc` | End of the window, ISO 8601, UTC |
| `temp_c` | Temperature, °C |
| `vib_rms_g`, `vib_peak_g` | RMS and peak of the vibration deviation, g |
| `current_ma` | Current, mA (the database stores A) |
| `bus_v` | Pack voltage, V |
| `n_samples` | Valid accelerometer samples in the window |
| `i2c_errors` | Failed reads and rejected samples in the window |
| `label` | Session label |
| `band_1_6_g`, `band_6_20_g`, `band_20_50_g`, `band_50_100_g` | Vibration RMS per frequency band, g (only in the files recorded from r4_band_normal_a on) |

## Label rules

- **Warm-up:** the first rows of a session carry the label `<session>_warmup` (the logger's `--warmup` flag). The evaluation and the live scorer exclude warm-up rows.
- **Sessions:** a session is the set of rows with one label, and one label can span two files (r5_normal_03).
- **Roles:** they come only from `docs/evaluation_plan.md` and `analysis/negative_findings.py`. A label that neither of them names is not assigned a role.

## Sessions

Warm-up segments are not listed below; their rows are in `sessions.csv`.

| Label | Role | Rows | Rows in the database | Date (UTC) | Band columns |
|---|---|---|---|---|---|
| r5_normal_01 | evaluation: training | 480 | 480 | 2026-10-21 | yes |
| r5_normal_02 | evaluation: training | 480 | 479 | 2026-10-21 | yes |
| r5_normal_03 | evaluation: training | 480 | 479 | 2026-10-21 | yes |
| r5_normal_04_redo | evaluation: validation | 480 | 479 | 2026-10-21 | yes |
| r5_normal_05 | evaluation: test, normal | 480 | 479 | 2026-10-21 | yes |
| r5_fault_open_01 | evaluation: test, fault (one motor lead disconnected) | 480 | 479 | 2026-10-21 | yes |
| r5_fault_open_02 | evaluation: test, fault | 480 | 479 | 2026-10-21 | yes |
| r5_fault_open_03 | evaluation: test, fault | 480 | 479 | 2026-10-21 | yes |
| r5_normal_04 | excluded: invalid session | 480 | 322 | 2026-10-21 | yes |
| r5_check | excluded: recorded with `--no-post` | 60 | 0 | 2026-10-21 | yes |
| r2_normal_01 | negative findings: baseline shift, reference | 480 | 479 | 2026-10-20 | no |
| r3_normal_01 | negative findings: baseline shift, test | 540 | 539 | 2026-10-21 | no |
| r2_test_baseline | negative findings: imbalance and loose mount, reference | 180 | 163 | 2026-10-21 | no |
| r3_test_fault | negative findings: imbalance | 180 | 180 | 2026-10-21 | no |
| r3_test_fault2 | negative findings: imbalance | 180 | 179 | 2026-10-21 | no |
| r3_test_loose | negative findings: loosened motor mount | 180 | 179 | 2026-10-21 | no |
| r4_band_normal_a | negative findings: reference (also baseline shift, test) | 240 | 0 | 2026-10-21 | yes |
| r4_band_fault_a | negative findings: imbalance, frequency bands | 240 | 0 | 2026-10-21 | yes |
| r4_tune | negative findings: friction by hand | 60 | 0 | 2026-10-21 | yes |
| r4_tune2 | negative findings: friction by hand | 60 | 0 | 2026-10-21 | yes |
| r4_test_open | negative findings: open motor lead | 180 | 0 | 2026-10-21 | yes |
| r4_test_drag | negative findings: former reference, no longer used | 180 | 0 | 2026-10-21 | yes |

## Excluded and invalid data

| Data | Reason |
|---|---|
| Every `_warmup` label | The first seconds of each session, while vibration is still low and rising |
| r5_normal_04 | Invalid session, cause unknown (see the evaluation plan) |
| r5_check | Recorded with `--no-post`, so it never reached the database |
| The extra 30 rows in r5_normal_03_warmup | An aborted start |
| Development tests | Not published (see above) |

## Rows that never reached the database

The evaluation read the database, not these files, and not every logged row reached the
database. `not_in_database.csv` lists the rows that did not. It was derived by comparing
these files with a backup of the database taken on 22 Oct 2026 (the backup itself is not
published). For the evaluation sessions:
- **Final row:** each session lacks its final row, except r5_normal_01. That is consistent with the last post being lost when the logger stopped.
- **r5_fault_open_01_warmup:** lacks its first 27 rows.

The analysis runs (r4 runs and r5_check) were not posted at all, and r5_normal_04 lacks 158
rows. Every row that did reach the database has the same values as in the files (current in
A instead of mA).

`python manage.py import_recordings` leaves these rows out by default, so the imported data
is the data the evaluation used; `--all-rows` imports every row. `analysis/negative_findings.py`
reads the files directly and uses every row.
