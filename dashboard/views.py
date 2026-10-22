from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.dateparse import parse_datetime
from .models import AlertEpisode, AnomalyScore, Equipment, ScorerHeartbeat, SensorData
from dashboard import catalog
from dashboard.ml import saved_model
from dashboard.ml.constants import (
    ALERT_SECONDS, IDLE_CURRENT_A, MAX_GAP_SECONDS, SEQUENCE_LENGTH, WARMUP_SECONDS,
)
from datetime import datetime, timedelta, timezone as dt_timezone
import hmac
import logging
import json
import math
from django.utils import timezone 
from django.db import connection

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
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(
                    next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('dashboard:dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'registration/login.html')


def logout_view(request):
    """Logout view"""
    auth_logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('login')



# DASHBOARD PAGES

TABS = [
    ('overview', 'Overview'),
    ('sensors', 'Sensors'),
    ('alerts', 'Alerts'),
    ('maintenance', 'Maintenance'),
    ('evaluation', 'Evaluation'),
    ('setup', 'Setup'),
]
PLACEHOLDER_TABS = {key: name for key, name in TABS if key != 'overview'}

MODEL_FEATURES = [
    # model feature, display name, unit, digits
    ('vib_rms_g', 'Vibration RMS', 'g', 3),
    ('vib_peak_g', 'Vibration peak', 'g', 3),
    ('current', 'Current', 'A', 3),
]

SENSOR_TILES = [
    # min_span: smallest vertical range of the sparkline, so sensor noise is not blown up to full height
    {'key': 'vibration_rms', 'name': 'Vibration RMS', 'unit': 'g', 'digits': 3, 'min_span': 0.02,
     'info': 'Model input. MPU-6050 on a breadboard resting on the chassis; RMS of one second of 200 Hz samples.'},
    {'key': 'vibration_peak', 'name': 'Vibration peak', 'unit': 'g', 'digits': 3, 'min_span': 0.05,
     'info': 'Model input. Largest absolute value in one second of 200 Hz samples from the MPU-6050.'},
    {'key': 'current', 'name': 'Current', 'unit': 'A', 'digits': 3, 'min_span': 0.05,
     'info': 'Model input. INA219 in series with the battery pack. Not calibrated against a reference meter, '
             'so read it as a relative value.'},
    {'key': 'bus_voltage', 'name': 'Pack voltage', 'unit': 'V', 'digits': 2, 'min_span': 0.2,
     'info': 'Displayed only, not a model input: the pack state differs between sessions by up to 0.15 V, '
             'independent of any fault.'},
    {'key': 'temperature', 'name': 'Temperature', 'unit': '°C', 'digits': 1, 'min_span': 1.0,
     'info': 'Displayed only, not a model input: it rises 3 to 5 °C per session without reaching a plateau.'},
]


def _tabs(active, mode, replay_label=None):
    query = f'?mode=replay&session={replay_label}' if mode == 'replay' and replay_label else ''
    tabs = []
    for key, name in TABS:
        if key == 'overview':
            href = (reverse('dashboard:replay') + (f'?session={replay_label}' if replay_label else '')
                    if mode == 'replay' else reverse('dashboard:dashboard'))
        else:
            href = reverse('dashboard:tab', args=[key]) + query
        tabs.append({'key': key, 'name': name, 'href': href})
    return tabs


def _model_metadata():
    """Training baseline and threshold of the saved model (JSON files only; no TensorFlow)."""
    try:
        scaler, threshold, _ = saved_model.read_metadata()
    except (OSError, ValueError, KeyError):
        return None, None
    return scaler, threshold


def _overview_context(request, mode, replay_label=None, extra_config=None):
    scaler, threshold = _model_metadata()
    features = []
    for key, name, unit, digits in MODEL_FEATURES:
        base = scaler.get(key) if scaler else None
        features.append({
            'key': key, 'name': name,
            'baseline_text': (f"{base['mean']:.{digits}f} {unit} ± {base['std']:.{digits}f}"
                              if base else 'not available'),
        })
    config = {
        'mode': mode,
        'equipmentId': LIVE_EQUIPMENT_ID,
        'pollMs': 2000,
        'liveMaxAgeSeconds': LIVE_MAX_AGE_SECONDS,
        'warmupSeconds': WARMUP_SECONDS,
        'sequenceLength': SEQUENCE_LENGTH,
        'alertSeconds': ALERT_SECONDS,
        'idleCurrentA': IDLE_CURRENT_A,
        'maxGapSeconds': MAX_GAP_SECONDS,
        'changesWindowSeconds': 60,
        'tileWindowSeconds': 300,
        'threshold': threshold,
        'baseline': scaler,
        'featureDigits': {key: digits for key, _, _, digits in MODEL_FEATURES},
        'featureUnits': {key: unit for key, _, unit, _ in MODEL_FEATURES},
        'tiles': [{'key': t['key'], 'digits': t['digits'], 'minSpan': t['min_span']} for t in SENSOR_TILES],
        'urls': {
            'status': reverse('dashboard:live_status'),
            'scores': reverse('dashboard:live_scores'),
            'history': reverse('dashboard:live_sensor_history'),
        },
    }
    config.update(extra_config or {})
    return {
        'mode': mode,
        'active_tab': 'overview',
        'tabs': _tabs('overview', mode, replay_label),
        'replay_label': replay_label,
        'model_features': features,
        'tiles': SENSOR_TILES,
        'config': config,
    }


@login_required(login_url='login')
def dashboard(request):
    """Overview, Live mode."""
    return render(request, 'dashboard/overview.html', _overview_context(request, 'live'))


@login_required(login_url='login')
def replay_overview(request):
    """Overview, Replay mode: the recorded scores and readings of one session."""
    replayed = set(AnomalyScore.objects.filter(mode='replay').values_list('run_label', flat=True).distinct())
    sessions = [dict(s, replayed=s['label'] in replayed) for s in catalog.REPLAY_SESSIONS]
    labels = [s['label'] for s in sessions]

    label = request.GET.get('session')
    if label not in labels:
        label = next((s['label'] for s in sessions if s['replayed']), labels[0])
    try:
        pos = int(request.GET['pos'])
    except (KeyError, ValueError):
        pos = None

    groups = []
    for s in sessions:
        if not groups or groups[-1]['role_name'] != s['role_name']:
            groups.append({'role_name': s['role_name'], 'sessions': []})
        groups[-1]['sessions'].append(s)

    available = label in replayed
    context = _overview_context(request, 'replay', label, {
        'session': label,
        'sessionName': catalog.session_name(label),
        'pos': pos,
        'urls': {
            'replay': reverse('dashboard:replay_detail', args=[label]),
            'replayReadings': reverse('dashboard:replay_readings', args=[label]),
        },
    })
    context.update({'session_groups': groups, 'replay_available': available})
    return render(request, 'dashboard/overview.html', context)


@login_required(login_url='login')
def tab_placeholder(request, tab):
    """Sections that are built in part 2 of the dashboard rebuild."""
    if tab not in PLACEHOLDER_TABS:
        raise Http404('Unknown section')
    replay_label = request.GET.get('session') if request.GET.get('mode') == 'replay' else None
    if replay_label not in [s['label'] for s in catalog.REPLAY_SESSIONS]:
        replay_label = None
    mode = 'replay' if replay_label else 'live'
    return render(request, 'dashboard/placeholder.html', {
        'mode': mode,
        'active_tab': tab,
        'tabs': _tabs(tab, mode, replay_label),
        'replay_label': replay_label,
        'page_name': PLACEHOLDER_TABS[tab],
    })


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
        'vibration_peak': [],
        'current': [],
        'bus_voltage': [],
    }
    for reading in readings:
        data['timestamps'].append(reading.timestamp.isoformat())
        data['temperature'].append(reading.temperature)
        data['vibration_rms'].append(reading.vibration_rms)
        data['vibration_peak'].append(reading.vibration_peak)
        data['current'].append(reading.current)
        data['bus_voltage'].append(reading.bus_voltage)

    return JsonResponse({
        'status': 'ok' if data['timestamps'] else 'no_data',
        'equipment_id': equipment_id,
        'time_range_seconds': seconds,
        'data_points': len(data['timestamps']),
        'data': data,
    })



# ANOMALY SCORES AND ALERTS (written by the score_live / replay_session commands)
# These views only read the database; TensorFlow runs in the scorer process.
# Live endpoints return mode "live" rows only, so a replay is never shown as live.

SCORER_ALIVE_SECONDS = 10
STATE_LOOKBACK = timedelta(hours=24)
LIVE_SCORES_MAX_MINUTES = 24 * 60


def _iso(value):
    return value.isoformat() if value else None


def _score_json(row):
    return {
        'timestamp': _iso(row.timestamp),
        'run_label': row.run_label,
        'machine_state': row.machine_state,
        'score': row.score,
        'threshold': row.threshold,
        'above_threshold': row.above_threshold,
        'alert_active': row.alert_active,
    }


def _episode_json(row):
    return {
        'equipment_id': row.equipment_id,
        'started_at': _iso(row.started_at),
        'ended_at': _iso(row.ended_at),
        'active': row.ended_at is None,
        'peak_score': row.peak_score,
        'run_label': row.run_label,
        'mode': row.mode,
        'open_at_end_of_recording': row.open_at_end_of_recording,
    }


@login_required(login_url='login')
def live_status(request):
    """Machine state and alert status of the live scorer (mode live only)."""
    equipment_id = request.GET.get('equipment_id', LIVE_EQUIPMENT_ID)
    now = timezone.now()

    latest = (AnomalyScore.objects.filter(mode='live', equipment_id=equipment_id)
              .order_by('-timestamp').first())
    last_reading = (SensorData.objects.filter(equipment_id=equipment_id, source='pi')
                    .order_by('-timestamp').values_list('timestamp', flat=True).first())
    heartbeat = ScorerHeartbeat.objects.filter(equipment_id=equipment_id).first()
    heartbeat_age = (now - heartbeat.last_poll_at).total_seconds() if heartbeat else None
    state = _state_details(latest) if latest else {}

    return JsonResponse({
        'equipment_id': equipment_id,
        'mode': 'live',
        'machine_state': latest.machine_state if latest else None,
        'latest_score': latest.score if latest else None,
        'latest_score_timestamp': _iso(latest.timestamp) if latest else None,
        'threshold': latest.threshold if latest else None,
        'alert_active': latest.alert_active if latest else False,
        'seconds_since_last_reading': round((now - last_reading).total_seconds(), 1) if last_reading else None,
        'scorer_alive': heartbeat_age is not None and heartbeat_age <= SCORER_ALIVE_SECONDS,
        'scorer_last_poll_seconds_ago': round(heartbeat_age, 1) if heartbeat_age is not None else None,
        'state_since': _iso(state.get('since')),
        'seconds_in_state': round((now - state['since']).total_seconds(), 1) if state else None,
        'warmup_elapsed_seconds': state.get('warmup_elapsed_seconds'),
        'consecutive_seconds_above_threshold': state.get('consecutive_above'),
        'scoring_starts_in_seconds': state.get('scoring_starts_in'),
    })


def _state_details(latest):
    """When the latest live machine state began, plus warm-up, buffer and run-length details."""
    rows = AnomalyScore.objects.filter(mode='live', equipment_id=latest.equipment_id)
    boundary = (rows.filter(timestamp__lt=latest.timestamp).exclude(machine_state=latest.machine_state)
                .order_by('-timestamp').values_list('timestamp', flat=True).first())
    # A gap of more than MAX_GAP_SECONDS resets the scorer's state machine, so it also
    # starts a new state run here (looking back at most STATE_LOOKBACK).
    lower = latest.timestamp - STATE_LOOKBACK
    if boundary is None or boundary < lower:
        boundary_or_lower = lower
    else:
        boundary_or_lower = boundary
    with connection.cursor() as cursor:
        cursor.execute(
            '''
            SELECT max(timestamp) FROM (
                SELECT timestamp, timestamp - lag(timestamp) OVER (ORDER BY timestamp) AS gap
                FROM anomaly_scores
                WHERE mode = 'live' AND equipment_id = %s AND timestamp > %s AND timestamp <= %s
            ) runs
            WHERE gap > %s
            ''',
            [latest.equipment_id, boundary_or_lower, latest.timestamp, timedelta(seconds=MAX_GAP_SECONDS)],
        )
        after_gap = cursor.fetchone()[0]
    in_state = rows.filter(timestamp__lte=latest.timestamp)
    if after_gap is not None:
        in_state = in_state.filter(timestamp__gte=after_gap)
    elif boundary is not None:
        in_state = in_state.filter(timestamp__gt=boundary)
    since = in_state.order_by('timestamp').values_list('timestamp', flat=True).first()

    details = {'since': since}
    if latest.machine_state == 'warming_up':
        details['warmup_elapsed_seconds'] = round((latest.timestamp - since).total_seconds(), 1)
    if latest.machine_state == 'running' and latest.score is None:
        buffered = in_state.filter(score__isnull=True).count()
        details['scoring_starts_in'] = max(0, SEQUENCE_LENGTH - buffered)
    recent = list(rows.filter(timestamp__lte=latest.timestamp).order_by('-timestamp')
                  .values_list('above_threshold', flat=True)[:ALERT_SECONDS])
    details['consecutive_above'] = next((i for i, above in enumerate(recent) if not above), len(recent))
    return details


@login_required(login_url='login')
def live_scores(request):
    """Live scores of the last N minutes (default 10, max 1440), oldest first."""
    equipment_id = request.GET.get('equipment_id', LIVE_EQUIPMENT_ID)
    try:
        minutes = int(request.GET.get('minutes', 10))
    except ValueError:
        return JsonResponse({'status': 'error', 'error': 'minutes must be an integer'}, status=400)
    minutes = max(1, min(minutes, LIVE_SCORES_MAX_MINUTES))

    rows = (AnomalyScore.objects.filter(mode='live', equipment_id=equipment_id,
                                        timestamp__gte=timezone.now() - timedelta(minutes=minutes))
            .order_by('timestamp'))
    scores = [_score_json(r) for r in rows]
    return JsonResponse({
        'equipment_id': equipment_id,
        'mode': 'live',
        'minutes': minutes,
        'count': len(scores),
        'scores': scores,
    })


@login_required(login_url='login')
def alerts(request):
    """Alert episodes, newest first. ?mode=live (default), replay or all; optional equipment_id."""
    mode = request.GET.get('mode', 'live')
    if mode not in ('live', 'replay', 'all'):
        return JsonResponse({'status': 'error', 'error': 'mode must be live, replay or all'}, status=400)
    rows = AlertEpisode.objects.all()
    if mode != 'all':
        rows = rows.filter(mode=mode)
    if request.GET.get('equipment_id'):
        rows = rows.filter(equipment_id=request.GET['equipment_id'])
    episodes = [_episode_json(r) for r in rows.order_by('-started_at')[:500]]
    return JsonResponse({'mode': mode, 'count': len(episodes), 'episodes': episodes})


@login_required(login_url='login')
def replay_readings(request, label):
    """Recorded readings of a replayed session (its _warmup rows and its main rows), oldest first."""
    labels = [f'{label}_warmup', label]
    if not AnomalyScore.objects.filter(mode='replay', run_label__in=labels).exists():
        return JsonResponse({'status': 'error', 'error': f'no replay stored for {label!r}'}, status=404)
    rows = (SensorData.objects.filter(source='pi', run_label__in=labels).order_by('timestamp')
            .values_list('timestamp', 'run_label', 'vibration_rms', 'vibration_peak', 'current',
                         'bus_voltage', 'temperature'))
    data = {key: [] for key in ('timestamps', 'run_label', 'vibration_rms', 'vibration_peak', 'current',
                                'bus_voltage', 'temperature')}
    for ts, run_label, rms, peak, current, bus_v, temp in rows:
        data['timestamps'].append(ts.isoformat())
        data['run_label'].append(run_label)
        data['vibration_rms'].append(rms)
        data['vibration_peak'].append(peak)
        data['current'].append(current)
        data['bus_voltage'].append(bus_v)
        data['temperature'].append(temp)
    return JsonResponse({'label': label, 'mode': 'replay', 'count': len(data['timestamps']), 'data': data})


@login_required(login_url='login')
def replay_detail(request, label):
    """Scores, threshold and alert periods of one replayed session (mode replay)."""
    labels = [f'{label}_warmup', label]
    rows = list(AnomalyScore.objects.filter(mode='replay', run_label__in=labels).order_by('timestamp'))
    if not rows:
        return JsonResponse({'status': 'error', 'error': f'no replay stored for {label!r}'}, status=404)
    episodes = AlertEpisode.objects.filter(mode='replay', run_label__in=labels).order_by('started_at')
    return JsonResponse({
        'label': label,
        'mode': 'replay',
        'equipment_id': rows[0].equipment_id,
        'threshold': rows[0].threshold,
        'count': len(rows),
        'scored_seconds': sum(1 for r in rows if r.score is not None),
        'scores': [_score_json(r) for r in rows],
        'alerts': [_episode_json(e) for e in episodes],
    })
