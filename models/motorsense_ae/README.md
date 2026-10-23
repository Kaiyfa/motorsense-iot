# Saved model: three-feature autoencoder, seed 0

The model the live scorer (`manage.py score_live`) and the replays (`manage.py replay_session`)
use by default.

| File | Content | SHA-256 |
|---|---|---|
| `model.keras` | LSTM autoencoder (Keras 2.13) | `1dcd1ea70171fc580ee6dacc37a0133ab1bf935c1f8b8891a4be410232b72cf3` |
| `scaler.json` | Training mean and standard deviation of vib_rms_g, vib_peak_g and current | `0aebb51fbe81c2453db0a2b42dbe16a41a64be5f7f2292e0170d2e137829e809` |
| `threshold.json` | Alert threshold 2.9486 (99.5th percentile of the scores on r5_normal_04_redo) and the settings it belongs to | `8c51df03280a06e5971034f8b83ec96953d55fffe7c6fe641111f0e9cc4a173c` |

**How it was made**
- **Command:** the evaluation, `python -m dashboard.ml.run_evaluation`.
- **Training data:** the plan's training sessions (r5_normal_01, r5_normal_02, r5_normal_03), warm-up excluded, with seed 0.
- **Settings:** all fixed in `docs/evaluation_plan.md`.
- **Source commit:** `222c4ef621c9896ca06acda49dec3ec3236a700f`, recorded in `threshold.json` and in `results/metrics.json`, which also has the environment (Python 3.10.13, tensorflow-macos 2.13.0, keras 2.13.1, CPU only).

Running the evaluation again writes a new model to this folder (or to `--models DIR`).
Whether a rerun reproduces these files bit for bit was not checked.

The scorer loads the model with `compile=False` (inference only); see `docs/README.md`.
