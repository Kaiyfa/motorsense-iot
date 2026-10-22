"""
Sensors, Alerts, Maintenance, Evaluation and Setup tabs.

Every number shown comes from stored rows (SensorData, AnomalyScore,
AlertEpisode, MaintenanceEntry) or from the committed result files
(results/metrics.json, results/negative_findings.json, and the per-session
score files the evaluation wrote to results/scores/). Nothing is invented and
no cause is named.
"""
import csv
import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from dashboard import calculations as calc
from dashboard import catalog
from dashboard import formats
from dashboard.forms import InspectionIntervalForm, MaintenanceEntryForm
from dashboard.ml import evaluation as ev
from dashboard.ml.constants import (
    ALERT_SECONDS, IDLE_CURRENT_A, MAX_GAP_SECONDS, RAW_RETENTION_DAYS, SEQUENCE_LENGTH, THRESHOLD_PERCENTILE,
    WARMUP_SECONDS,
)
from dashboard.models import (
    AlertEpisode, AnomalyScore, Equipment, InspectionInterval, MaintenanceEntry, SensorData,
)
from dashboard.views import (
    LIVE_EQUIPMENT_ID, LIVE_MAX_AGE_SECONDS, SENSOR_TILES, _iso, _model_metadata, _score_json, _tabs,
)

RESULTS_DIR = Path(settings.BASE_DIR) / 'results'
SENSOR_RANGES = {5: '5 min', 30: '30 min', 120: '2 h', 1440: '24 h'}
ALERT_RANGES = {1: '24 h', 7: '7 days', 30: '30 days'}
CHART_POINTS = 1200
DETAIL_SECONDS = 120
SENSOR_FIELDS = ['vibration_rms', 'vibration_peak', 'current', 'bus_voltage', 'temperature']
CSV_COLUMNS = [
    ('timestamp', 'timestamp_utc'),
    ('run_label', 'run_label'),
    ('vibration_rms', 'vibration_rms_g'),
    ('vibration_peak', 'vibration_peak_g'),
    ('current', 'current_a'),
    ('bus_voltage', 'pack_voltage_v'),
    ('temperature', 'temperature_c'),
]


# --------------------------------------------------------------------------- mode helpers

def _replay_label(request):
    """The replayed session asked for in ?mode=replay&session=..., if it is a known session."""
    if request.GET.get('mode') != 'replay':
        return None
    label = request.GET.get('session')
    return label if label in {s['label'] for s in catalog.REPLAY_SESSIONS} else None


def _page(request, active, extra, mode=None, replay_label=None):
    context = {
        'mode': mode,
        'active_tab': active,
        'tabs': _tabs(active, mode or 'live', replay_label),
        'replay_label': replay_label,
    }
    context.update(extra)
    return context


# --------------------------------------------------------------------------- sensors

def _sensor_rows(equipment_id, start=None, end=None, labels=None):
    rows = SensorData.objects.filter(equipment_id=equipment_id, source='pi')
    if labels is not None:
        rows = rows.filter(run_label__in=labels)
    if start is not None:
        rows = rows.filter(timestamp__gte=start)
    if end is not None:
        rows = rows.filter(timestamp__lte=end)
    return rows.order_by('timestamp')


def _sensor_query(request):
    """
    Resolve the rows shown: Live (last N minutes) or Replay (a recorded session up to
    the playhead position). Returns (queryset, info) or raises Http404 / ValueError.
    """
    equipment_id = request.GET.get('equipment_id', LIVE_EQUIPMENT_ID)
    label = _replay_label(request)
    if label:
        labels = [f'{label}_warmup', label]
        rows = _sensor_rows(equipment_id, labels=labels)
        stamps = list(rows.values_list('timestamp', flat=True))
        if not stamps:
            raise Http404('no stored rows for this session')
        try:
            pos = int(request.GET['pos'])
        except (KeyError, ValueError):
            pos = len(stamps) - 1
        pos = max(0, min(pos, len(stamps) - 1))
        until = stamps[pos]
        return rows.filter(timestamp__lte=until), {
            'mode': 'replay', 'session': label, 'pos': pos, 'range_start': stamps[0],
            'range_end': until, 'last_reading': until, 'label': f'{label} up to second {pos + 1} of {len(stamps)}',
        }
    try:
        minutes = int(request.GET.get('minutes', 30))
    except ValueError:
        raise ValueError('minutes must be an integer')
    if minutes not in SENSOR_RANGES:
        raise ValueError(f'minutes must be one of {sorted(SENSOR_RANGES)}')
    end = timezone.now()
    start = end - timedelta(minutes=minutes)
    last = (SensorData.objects.filter(equipment_id=equipment_id, source='pi')
            .aggregate(last=Max('timestamp'))['last'])
    return _sensor_rows(equipment_id, start, end), {
        'mode': 'live', 'minutes': minutes, 'range_start': start, 'range_end': end,
        'last_reading': last, 'label': f'last {SENSOR_RANGES[minutes]}',
    }


@login_required(login_url='login')
def sensors_page(request):
    label = _replay_label(request)
    mode = 'replay' if label else 'live'
    return render(request, 'dashboard/sensors.html', _page(request, 'sensors', {
        'tiles': SENSOR_TILES,
        'ranges': SENSOR_RANGES,
        'max_gap': int(MAX_GAP_SECONDS),
        'chart_points': CHART_POINTS,
        'config': {
            'mode': mode, 'session': label, 'pos': request.GET.get('pos'),
            'equipmentId': LIVE_EQUIPMENT_ID, 'liveMaxAgeSeconds': LIVE_MAX_AGE_SECONDS,
            'tiles': [{'key': t['key'], 'name': t['name'], 'unit': t['unit'], 'digits': t['digits']}
                      for t in SENSOR_TILES],
            'urls': {'data': reverse('dashboard:sensor_data'), 'csv': reverse('dashboard:sensor_csv')},
        },
    }, mode=mode, replay_label=label))


@login_required(login_url='login')
def sensor_data(request):
    """Series (reduced for drawing), exact statistics and data quality for the rows shown."""
    try:
        rows, info = _sensor_query(request)
    except ValueError as e:
        return JsonResponse({'status': 'error', 'error': str(e)}, status=400)
    values = list(rows.values_list('timestamp', *SENSOR_FIELDS))
    times = [v[0] for v in values]
    series, stats = {}, {}
    for i, field in enumerate(SENSOR_FIELDS, start=1):
        column = [v[i] for v in values]
        present = [x for x in column if x is not None]
        stats[field] = {
            'n': len(present),
            'min': min(present) if present else None,
            'mean': sum(present) / len(present) if present else None,
            'max': max(present) if present else None,
        }
        t, v = calc.downsample(times, column, CHART_POINTS)
        series[field] = {'t': [x.isoformat() for x in t], 'v': v}
    quality = calc.data_quality(times, info['range_start'], info['range_end'], info['last_reading'])
    if info['mode'] == 'replay':
        quality['seconds_since_last_reading'] = None   # a recording has no "now"
    return JsonResponse({
        'mode': info['mode'], 'label': info['label'], 'session': info.get('session'), 'pos': info.get('pos'),
        'range_start': info['range_start'].isoformat(), 'range_end': info['range_end'].isoformat(),
        'rows': len(values), 'reduced_for_drawing': any(len(s['t']) < len(values) for s in series.values()),
        'series': series, 'stats': stats, 'quality': quality,
        'last_reading': _iso(info['last_reading']),
    })


@login_required(login_url='login')
def sensor_csv(request):
    """Exactly the stored rows shown, with a header row that carries the units."""
    try:
        rows, info = _sensor_query(request)
    except ValueError as e:
        return HttpResponse(str(e), status=400, content_type='text/plain')
    name = (f"motorsense_{info['session']}_to_second_{info['pos'] + 1}.csv" if info['mode'] == 'replay'
            else f"motorsense_EQ-001_last_{info['minutes']}_min_{info['range_end']:%Y%m%dT%H%M%SZ}.csv")
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{name}"'
    writer = csv.writer(response)
    writer.writerow([title for _, title in CSV_COLUMNS])
    for row in rows.values_list(*[field for field, _ in CSV_COLUMNS]):
        writer.writerow([row[0].isoformat(), *row[1:]])
    return response


# --------------------------------------------------------------------------- alerts

def _episode_deviations(episode, baseline, after=False):
    """
    The "What changed" calculation for the 60 s up to and including the alert start, or
    (after=True) for the first 60 s of the alert: the 60 s after the start, (start, start + 60 s].
    """
    end = episode.started_at + timedelta(seconds=calc.DEVIATION_WINDOW_SECONDS if after else 0)
    readings = list(SensorData.objects.filter(
        equipment_id=episode.equipment_id, source='pi',
        timestamp__gt=end - timedelta(seconds=calc.DEVIATION_WINDOW_SECONDS),
        timestamp__lte=end,
    ).values('timestamp', 'vibration_rms', 'vibration_peak', 'current'))
    return calc.window_deviations(readings, baseline, end)


def _session_of(run_label):
    label = run_label[:-len('_warmup')] if run_label.endswith('_warmup') else run_label
    return label, catalog.session_name(label)


def _episode_row(episode, baseline, now):
    devs = _episode_deviations(episode, baseline)
    largest = calc.largest_deviation(devs)
    end = episode.ended_at or now
    label, name = _session_of(episode.run_label)
    return {
        'id': episode.id,
        'mode': episode.mode,
        'started_at': _iso(episode.started_at),
        'ended_at': _iso(episode.ended_at),
        'duration_seconds': round((end - episode.started_at).total_seconds(), 1),
        'open': episode.ended_at is None,
        'open_at_end_of_recording': episode.open_at_end_of_recording,
        'peak_score': episode.peak_score,
        'run_label': episode.run_label,
        'session': label if episode.mode == 'replay' else None,
        'session_name': name if episode.mode == 'replay' else None,
        'largest_deviation': largest and {
            'feature': largest['feature'], 'name': largest['name'], 'unit': largest['unit'],
            'z': largest['z'], 'mean': largest['mean'], 'latest': largest['latest'],
            'baseline_mean': largest['baseline_mean'], 'n': largest['n'],
        },
    }


@login_required(login_url='login')
def alerts_page(request):
    label = _replay_label(request)
    mode = 'replay' if label else 'live'
    return render(request, 'dashboard/alerts.html', _page(request, 'alerts', {
        'ranges': ALERT_RANGES,
        'alert_seconds': ALERT_SECONDS,
        'config': {
            'mode': mode, 'filter': request.GET.get('filter') or mode, 'open': request.GET.get('open'),
            'urls': {'table': reverse('dashboard:alert_table'), 'detail': reverse('dashboard:alert_detail', args=[0])},
            'deviationWindowSeconds': calc.DEVIATION_WINDOW_SECONDS, 'detailSeconds': DETAIL_SECONDS,
        },
    }, mode=mode, replay_label=label))


@login_required(login_url='login')
def alert_table(request):
    """Alert episodes for the table. ?mode=live|replay|all, ?days=1|7|30 (live: started within; replay: all)."""
    mode = request.GET.get('mode', 'live')
    if mode not in ('live', 'replay', 'all'):
        return JsonResponse({'status': 'error', 'error': 'mode must be live, replay or all'}, status=400)
    try:
        days = int(request.GET.get('days', 7))
    except ValueError:
        return JsonResponse({'status': 'error', 'error': 'days must be an integer'}, status=400)
    if days not in ALERT_RANGES:
        return JsonResponse({'status': 'error', 'error': f'days must be one of {sorted(ALERT_RANGES)}'}, status=400)
    now = timezone.now()
    episodes = AlertEpisode.objects.all().order_by('-started_at')
    if mode != 'all':
        episodes = episodes.filter(mode=mode)
    # The range applies to live alerts; replayed alerts keep their recorded dates.
    live_since = now - timedelta(days=days)
    episodes = [e for e in episodes[:500] if e.mode == 'replay' or e.started_at >= live_since]
    scaler, _ = _model_metadata()
    return JsonResponse({
        'mode': mode, 'days': days, 'range_label': ALERT_RANGES[days], 'now': now.isoformat(),
        'count': len(episodes),
        'episodes': [_episode_row(e, scaler, now) for e in episodes],
    })


@login_required(login_url='login')
def alert_detail(request, episode_id):
    """
    Scores from 2 minutes before to 2 minutes after the start, and the three deviations in
    the 60 s before the start and in the first 60 s of the alert.
    """
    episode = get_object_or_404(AlertEpisode, pk=episode_id)
    start = episode.started_at - timedelta(seconds=DETAIL_SECONDS)
    end = episode.started_at + timedelta(seconds=DETAIL_SECONDS)
    scores = AnomalyScore.objects.filter(mode=episode.mode, equipment_id=episode.equipment_id,
                                         timestamp__gte=start, timestamp__lte=end).order_by('timestamp')
    scaler, threshold = _model_metadata()
    devs = _episode_deviations(episode, scaler)
    devs_after = _episode_deviations(episode, scaler, after=True)
    rows = [_score_json(r) for r in scores]
    keys = ('feature', 'name', 'unit', 'digits', 'n', 'mean', 'latest', 'z', 'baseline_mean')
    return JsonResponse({
        'episode': _episode_row(episode, scaler, timezone.now()),
        'window_start': start.isoformat(), 'window_end': end.isoformat(),
        'threshold': rows[0]['threshold'] if rows else threshold,
        'scores': rows,
        'deviations': [{k: d[k] for k in keys} for d in devs],
        'deviations_after': [{k: d[k] for k in keys} for d in devs_after],
        'deviation_seconds': calc.DEVIATION_WINDOW_SECONDS,
    })


# --------------------------------------------------------------------------- maintenance

def _equipment():
    return Equipment.objects.filter(equipment_id=LIVE_EQUIPMENT_ID).first()


@login_required(login_url='login')
def maintenance_page(request):
    equipment = _equipment()
    entries = MaintenanceEntry.objects.filter(equipment=equipment).select_related('performed_by') if equipment else []
    interval = InspectionInterval.objects.filter(equipment=equipment).first() if equipment else None
    last_inspection = (MaintenanceEntry.objects.filter(equipment=equipment, kind='inspection')
                       .aggregate(last=Max('performed_at'))['last'] if equipment else None)
    live_alerts = list(AlertEpisode.objects.filter(mode='live', equipment=equipment).order_by('-started_at')) \
        if equipment else []
    inspections = list(MaintenanceEntry.objects.filter(equipment=equipment, kind='inspection')
                       .values_list('performed_at', flat=True)) if equipment else []
    return render(request, 'dashboard/maintenance.html', _page(request, 'maintenance', {
        'equipment': equipment,
        'entries': entries,
        'interval': interval,
        'last_inspection': last_inspection,
        'next_due': calc.next_inspection_due(last_inspection, interval.days if interval else None),
        'now': timezone.now(),
        'unchecked_alerts': calc.alerts_without_inspection(live_alerts, inspections),
        'live_alert_count': len(live_alerts),
        'entry_form': MaintenanceEntryForm(initial={
            'performed_at': formats.format_datetime(timezone.now(), formats.DATETIME_INPUT_FORMAT)}),
        'input_example': formats.format_datetime(timezone.now(), formats.DATETIME_INPUT_FORMAT),
        'interval_form': InspectionIntervalForm(initial={'days': interval.days if interval else None}),
    }))


@login_required(login_url='login')
@require_POST
def maintenance_add(request):
    equipment = _equipment()
    if equipment is None:
        messages.error(request, 'EQ-001 does not exist yet: it is created by the first reading from the Pi.')
        return redirect('dashboard:maintenance')
    form = MaintenanceEntryForm(request.POST)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.equipment = equipment
        entry.performed_by = request.user
        entry.save()
        messages.success(request, f'Logged {entry.get_kind_display().lower()} at '
                                  f'{formats.format_datetime(entry.performed_at)}.')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{form.fields[field].label if field in form.fields else 'Entry'}: {error}")
    return redirect('dashboard:maintenance')


@login_required(login_url='login')
@require_POST
def maintenance_delete(request, entry_id):
    entry = get_object_or_404(MaintenanceEntry, pk=entry_id)
    if entry.performed_by_id != request.user.id:
        return HttpResponseForbidden('You can only delete your own entries.')
    entry.delete()
    messages.success(request, 'Entry deleted.')
    return redirect('dashboard:maintenance')


@login_required(login_url='login')
@require_POST
def maintenance_interval(request):
    equipment = _equipment()
    if equipment is None:
        messages.error(request, 'EQ-001 does not exist yet: it is created by the first reading from the Pi.')
        return redirect('dashboard:maintenance')
    form = InspectionIntervalForm(request.POST)
    if form.is_valid():
        InspectionInterval.objects.update_or_create(
            equipment=equipment, defaults={'days': form.cleaned_data['days'], 'set_by': request.user})
        messages.success(request, f"Inspection interval set to {form.cleaned_data['days']} days.")
    else:
        for error in form.errors.get('days', []):
            messages.error(request, f'Inspection interval: {error}')
    return redirect('dashboard:maintenance')


# --------------------------------------------------------------------------- evaluation

def _read_json(name):
    path = RESULTS_DIR / name
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def _small_multiples(metrics):
    """Seed-0 three-feature scores of the validation and test sessions, from results/scores/."""
    seed0 = metrics['methods']['ae_all']['seeds']['0']
    threshold = seed0['threshold']
    out = []
    for label in ('r5_normal_04_redo', 'r5_normal_05', 'r5_fault_open_01', 'r5_fault_open_02', 'r5_fault_open_03'):
        path = RESULTS_DIR / 'scores' / f'{label}.csv'
        item = {'label': label, 'name': catalog.session_name(label), 'available': path.exists()}
        if path.exists():
            with path.open(newline='') as f:
                scores = [float(r['ae_all_seed0']) if r['ae_all_seed0'] else None for r in csv.DictReader(f)]
            geometry = calc.score_path(scores, threshold, 300, 90)
            alert_on, _ = ev.alert_state(ev.above_threshold([float('nan') if s is None else s for s in scores],
                                                            threshold))
            spans, start = [], None
            for i, on in enumerate(list(alert_on) + [False]):
                if on and start is None:
                    start = i
                elif not on and start is not None:
                    spans.append((round(start / max(len(scores) - 1, 1) * 300, 2),
                                  round((i - start) / max(len(scores) - 1, 1) * 300, 2)))
                    start = None
            session = seed0['sessions'].get(label)
            item.update({
                'geometry': geometry, 'alert_spans': spans, 'scored': sum(1 for s in scores if s is not None),
                'episodes': session['episodes'] if session else seed0['validation_episodes'],
                'role': 'validation' if label.endswith('redo') else ('test, fault' if 'fault' in label else 'test, normal'),
            })
        out.append(item)
    return threshold, out


@login_required(login_url='login')
def evaluation_page(request):
    metrics = _read_json('metrics.json')
    findings = _read_json('negative_findings.json')
    context = {'metrics_available': metrics is not None, 'findings_available': findings is not None,
               'what_this_shows': calc.what_this_shows(metrics, findings), 'warmup_seconds': int(WARMUP_SECONDS)}
    if metrics:
        threshold, multiples = _small_multiples(metrics)
        env = metrics['environment']
        context.update({
            'tables': [
                {'title': 'Per second', 'note': 'a second counts as detected when its score is above the threshold',
                 'columns': [t for _, t, _ in calc.PER_SECOND_COLUMNS],
                 'rows': calc.method_rows(metrics, calc.PER_SECOND_COLUMNS)},
                {'title': 'Per session', 'note': 'a session counts as detected when at least one alert fired',
                 'columns': [t for _, t, _ in calc.PER_SESSION_COLUMNS],
                 'rows': calc.method_rows(metrics, calc.PER_SESSION_COLUMNS)},
            ],
            'statements': calc.comparison_statements(metrics),
            'settings': metrics['settings'],
            'seeds': metrics['settings']['seeds'],
            'threshold': threshold,
            'multiples': multiples,
            'environment': env,
            'git': metrics['git'],
            'created_at': parse_datetime(metrics['created_at']),
            'test_seconds': metrics['settings']['sessions']['r5_normal_05']['scored_seconds'],
        })
        for table in context['tables']:
            table['same_for_all_seeds'] = any(cell['same_for_all_seeds'] for row in table['rows']
                                              for cell in row['cells'])
    if findings:
        context['findings'] = [{
            **c,
            'rows': ([{'test': ch['test'], 'reference': ch['reference'], 'is_reference': False,
                       'cells': calc.finding_cells(ch)} for ch in c['changes']]
                     + [{'test': ch['test'], 'reference': ch['reference'], 'is_reference': True,
                         'cells': calc.finding_cells(ch)}
                        for ch in c['reference_changes']]),
        } for c in findings['comparisons']]
        context['findings_meta'] = {k: findings.get(k) for k in ('script', 'plateau_rule', 'std', 'percent',
                                                                  'short_runs')}
    return render(request, 'dashboard/evaluation.html', _page(request, 'evaluation', context))


# --------------------------------------------------------------------------- setup

@login_required(login_url='login')
def setup_page(request):
    return render(request, 'dashboard/setup.html', _page(request, 'setup', {
        'warmup_seconds': int(WARMUP_SECONDS), 'idle_current': IDLE_CURRENT_A, 'sequence_length': SEQUENCE_LENGTH,
        'alert_seconds': ALERT_SECONDS, 'max_gap': int(MAX_GAP_SECONDS), 'percentile': THRESHOLD_PERCENTILE,
        'offline_after': LIVE_MAX_AGE_SECONDS, 'retention_days': RAW_RETENTION_DAYS,
        'photo_path': 'docs/media/testbed_photo.jpg',
    }))
