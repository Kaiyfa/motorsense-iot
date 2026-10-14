from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.dateparse import parse_datetime
from .models import Equipment, SensorData
from dashboard.ml.ml_service import prediction_service
from datetime import datetime, timedelta, timezone as dt_timezone
import hmac
import logging
import json
import math
from django.utils import timezone 

logger = logging.getLogger(__name__)


# AUTHENTICATION VIEWS

def login_view(request):
    """Login page view"""
    if request.user.is_authenticated:
        return redirect('dashboard:dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            auth_login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard:dashboard'
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'registration/login.html')


def logout_view(request):
    """Logout view"""
    auth_logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('login')



# DASHBOARD VIEWS

@login_required(login_url='login')
def dashboard(request):
    """Main dashboard view"""
    context = {
        'equipment_count': Equipment.objects.count(),
        'sensor_data_count': SensorData.objects.count(),
        'user': request.user,
    }
    return render(request, 'dashboard/dashboard.html', context)


# API ENDPOINTS

@login_required(login_url='login')
def index(request):
    """API health check endpoint"""
    equipment_count = Equipment.objects.count()
    sensor_data_count = SensorData.objects.count()
    
    return JsonResponse({
        'equipment_count': equipment_count,
        'sensor_data_count': sensor_data_count,
        'status': 'API is working',
        'user': request.user.username
    })


@login_required(login_url='login')
def equipment_list(request):
    """Equipment list API endpoint"""
    equipment = Equipment.objects.all().values('equipment_id', 'name', 'status')
    return JsonResponse(list(equipment), safe=False)


@login_required(login_url='login')
def get_prediction(request):
    """
    Generate comprehensive AI prediction with LSTM model
    
    Returns:
        JSON with prediction, recommendations, alerts, cost impact, and trend metrics
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        # Extract request parameters
        equipment_type = request.POST.get('equipment_type', 'Pump')
        equipment_id = request.POST.get('equipment_id', 'EQ-001')
        location = request.POST.get('location', '')
        
        logger.info(f"🔄 Prediction request: {equipment_type} {equipment_id} @ {location}")
        
        # Load model if not already loaded
        if not prediction_service.model_loaded:
            logger.info("📦 Loading LSTM model...")
            if not prediction_service.load_model():
                raise Exception("Failed to load LSTM model")
        
        # Generate prediction using LSTM model
        prediction_result = prediction_service.predict_from_equipment(
            equipment_id=equipment_id,
            equipment_type=equipment_type
        )
        
        # Add metadata
        prediction_result['location'] = location
        prediction_result['timestamp'] = datetime.now().isoformat()
        prediction_result['user'] = request.user.username
        
        # Generate AI recommendations
        recommendations = generate_ai_recommendations(prediction_result)
        
        # Generate contextual alerts
        alerts = generate_contextual_alerts(prediction_result)
        
        # Calculate cost impact analysis
        cost_impact = calculate_cost_impact(prediction_result, recommendations)
        
        # Calculate trend metrics
        trend_metrics = calculate_trend_metrics(prediction_result)
        
        logger.info(f"✅ Prediction complete: RUL={prediction_result['rul']}, Status={prediction_result['status']}")
        
        # Return comprehensive response
        return JsonResponse({
            'success': True,
            'prediction': prediction_result,
            'recommendations': recommendations,
            'alerts': alerts,
            'costImpact': cost_impact,
            'trendMetrics': trend_metrics
        })
        
    except Exception as e:
        logger.error(f"❌ Prediction error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# AI RECOMMENDATION ENGINE

def generate_ai_recommendations(prediction: dict) -> list:
    """
    Generate intelligent maintenance recommendations based on prediction
    
    Matches Replit's recommendation structure with:
    - Priority levels (HIGH/MEDIUM/LOW)
    - Cost impact estimates
    - Estimated savings
    - Actionable steps
    """
    recommendations = []
    rul = prediction['rul']
    status = prediction['status']
    health = prediction['health_metrics']
    equipment_id = prediction['equipment_id']
    
    # CRITICAL STATUS: Immediate action required
    if status == 'critical':
        recommendations.append({
            'id': 'critical_maintenance',
            'priority': 'HIGH',
            'title': 'Schedule Preventive Inspection',
            'description': f'Critical wear patterns detected on {equipment_id}. RUL critically low at {rul:.1f} cycles. Immediate inspection required to prevent catastrophic failure.',
            'action': 'Schedule emergency inspection within 24-48 hours and prepare replacement parts (bearings, seals, gaskets).',
            'costImpact': '$50,000 - $75,000',
            'estimatedSavings': '$500,000 (avoided unplanned downtime)'
        })
    
    # CAUTION STATUS: Plan maintenance
    elif status == 'caution':
        recommendations.append({
            'id': 'preventive_maintenance',
            'priority': 'MEDIUM',
            'title': 'Schedule Preventive Inspection',
            'description': f'Moderate wear patterns detected on {equipment_id}. Schedule inspection within 2-3 weeks to prevent unexpected failures.',
            'action': 'Schedule inspection within 2-3 weeks and prepare replacement parts.',
            'costImpact': '$2,500 - $3,500',
            'estimatedSavings': '$15,000 (avoided downtime)'
        })
    
    # TEMPERATURE HEALTH: Operating parameter optimization
    if health['temperatureHealth'] > 80:
        temp_diff = int((health['temperatureHealth'] - 72) * 0.25)
        recommendations.append({
            'id': 'optimize_temperature',
            'priority': 'MEDIUM',
            'title': 'Optimize Operating Parameters',
            'description': f'Current operating temperature is {temp_diff}% higher than optimal range. Elevated temperatures accelerate component degradation.',
            'action': 'Reduce operating speed by 5% and increase cooling system efficiency. Monitor temperature trends over next 48 hours.',
            'costImpact': '$1,200 - $1,800',
            'estimatedSavings': '$5,000 annually (reduced wear)'
        })
    elif health['temperatureHealth'] < 60:
        recommendations.append({
            'id': 'investigate_cooling',
            'priority': 'MEDIUM',
            'title': 'Investigate Cooling System',
            'description': f'Temperature readings indicate potential cooling system inefficiency. Current health at {health["temperatureHealth"]:.1f}%.',
            'action': 'Inspect cooling system, check coolant levels, and verify thermal sensor accuracy.',
            'costImpact': '$800 - $1,500',
            'estimatedSavings': '$3,000 (prevented thermal damage)'
        })
    
    # SPEED HEALTH: Mechanical inspection
    if health['speedHealth'] < 70:
        recommendations.append({
            'id': 'mechanical_inspection',
            'priority': 'MEDIUM',
            'title': 'Mechanical System Inspection',
            'description': f'Speed health at {health["speedHealth"]:.1f}% indicates potential mechanical wear. Motor speed variations detected outside normal parameters.',
            'action': 'Check motor bearings, drive system alignment, and lubrication levels. Schedule vibration analysis.',
            'costImpact': '$1,500 - $2,500',
            'estimatedSavings': '$8,000 (prevented bearing failure)'
        })
    
    # SENSOR CALIBRATION: Routine maintenance
    if health['speedHealth'] < 75 or health['pressureHealth'] < 75:
        recommendations.append({
            'id': 'sensor_calibration',
            'title': 'Update Sensor Calibration',
            'priority': 'LOW',
            'description': 'Sensors have been in operation for extended period without recalibration. Sensor drift may affect prediction accuracy.',
            'action': 'Schedule sensor calibration during next planned maintenance window.',
            'costImpact': '$400 - $600',
            'estimatedSavings': None
        })
    
    # HEALTHY STATUS: Continue monitoring
    if status == 'healthy':
        recommendations.append({
            'id': 'routine_monitoring',
            'title': 'Continue Routine Monitoring',
            'priority': 'LOW',
            'description': f'Equipment {equipment_id} is operating within normal parameters. RUL: {rul:.1f} cycles remaining.',
            'action': 'Maintain current monitoring schedule and operating conditions. Next inspection in 4-6 weeks.',
            'costImpact': '$200 - $400',
            'estimatedSavings': None
        })
    
    return recommendations


# ALERT GENERATION SYSTEM

def generate_contextual_alerts(prediction: dict) -> list:
    """
    Generate contextual alerts based on sensor thresholds and equipment status
    
    Returns alerts with:
    - Severity levels (CRITICAL/WARNING/INFO)
    - Specific sensor anomalies
    - Timestamps
    - Equipment context
    """
    alerts = []
    rul = prediction['rul']
    health = prediction['health_metrics']
    equipment_id = prediction['equipment_id']
    
    # CRITICAL RUL ALERT
    if rul < 30:
        alerts.append({
            'id': f'alert_critical_rul_{int(datetime.now().timestamp())}',
            'severity': 'critical',
            'title': 'Critical: Equipment Approaching Failure',
            'description': f'RUL has dropped to {rul:.1f} cycles. Equipment may fail within {int(rul)} operational cycles. Immediate action required.',
            'equipmentId': equipment_id,
            'timestamp': '15 minutes ago',
        })
    
    # PERFORMANCE DEGRADATION WARNING
    if health['temperatureHealth'] < 60:
        alerts.append({
            'id': f'alert_degradation_{int(datetime.now().timestamp())}',
            'severity': 'warning',
            'title': 'Warning: Gradual Performance Degradation',
            'description': f'Equipment health at {health["temperatureHealth"]:.1f}%. Monitor closely for further degradation. Temperature sensors showing elevated readings.',
            'equipmentId': equipment_id,
            'timestamp': '15 minutes ago',
        })
    
    # SCHEDULED MAINTENANCE INFO
    if rul < 60:
        alerts.append({
            'id': f'alert_maintenance_{int(datetime.now().timestamp())}',
            'severity': 'info',
            'title': 'Scheduled Maintenance Window',
            'description': 'Routine maintenance scheduled for next week. Preventive inspection recommended based on current equipment health.',
            'equipmentId': equipment_id,
            'timestamp': '2 days ago',
        })
    
    # SENSOR ANOMALY WARNING
    if health['speedHealth'] < 70:
        alerts.append({
            'id': f'alert_sensor_anomaly_{int(datetime.now().timestamp())}',
            'severity': 'warning',
            'title': 'Sensor Reading Anomaly',
            'description': 'Sensor_21 showing unusual fluctuation patterns over the past 48 hours. Speed sensor readings vary outside normal operational range.',
            'equipmentId': equipment_id,
            'timestamp': '3 days ago',
        })
    
    return alerts


# COST IMPACT ANALYSIS

def calculate_cost_impact(prediction: dict, recommendations: list) -> dict:
    """
    Calculate comprehensive cost impact analysis
    
    Returns:
    - Total potential cost
    - Estimated savings
    - ROI percentage
    """
    total_cost = 0
    total_savings = 0
    
    for rec in recommendations:
        # Parse cost range (e.g., "$2,500 - $3,500")
        if rec.get('costImpact'):
            try:
                cost_str = rec['costImpact'].replace('$', '').replace(',', '')
                if ' - ' in cost_str:
                    low, high = cost_str.split(' - ')
                    avg_cost = (float(low) + float(high)) / 2
                else:
                    avg_cost = float(cost_str)
                total_cost += avg_cost
            except ValueError:
                pass
        
        # Parse savings (e.g., "$15,000 (avoided downtime)")
        if rec.get('estimatedSavings'):
            try:
                savings_str = rec['estimatedSavings'].split('(')[0]
                savings_str = savings_str.replace('$', '').replace(',', '').strip()
                total_savings += float(savings_str)
            except ValueError:
                pass
    
    # Calculate ROI
    roi = (total_savings / total_cost * 100) if total_cost > 0 else 0
    
    return {
        'totalCost': f"${int(total_cost):,}",
        'estimatedSavings': f"${int(total_savings):,}",
        'roi': f"{int(roi)}%"
    }


# TREND METRICS CALCULATION

def calculate_trend_metrics(prediction: dict) -> dict:
    """
    Calculate degradation rate and health trends
    
    In production, this would analyze historical predictions
    For now, calculates based on current state
    """
    rul = prediction['rul']
    health = prediction['health_metrics']
    
    # Calculate average health across all metrics
    avg_health = (
        health['speedHealth'] + 
        health['temperatureHealth'] + 
        health['pressureHealth']
    ) / 3
    
    # Estimate degradation rate
    # Assuming max RUL of 125 cycles (C-MAPSS dataset range)
    degradation_rate = ((125 - rul) / 125) * 2  # Percentage per prediction
    
    return {
        'degradationRate': round(degradation_rate, 2),
        'averageHealth': round(avg_health, 1)
    }


# SENSOR INGEST (Raspberry Pi)

INGEST_MAX_BODY_BYTES = 4 * 1024
LIVE_EQUIPMENT_ID = 'EQ-001'
LIVE_EQUIPMENT_NAME = 'Motor testbed'

# JSON field -> (min, max) accepted range
INGEST_RANGES = {
    'temp_c': (-20.0, 150.0),
    'vib_rms_g': (0.0, 20.0),
    'vib_peak_g': (0.0, 20.0),
    'current_ma': (0.0, 5000.0),
    'bus_v': (0.0, 30.0),
}


def _ingest_error(message, status=400):
    return JsonResponse({'status': 'error', 'error': message}, status=status)


def _has_valid_ingest_token(request):
    header = request.META.get('HTTP_AUTHORIZATION', '')
    scheme, _, token = header.partition(' ')
    if scheme != 'Bearer' or not token:
        return False
    return hmac.compare_digest(token.strip().encode(), settings.INGEST_TOKEN.encode())


@csrf_exempt
@require_POST
def ingest(request):
    """
    Store one sensor reading sent by the Raspberry Pi.

    Auth: 'Authorization: Bearer <INGEST_TOKEN>'.
    Body: {"equipment_id", "timestamp", "temp_c", "vib_rms_g", "vib_peak_g",
           "current_ma", "bus_v", "label"}
    """
    if not _has_valid_ingest_token(request):
        return _ingest_error('Missing or invalid token', status=401)

    try:
        content_length = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        content_length = 0
    if content_length > INGEST_MAX_BODY_BYTES or len(request.body) > INGEST_MAX_BODY_BYTES:
        return _ingest_error(f'Request body larger than {INGEST_MAX_BODY_BYTES} bytes', status=413)

    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return _ingest_error('Body is not valid JSON')
    if not isinstance(payload, dict):
        return _ingest_error('Body must be a JSON object')

    # Equipment
    equipment_id = payload.get('equipment_id', LIVE_EQUIPMENT_ID)
    if not isinstance(equipment_id, str) or not equipment_id or len(equipment_id) > 50:
        return _ingest_error('equipment_id must be a non-empty string of at most 50 characters')

    # Timestamp (ISO 8601, UTC assumed when no offset is given)
    raw_timestamp = payload.get('timestamp')
    if raw_timestamp is None:
        timestamp = timezone.now()
    else:
        timestamp = parse_datetime(raw_timestamp) if isinstance(raw_timestamp, str) else None
        if timestamp is None:
            return _ingest_error('timestamp must be an ISO 8601 datetime, e.g. 2026-10-14T12:00:00Z')
        if timezone.is_naive(timestamp):
            timestamp = timezone.make_aware(timestamp, dt_timezone.utc)

    # Numeric readings
    values = {}
    for field, (low, high) in INGEST_RANGES.items():
        value = payload.get(field)
        if value is None:
            return _ingest_error(f'{field} is required')
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _ingest_error(f'{field} must be a number')
        if not math.isfinite(value):
            return _ingest_error(f'{field} must be a finite number')
        if not low <= value <= high:
            return _ingest_error(f'{field}={value} is outside the allowed range {low}..{high}')
        values[field] = float(value)

    label = payload.get('label', '')
    if label is None:
        label = ''
    if not isinstance(label, str) or len(label) > 64:
        return _ingest_error('label must be a string of at most 64 characters')

    if equipment_id == LIVE_EQUIPMENT_ID:
        equipment, _ = Equipment.objects.get_or_create(
            equipment_id=LIVE_EQUIPMENT_ID,
            defaults={
                'name': LIVE_EQUIPMENT_NAME,
                'equipment_type': 'MOTOR',
                'location': 'Test bench',
                'installation_date': timezone.now().date(),
            },
        )
    else:
        equipment = Equipment.objects.filter(equipment_id=equipment_id).first()
        if equipment is None:
            return _ingest_error(f'Unknown equipment_id {equipment_id!r}')

    if SensorData.objects.filter(equipment=equipment, timestamp=timestamp, source='pi').exists():
        return JsonResponse({'status': 'duplicate'}, status=200)

    reading = SensorData.objects.create(
        equipment=equipment,
        timestamp=timestamp,
        temperature=values['temp_c'],
        vibration_rms=values['vib_rms_g'],
        vibration_peak=values['vib_peak_g'],
        current=values['current_ma'] / 1000.0,  # mA -> A
        bus_voltage=values['bus_v'],
        run_label=label,
        source='pi',
    )
    return JsonResponse({'status': 'created', 'id': reading.id}, status=201)


# LIVE SENSOR API ENDPOINTS
# These only ever return readings stored by /api/ingest/ (source="pi").
# There is no simulated fallback: no data means "no_data".

LIVE_MAX_AGE_SECONDS = 15


def _serialize_reading(reading):
    return {
        'temperature': reading.temperature,
        'vibration_rms': reading.vibration_rms,
        'vibration_peak': reading.vibration_peak,
        'current': reading.current,
        'bus_voltage': reading.bus_voltage,
        'run_label': reading.run_label,
    }


@login_required(login_url='login')
def live_reading(request):
    """
    Latest stored Pi reading for the equipment.

    status "ok"      -> reading is at most 15 s old
    status "no_data" -> no reading at all, or the latest one is older than 15 s
    """
    equipment_id = request.GET.get('equipment_id', LIVE_EQUIPMENT_ID)

    latest = SensorData.objects.filter(
        equipment_id=equipment_id, source='pi'
    ).order_by('-timestamp').first()

    if latest is None:
        return JsonResponse({
            'status': 'no_data',
            'equipment_id': equipment_id,
            'last_timestamp': None,
            'age_seconds': None,
        })

    age_seconds = round((timezone.now() - latest.timestamp).total_seconds(), 1)

    if age_seconds > LIVE_MAX_AGE_SECONDS:
        return JsonResponse({
            'status': 'no_data',
            'equipment_id': equipment_id,
            'last_timestamp': latest.timestamp.isoformat(),
            'age_seconds': age_seconds,
        })

    return JsonResponse({
        'status': 'ok',
        'equipment_id': equipment_id,
        'timestamp': latest.timestamp.isoformat(),
        'age_seconds': age_seconds,
        'reading': _serialize_reading(latest),
    })


@login_required(login_url='login')
def live_prediction(request):
    """No anomaly model has been trained on the testbed data yet."""
    return JsonResponse({'status': 'model_not_available'})


@login_required(login_url='login')
def live_dashboard(request):
    """
    Live Sensor Dashboard view
    Displays real-time sensor readings and continuous monitoring
    """
    context = {
        'user': request.user,
        'dashboard_type': 'live',
    }
    return render(request, 'dashboard/dashboard_live.html', context)


@login_required(login_url='login')
def live_sensor_history(request):
    """
    Stored Pi readings from the last N seconds (default 60, max 3600) for charts.
    Returns empty lists when nothing was received.
    """
    equipment_id = request.GET.get('equipment_id', LIVE_EQUIPMENT_ID)
    try:
        seconds = int(request.GET.get('seconds', 60))
    except ValueError:
        return JsonResponse({'status': 'error', 'error': 'seconds must be an integer'}, status=400)
    seconds = max(1, min(seconds, 3600))

    start_time = timezone.now() - timedelta(seconds=seconds)
    readings = SensorData.objects.filter(
        equipment_id=equipment_id,
        source='pi',
        timestamp__gte=start_time,
    ).order_by('timestamp')

    data = {
        'timestamps': [],
        'temperature': [],
        'vibration_rms': [],
        'current': [],
        'bus_voltage': [],
    }
    for reading in readings:
        data['timestamps'].append(reading.timestamp.isoformat())
        data['temperature'].append(reading.temperature)
        data['vibration_rms'].append(reading.vibration_rms)
        data['current'].append(reading.current)
        data['bus_voltage'].append(reading.bus_voltage)

    return JsonResponse({
        'status': 'ok' if data['timestamps'] else 'no_data',
        'equipment_id': equipment_id,
        'time_range_seconds': seconds,
        'data_points': len(data['timestamps']),
        'data': data,
    })
