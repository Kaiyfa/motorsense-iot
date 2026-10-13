# MotorSense IoT – Motor Health Dashboard

Production-grade Django web application for predictive maintenance using LSTM models.

## Tech Stack
- Django 4.2
- PostgreSQL + TimescaleDB
- TensorFlow/Keras
- Bootstrap 5

## Setup Instructions
1. Clone repository
2. Create virtual environment: `python3 -m venv venv`
3. Activate: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Configure database in `.env`
6. Run migrations: `python manage.py migrate`
7. Start server: `python manage.py runserver`

## Project Structure
- `dashboard/` - Main application
- `monitor/` - Project settings
- `static/` - CSS, JS, images
- `templates/` - HTML templates
- `ml_models/` - Trained models and scalers
