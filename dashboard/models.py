"""
Dashboard Models for Predictive Maintenance System
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Equipment(models.Model):
    """Equipment/Asset Model"""
    EQUIPMENT_TYPES = [
        ('PUMP', 'Pump'),
        ('MOTOR', 'Motor'),
        ('COMPRESSOR', 'Compressor'),
        ('TURBINE', 'Turbine'),
        ('GENERATOR', 'Generator'),
        ('OTHER', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('OPERATIONAL', 'Operational'),
        ('MAINTENANCE', 'Under Maintenance'),
        ('WARNING', 'Warning'),
        ('CRITICAL', 'Critical'),
        ('OFFLINE', 'Offline'),
    ]
    
    equipment_id = models.CharField(max_length=50, unique=True, primary_key=True)
    name = models.CharField(max_length=200)
    equipment_type = models.CharField(max_length=20, choices=EQUIPMENT_TYPES)
    location = models.CharField(max_length=200)
    installation_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPERATIONAL')
    last_maintenance = models.DateTimeField(null=True, blank=True)
    next_maintenance = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'equipment'
        ordering = ['equipment_id']
        verbose_name = 'Equipment'
        verbose_name_plural = 'Equipment'
    
    def __str__(self):
        return f"{self.equipment_id} - {self.name}"


class SensorData(models.Model):
    """Time-series sensor data (TimescaleDB hypertable)"""
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='sensor_data')
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    SOURCE_CHOICES = [
        ('pi', 'Raspberry Pi'),
        ('sample', 'Sample (synthetic)'),
    ]

    # Vibration data (per-axis values are not sent by the Pi, so they may be empty)
    vibration_x = models.FloatField(null=True, blank=True, help_text="Vibration X-axis (g)")
    vibration_y = models.FloatField(null=True, blank=True, help_text="Vibration Y-axis (g)")
    vibration_z = models.FloatField(null=True, blank=True, help_text="Vibration Z-axis (g)")
    
    # Temperature data
    temperature = models.FloatField(help_text="Temperature (°C)")
    
    # Current data
    current = models.FloatField(help_text="Motor current in amperes (A), not milliamperes")
    
    # Supply voltage
    bus_voltage = models.FloatField(null=True, blank=True, help_text="Bus voltage (V)")
    
    # Calculated features
    vibration_rms = models.FloatField(null=True, blank=True, help_text="Root Mean Square of vibration")
    vibration_peak = models.FloatField(null=True, blank=True, help_text="Peak vibration value")
    
    # Provenance
    run_label = models.CharField(max_length=64, blank=True, help_text="Name of the recording session")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default='pi')
    
    class Meta:
        db_table = 'sensor_data'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['equipment', '-timestamp']),
            models.Index(fields=['-timestamp']),
        ]
        verbose_name = 'Sensor Data'
        verbose_name_plural = 'Sensor Data'
    
    def __str__(self):
        return f"{self.equipment.equipment_id} - {self.timestamp}"
    
    def save(self, *args, **kwargs):
        """Calculate derived values before saving"""
        if self.vibration_x and self.vibration_y and self.vibration_z:
            # Calculate RMS
            self.vibration_rms = (
                (self.vibration_x**2 + self.vibration_y**2 + self.vibration_z**2) / 3
            ) ** 0.5
            # Calculate Peak
            self.vibration_peak = max(abs(self.vibration_x), abs(self.vibration_y), abs(self.vibration_z))
        super().save(*args, **kwargs)


class Prediction(models.Model):
    """ML Model Predictions"""
    HEALTH_STATUS = [
        ('HEALTHY', 'Healthy'),
        ('WARNING', 'Warning'),
        ('CRITICAL', 'Critical'),
        ('FAILURE', 'Failure Imminent'),
    ]
    
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='predictions')
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    # Prediction results
    failure_probability = models.FloatField(help_text="Probability of failure (0-1)")
    health_score = models.FloatField(help_text="Equipment health score (0-100)")
    health_status = models.CharField(max_length=20, choices=HEALTH_STATUS)
    
    # Remaining useful life
    rul_days = models.IntegerField(help_text="Remaining Useful Life in days", null=True, blank=True)
    
    # Model information
    model_version = models.CharField(max_length=50)
    confidence_score = models.FloatField(help_text="Model confidence (0-1)")
    
    # Feature importance (stored as JSON-like text)
    feature_contributions = models.JSONField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'predictions'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['equipment', '-timestamp']),
            models.Index(fields=['-timestamp']),
        ]
        verbose_name = 'Prediction'
        verbose_name_plural = 'Predictions'
    
    def __str__(self):
        return f"{self.equipment.equipment_id} - {self.health_status} ({self.timestamp})"


class MaintenanceLog(models.Model):
    """Maintenance history and scheduling"""
    MAINTENANCE_TYPES = [
        ('PREVENTIVE', 'Preventive'),
        ('CORRECTIVE', 'Corrective'),
        ('PREDICTIVE', 'Predictive'),
        ('EMERGENCY', 'Emergency'),
    ]
    
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='maintenance_logs')
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SCHEDULED')
    
    scheduled_date = models.DateTimeField()
    completed_date = models.DateTimeField(null=True, blank=True)
    
    technician = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    description = models.TextField()
    notes = models.TextField(blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Link to prediction that triggered this maintenance
    triggered_by_prediction = models.ForeignKey(Prediction, on_delete=models.SET_NULL, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'maintenance_logs'
        ordering = ['-scheduled_date']
        verbose_name = 'Maintenance Log'
        verbose_name_plural = 'Maintenance Logs'
    
    def __str__(self):
        return f"{self.equipment.equipment_id} - {self.maintenance_type} ({self.scheduled_date.date()})"


class Alert(models.Model):
    """System alerts and notifications"""
    SEVERITY_LEVELS = [
        ('INFO', 'Information'),
        ('WARNING', 'Warning'),
        ('CRITICAL', 'Critical'),
        ('EMERGENCY', 'Emergency'),
    ]
    
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='alerts')
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS)
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Link to related prediction
    related_prediction = models.ForeignKey(Prediction, on_delete=models.SET_NULL, null=True, blank=True)
    
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'alerts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['equipment', '-created_at']),
            models.Index(fields=['severity', '-created_at']),
            models.Index(fields=['is_acknowledged']),
        ]
        verbose_name = 'Alert'
        verbose_name_plural = 'Alerts'
    
    def __str__(self):
        return f"{self.severity} - {self.title}"


class SystemConfiguration(models.Model):
    """System-wide configuration and settings"""
    config_key = models.CharField(max_length=100, unique=True)
    config_value = models.TextField()
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        db_table = 'system_configuration'
        verbose_name = 'System Configuration'
        verbose_name_plural = 'System Configurations'
    
    def __str__(self):
        return self.config_key
class PredictionHistory(models.Model):
    """Store prediction history for trends analysis"""
    equipment = models.ForeignKey(
        Equipment, 
        on_delete=models.CASCADE, 
        related_name='prediction_history'  # ✅ Changed from 'predictions'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    rul = models.FloatField(help_text="Predicted Remaining Useful Life")
    confidence = models.FloatField(help_text="Prediction confidence percentage")
    status = models.CharField(max_length=20, choices=[
        ('healthy', 'Healthy'),
        ('caution', 'Caution'),
        ('critical', 'Critical')
    ])
    data_source = models.CharField(max_length=20, choices=[
        ('simulated', 'Simulated'),
        ('live', 'Live Sensors')
    ], default='simulated')
    
    # Health metrics
    vibration_health = models.FloatField(default=0)
    temperature_health = models.FloatField(default=0)
    current_health = models.FloatField(default=0)
    average_health = models.FloatField(default=0)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['equipment', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.equipment.equipment_id} - RUL: {self.rul} - {self.timestamp}"

class AnomalyScore(models.Model):
    """
    One scored (or deliberately unscored) second from the live scorer or a replay.
    Written only by the score_live and replay_session commands.
    """
    MODE_CHOICES = [
        ('live', 'Live'),
        ('replay', 'Replay of a recorded session'),
    ]
    MACHINE_STATE_CHOICES = [
        ('idle', 'Idle'),
        ('warming_up', 'Warming up'),
        ('running', 'Running'),
    ]

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='anomaly_scores')
    timestamp = models.DateTimeField(help_text="Timestamp of the sensor reading that was scored")
    run_label = models.CharField(max_length=64, blank=True)
    score = models.FloatField(null=True, blank=True, help_text="Reconstruction error; empty when not scored")
    threshold = models.FloatField()
    above_threshold = models.BooleanField(null=True, blank=True, help_text="Empty when not scored")
    alert_active = models.BooleanField(default=False)
    machine_state = models.CharField(max_length=16, choices=MACHINE_STATE_CHOICES)
    mode = models.CharField(max_length=8, choices=MODE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'anomaly_scores'
        ordering = ['-timestamp']
        constraints = [
            models.UniqueConstraint(fields=['equipment', 'timestamp', 'mode'], name='uniq_anomaly_score_second'),
        ]
        indexes = [
            models.Index(fields=['mode', 'equipment', '-timestamp']),
            models.Index(fields=['mode', 'run_label']),
        ]

    def __str__(self):
        return f"{self.mode} {self.equipment_id} {self.timestamp} {self.machine_state} {self.score}"


class AlertEpisode(models.Model):
    """An alert from firing (10 s above threshold) until the first second not above it."""
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='alert_episodes')
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True, help_text="Empty while the alert is active")
    peak_score = models.FloatField()
    run_label = models.CharField(max_length=64, blank=True)
    mode = models.CharField(max_length=8, choices=AnomalyScore.MODE_CHOICES)
    open_at_end_of_recording = models.BooleanField(
        default=False,
        help_text="Replay only: the alert was still active at the last reading of the recording, "
                  "so ended_at is the end of the data, not the end of the alert",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'alert_episodes'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['mode', 'equipment', '-started_at']),
            models.Index(fields=['mode', 'run_label']),
        ]

    def __str__(self):
        return f"{self.mode} {self.equipment_id} {self.started_at} - {self.ended_at or 'active'}"


class ScorerHeartbeat(models.Model):
    """Last poll of the live scorer per equipment, so the API can tell whether it is running."""
    equipment = models.OneToOneField(Equipment, on_delete=models.CASCADE, related_name='scorer_heartbeat')
    last_poll_at = models.DateTimeField()
    last_scored_reading_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'scorer_heartbeats'

    def __str__(self):
        return f"{self.equipment_id} polled {self.last_poll_at}"
