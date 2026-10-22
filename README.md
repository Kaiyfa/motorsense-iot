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
```
source venv/bin/activate
python manage.py migrate
python manage.py runserver                      # dashboard: http://127.0.0.1:8000/
python manage.py score_live --equipment EQ-001  # second terminal: live scorer
```
Configuration comes from `.env` (see `.env.example`). More commands, including replays
and reproducing the evaluation, are in [docs/README.md](docs/README.md).

## Layout
- `dashboard/` - the Django app: models, ingest and JSON API, pages, scorer service
- `dashboard/ml/` - dataset roles, evaluation, live scoring core
- `monitor/` - project settings
- `analysis/` - scripts that reproduce figures in the docs
- `docs/` - evaluation plan, how to reproduce, screenshots
