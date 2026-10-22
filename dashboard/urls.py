# dashboard/urls.py

from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # Pages
    path('', views.dashboard, name='dashboard'),                    # Overview, Live
    path('replay/', views.replay_overview, name='replay'),          # Overview, Replay
    path('<slug:tab>/', views.tab_placeholder, name='tab'),         # Sensors, Alerts, ... (part 2)

    # API endpoints - Live Sensors
    path('api/live/reading/', views.live_reading, name='live_reading'),
    path('api/live/history/', views.live_sensor_history, name='live_sensor_history'),

    # Sensor ingest (Raspberry Pi, token auth)
    path('api/ingest/', views.ingest, name='ingest'),

    # Anomaly scores and alerts (written by score_live / replay_session)
    path('api/live/status/', views.live_status, name='live_status'),
    path('api/live/scores/', views.live_scores, name='live_scores'),
    path('api/live/timeline/', views.live_timeline, name='live_timeline'),
    path('api/alerts/', views.alerts, name='alerts'),
    path('api/replay/<str:label>/', views.replay_detail, name='replay_detail'),
    path('api/replay/<str:label>/readings/', views.replay_readings, name='replay_readings'),
]