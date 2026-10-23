# MotorSense IoT

Condition monitoring for a bench test rig: EQ-001, an Elegoo robot car with four DC motors,
wheels removed, running at fixed speed. A Raspberry Pi sends one reading per second
(vibration from an MPU-6050, current and pack voltage from an INA219, temperature from a
DS18B20). The Django app stores the readings in TimescaleDB, a separate scorer process
applies an LSTM autoencoder trained on normal sessions, and the dashboard shows the
machine state, the anomaly score and alerts, live or as a replay of a recorded session.

What the model can and cannot detect on this rig is documented, with numbers, in
[docs/evaluation_plan.md](docs/evaluation_plan.md) and `results/metrics.json`.

## Stack
- Django 4.2, PostgreSQL with TimescaleDB
- TensorFlow 2.13 / Keras, in the scorer process only (the web server does not load it)
- Plain JavaScript modules and Chart.js 4.4.0, served from the project's static files

## Run it

You need Python 3.10 (the results were produced with 3.10.13; tensorflow-macos 2.13 does not
support newer versions) and Docker. All commands run from the repository root.

1. Create a venv and install the web app:
   ```
   python3.10 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-ml.txt   # only for the live scorer, training and evaluation
   ```
   `requirements-ml.txt` was tested on macOS arm64 only; see the note in the file.
2. Copy `.env.example` to `.env` and set `SECRET_KEY`, `INGEST_TOKEN` and `DB_PASSWORD` (the
   file shows how to generate the first two).
3. Start TimescaleDB: `docker compose up -d`. This creates the container
   `motorsense_timescaledb` on port 5432, with the database and user from `.env.example` and
   `DB_PASSWORD` from `.env`. If that name or port is already in use, run the image
   `timescale/timescaledb:latest-pg15` under another name and port and set `DB_PORT` in
   `.env` to match.
4. Create the tables and the TimescaleDB hypertable, retention policy and aggregate:
   ```
   python manage.py migrate
   python manage.py setup_timescaledb
   ```
5. Create a login: `python manage.py createsuperuser`. Every page needs one.
6. Start the dashboard with `python manage.py runserver` and open http://127.0.0.1:8000/.
7. Readings arrive from the Pi at `/api/ingest/` with the bearer token from `.env` (see
   [testbed/README.md](testbed/README.md)). The first reading creates the equipment EQ-001.
8. Live scorer, in a second terminal: `python manage.py score_live --equipment EQ-001`. It
   needs the trained model in `ml_models/motorsense_ae/` (`model.keras`, `scaler.json`,
   `threshold.json`). The model is not in the repository. `python -m dashboard.ml.run_evaluation`
   produces it from the dataset that `export_dataset` exports from a database holding the
   recorded sessions, and those recordings are not in the repository either. Without the model,
   the command stops with "No such file or directory: ... ml_models/motorsense_ae/scaler.json".

Tests: `python manage.py test` (needs the database from step 3; Django creates and drops its own
test database). More commands, including replays and reproducing the evaluation, are in
[docs/README.md](docs/README.md).

## Layout
- `dashboard/` - the Django app: models, ingest and JSON API, pages, scorer service
- `dashboard/ml/` - dataset roles, evaluation, live scoring core
- `monitor/` - project settings
- `analysis/` - scripts that reproduce figures in the docs
- `docs/` - evaluation plan, how to reproduce, screenshots
- `testbed/` - the logger that runs on the Raspberry Pi, and the rig's wiring
