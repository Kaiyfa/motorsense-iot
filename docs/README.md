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
