# Evaluation plan: anomaly detection on the motor testbed

Written on 2026-10-22, before any model has been trained. The rules below are fixed
now so that results cannot be tuned after looking at the fault data.

## Test setup

| Item | Setup |
|---|---|
| Machine | Elegoo robot car with four DC motors, wheels removed, fixed speed, on a bench |
| Vibration | MPU-6050 on a breadboard resting on the chassis |
| Current and bus voltage | INA219 in series with the battery pack |
| Temperature | DS18B20 |
| Sampling | 200 Hz samples summarised into 1 Hz windows (one row per second) |
| Calibration | Current is not calibrated |
| Transport | Plain HTTP ingest on a home network |

Each row in `sensor_data` is one 1-second window. Rows are grouped into sessions by
`run_label`. Current is stored in amperes.

## Sessions and their roles

| Role | Sessions |
|---|---|
| Training | r5_normal_01, r5_normal_02, r5_normal_03 |
| Validation | r5_normal_04_redo |
| Test, normal | r5_normal_05 |
| Test, fault | r5_fault_open_01, r5_fault_open_02, r5_fault_open_03 |

The fault in the test fault sessions is one motor lead disconnected (open circuit).

### Excluded data

| Excluded | Reason |
|---|---|
| Every label ending in `_warmup` | The first 180 s of each session; vibration is still warming up |
| r5_check | Recorded with `--no-post`: it exists only in the raw CSV files, not in the database |
| r5_normal_04 | Invalid session, cause unknown (details below) |
| The extra 30 rows in r5_normal_03_warmup | An aborted start |
| Every row with source other than `pi` | `pi` is the value the ingest endpoint stores for testbed rows |
| Any label not listed in this plan | Never assigned to a role by guessing |

#### r5_normal_04

| View | Vibration RMS | Current | Rows |
|---|---|---|---|
| Session log, per-minute means | 0.175 to 0.270 g | 953 to 995 mA | 480 recorded |
| Database, per 1 s window | 0.163 to 0.295 g, mean 0.247 g | | 322 reached the database |

The raw CSV file of this recording contains 923 I2C errors in total (230 in
r5_normal_04_warmup and 693 in r5_normal_04). The I2C error count is not stored in the
database.

#### Rows missing from the database

r5_fault_open_01_warmup has 153 rows in the database because some early seconds were not
posted; the raw CSV has all 180. This session is excluded in any case (warm-up).

## Model inputs

The model uses three features per window: `vib_rms_g`, `vib_peak_g` and `current`.

Bus voltage and temperature are recorded and plotted but are not model inputs:

| Signal | Why it is not an input |
|---|---|
| bus_v | The pack state differs between sessions by up to 0.15 V, independent of any fault |
| temperature | It rises 3 to 5 degrees per session without reaching a plateau |

## Method

An LSTM autoencoder is trained on normal windows only (the training sessions).

| Rule | Value |
|---|---|
| Alert threshold | 99.5th percentile of reconstruction error on the validation session |
| Alert condition | 10 consecutive seconds above the threshold |

Both rules are fixed before looking at any fault data.

## Baselines

The autoencoder is compared against two simple detectors. Each uses the same validation
session, the same 99.5th percentile and the same 10-second rule.

| Baseline | Signal |
|---|---|
| Fixed threshold on current | `current` |
| Fixed threshold on vibration | `vib_rms_g` |

## Ablation

Besides the three-feature model, the same autoencoder architecture is trained on two
reduced feature sets. All variants use exactly the same sessions, the same threshold rule
(99.5th percentile on the validation session) and the same alert rule (10 consecutive
seconds).

| Detector | Inputs |
|---|---|
| Autoencoder, all features | vib_rms_g, vib_peak_g, current |
| Autoencoder, vibration only | vib_rms_g, vib_peak_g |
| Autoencoder, current only | current |
| Fixed threshold on current | current |
| Fixed threshold on vibration | vib_rms_g |

The fault (one motor lead open) drops the current by about 0.115 A, so it is expected to be
detected by any method that sees the current. The ablation is there to show what the
vibration channels alone can and cannot detect.

## Metrics

Precision and recall on the test sessions, computed both per window and per session,
reported together with the underlying counts (true positives, false positives, false
negatives, true negatives). All five detectors above are reported in one table, per window
and per session.

## Negative findings

All numbers in this section are printed by `analysis/negative_findings.py`, run on the raw
Pi CSV files (`python analysis/negative_findings.py ~/motorsense-raw-data`; the raw files
are not in the repository). Values are plateau means ± sample standard deviation. Plateau:
for sessions with a `_warmup` segment, all windows after it; for every other session, the
last 90 windows. Percentages are the change of the test mean relative to the reference mean.

### Baseline shift after mechanical handling

| Session | Role | Windows | vib_rms_g | vib_peak_g | current_ma |
|---|---|---|---|---|---|
| r2_normal_01 | reference (old baseline) | 480 | 0.0968 ± 0.0049 | 0.2388 ± 0.0291 | 822.6 ± 4.7 |
| r3_normal_01 | new baseline | 540 | 0.1193 ± 0.0057 | 0.3135 ± 0.0353 | 815.5 ± 4.6 |
| r4_band_normal_a | new baseline | 90 | 0.1452 ± 0.0100 | 0.3794 ± 0.0449 | 823.3 ± 2.5 |

Vibration RMS rose by 23.2 % from r2_normal_01 to r3_normal_01 (0.0968 g to 0.1193 g) and by
49.9 % from r2_normal_01 to r4_band_normal_a, with no fault applied; current changed by
-0.9 % and +0.1 %. This is why the normal sessions used for training, validation and testing
are separate recordings.

### Imbalance (taped weights)

| Session | Role | Windows | vib_rms_g | vib_peak_g | current_ma |
|---|---|---|---|---|---|
| r4_test_drag | reference (no-effect run) | 90 | 0.1482 ± 0.0105 | 0.3779 ± 0.0429 | 824.2 ± 4.3 |
| r4_band_normal_a | reference | 90 | 0.1452 ± 0.0100 | 0.3794 ± 0.0449 | 823.3 ± 2.5 |
| r3_test_fault | imbalance | 90 | 0.1346 ± 0.0056 | 0.3494 ± 0.0386 | 823.8 ± 2.7 |
| r3_test_fault2 | imbalance | 90 | 0.1249 ± 0.0064 | 0.3247 ± 0.0356 | 824.2 ± 2.7 |

Against these references, vibration RMS of the imbalance runs was 7.3 % to 15.7 % lower,
not higher (r3_test_fault -9.2 % and -7.3 %, r3_test_fault2 -15.7 % and -14.0 % against
r4_test_drag and r4_band_normal_a). Current changed by 0.1 % or less.

### Imbalance, frequency bands

| Session | vib_rms_g | 1 to 6 Hz | 6 to 20 Hz | 20 to 50 Hz | 50 to 100 Hz |
|---|---|---|---|---|---|
| r4_band_normal_a | 0.1452 ± 0.0100 | 0.0305 | 0.0553 | 0.0642 | 0.1125 |
| r4_band_fault_a | 0.1457 ± 0.0091 | 0.0284 | 0.0577 | 0.0684 | 0.1077 |
| Change | +0.3 % | -7.1 % | +4.3 % | +6.4 % | -4.3 % |

Band means in g, 90 windows each. No band separates the two runs by more than 7.1 %, and the
changes go in both directions.

### Loosened motor mount

| Session | Role | Windows | vib_rms_g | vib_peak_g | current_ma |
|---|---|---|---|---|---|
| r3_normal_01 | reference | 540 | 0.1193 ± 0.0057 | 0.3135 ± 0.0353 | 815.5 ± 4.6 |
| r3_test_loose | loose mount | 90 | 0.1246 ± 0.0098 | 0.3374 ± 0.0818 | 825.1 ± 3.6 |

Vibration RMS rose by 4.4 %, vibration peak by 7.6 % and current by 1.2 %.

### Friction by hand

Only seconds with current above 500 mA.

| Session | Role | Windows | current_ma | current min to max | vib_rms_g |
|---|---|---|---|---|---|
| r3_normal_01 | reference | 540 | 815.5 ± 4.6 | 805 to 854 | 0.1193 ± 0.0057 |
| r4_band_normal_a | reference | 90 | 823.3 ± 2.5 | 816 to 829 | 0.1452 ± 0.0100 |
| r4_tune | friction | 59 | 831.0 ± 4.0 | 822 to 841 | 0.1090 ± 0.0277 |
| r4_tune2 | friction | 57 | 829.2 ± 3.2 | 819 to 835 | 0.1047 ± 0.0284 |

Current was 0.7 % to 1.9 % higher than in the references (r4_tune +1.9 % and +0.9 %,
r4_tune2 +1.7 % and +0.7 % against r3_normal_01 and r4_band_normal_a). The two normal
references differ from each other by 0.9 % in current (r4_band_normal_a against
r3_normal_01), with no fault applied.

### Conclusion

| Fault | Effect | Normal variation without a fault |
|---|---|---|
| Imbalance | Vibration RMS 7.3 % to 15.7 % lower than both references, not higher | r4_band_normal_a against r3_normal_01: +21.7 %. The imbalance runs were recorded after r3_normal_01 and before the r4 references, so this shift is mixed into the comparison |
| Imbalance, four bands | -7.1 % to +6.4 % per band, in both directions | |
| Loosened mount | Vibration RMS +4.4 % | r3_normal_01 against r2_normal_01: +23.2 % |
| Friction by hand | Current +0.7 % to +0.9 % against the reference from the same period (r4_band_normal_a); +1.7 % to +1.9 % against r3_normal_01 | r4_band_normal_a against r3_normal_01: +0.9 % |

None of these faults produces a change that is clearly larger than the variation between
normal sessions, so they are not detectable in this rig and are not part of the evaluation.

### For comparison: open motor lead

| Session | Role | Windows | vib_rms_g | vib_peak_g | current_ma |
|---|---|---|---|---|---|
| r4_band_normal_a | reference | 90 | 0.1452 ± 0.0100 | 0.3794 ± 0.0449 | 823.3 ± 2.5 |
| r4_test_open | one motor lead open | 90 | 0.1642 ± 0.0067 | 0.4213 ± 0.0425 | 703.2 ± 2.9 |

Current fell by 14.6 % (823.3 to 703.2 mA) and vibration RMS rose by 13.1 %. This is the fault
used in the test fault sessions.
