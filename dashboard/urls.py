# dashboard/urls.py

from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # Main dashboards
    path('', views.dashboard, name='dashboard'),  # Simulated/Historical dashboard
    path('live/', views.live_dashboard, name='live_dashboard'),  # Live sensor dashboard
    
    # API endpoints - Simulated/Historical
    path('api/', views.index, name='api_index'),
    path('api/equipment/', views.equipment_list, name='equipment_list'),
    path('api/prediction/', views.get_prediction, name='get_prediction'),
    
    # API endpoints - Live Sensors
    path('api/live/reading/', views.live_reading, name='live_reading'),
    path('api/live/prediction/', views.live_prediction, name='live_prediction'),
    path('api/live/history/', views.live_sensor_history, name='live_sensor_history'),

    # Sensor ingest (Raspberry Pi, token auth)
    path('api/ingest/', views.ingest, name='ingest'),

    # Anomaly scores and alerts (written by score_live / replay_session)
    path('api/live/status/', views.live_status, name='live_status'),
    path('api/live/scores/', views.live_scores, name='live_scores'),
    path('api/alerts/', views.alerts, name='alerts'),
    path('api/replay/<str:label>/', views.replay_detail, name='replay_detail'),
]