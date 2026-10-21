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
| r5_check | Excluded (no reason given) |
| r5_normal_04 | Invalid session: current 950 to 995 mA, vibration RMS 0.18 to 0.27 g, 923 I2C errors, cause unknown |
| The extra 30 rows in r5_normal_03_warmup | An aborted start |
| Every row with source other than live | Excluded by rule |
| Any label not listed in this plan | Never assigned to a role by guessing |

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

## Metrics

Precision and recall on the test sessions, computed both per window and per session,
reported together with the underlying counts (true positives, false positives, false
negatives, true negatives).

## Negative findings

These faults were tried and are not detectable in this rig:

| Fault tried | Result |
|---|---|
| Taped imbalance weights | Vibration RMS rose by only 8 to 14 percent (0.133 to 0.137 g against 0.119 g) |
| Loosened motor mount | Vibration RMS rose by about 10 percent (0.124 to 0.132 g) |
| Friction applied by hand | Current did not change (mean 829 mA, max 835 mA against 823 to 825 mA) |
| Imbalance, vibration split into four frequency bands (1 to 6, 6 to 20, 20 to 50 and 50 to 100 Hz) | The bands did not separate the imbalance either |

Baseline vibration shifted by about 25 percent after mechanical handling (0.097 g to
0.12 g). This is why the normal sessions used for training, validation and testing are
separate recordings.
