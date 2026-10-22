# dashboard/urls.py

from django.urls import path
from . import views, views_tabs

app_name = 'dashboard'

urlpatterns = [
    # Pages
    path('', views.dashboard, name='dashboard'),                    # Overview, Live
    path('replay/', views.replay_overview, name='replay'),          # Overview, Replay
    path('sensors/', views_tabs.sensors_page, name='sensors'),
    path('alerts/', views_tabs.alerts_page, name='alerts_page'),
    path('maintenance/', views_tabs.maintenance_page, name='maintenance'),
    path('maintenance/entries/', views_tabs.maintenance_add, name='maintenance_add'),
    path('maintenance/entries/<int:entry_id>/delete/', views_tabs.maintenance_delete, name='maintenance_delete'),
    path('maintenance/interval/', views_tabs.maintenance_interval, name='maintenance_interval'),
    path('evaluation/', views_tabs.evaluation_page, name='evaluation'),
    path('setup/', views_tabs.setup_page, name='setup'),

    # API endpoints - tabs
    path('api/sensors/', views_tabs.sensor_data, name='sensor_data'),
    path('api/sensors.csv', views_tabs.sensor_csv, name='sensor_csv'),
    path('api/alerts/table/', views_tabs.alert_table, name='alert_table'),
    path('api/alerts/<int:episode_id>/', views_tabs.alert_detail, name='alert_detail'),

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