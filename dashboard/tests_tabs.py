"""
Tests for the Sensors, Alerts, Maintenance, Evaluation and Setup tabs and the
calculations behind them (dashboard/calculations.py, analysis/negative_findings.py).
"""
import csv
import importlib.util
import io
import json
import math
import unittest
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from dashboard import calculations as calc
from dashboard.models import (
    AlertEpisode, AnomalyScore, Equipment, InspectionInterval, MaintenanceEntry, SensorData,
)

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 22, 12, 0, 0, tzinfo=dt_timezone.utc)
BASELINE = {'vib_rms_g': {'mean': 0.1, 'std': 0.01}, 'vib_peak_g': {'mean': 0.3, 'std': 0.05},
            'current': {'mean': 0.8, 'std': 0.005}}


def reading(seconds, rms=0.1, peak=0.3, current=0.8):
    return {'timestamp': T0 + timedelta(seconds=seconds), 'vibration_rms': rms, 'vibration_peak': peak,
            'current': current}


# --------------------------------------------------------------------------- calculations

class DeviationTests(unittest.TestCase):
    def test_window_is_the_60_seconds_up_to_and_including_the_end(self):
        rows = [reading(-61, current=0.0), reading(-60, current=0.0)] + \
               [reading(-i, current=0.79) for i in range(0, 60)]
        devs = {d['feature']: d for d in calc.window_deviations(rows, BASELINE, T0)}
        self.assertEqual(devs['current']['n'], 60)               # -60 s and earlier are outside
        self.assertAlmostEqual(devs['current']['z'], -2.0)
        self.assertAlmostEqual(devs['current']['latest'], 0.79)
        self.assertAlmostEqual(devs['vib_rms_g']['z'], 0.0)

    def test_largest_deviation_by_absolute_value(self):
        devs = calc.window_deviations([reading(0, rms=0.13, current=0.75)], BASELINE, T0)
        largest = calc.largest_deviation(devs)
        self.assertEqual(largest['feature'], 'current')          # -10 sigma beats +3 sigma
        self.assertAlmostEqual(largest['z'], -10.0)

    def test_no_readings_or_no_baseline(self):
        devs = calc.window_deviations([], BASELINE, T0)
        self.assertTrue(all(d['z'] is None and d['n'] == 0 for d in devs))
        self.assertIsNone(calc.largest_deviation(devs))
        devs = calc.window_deviations([reading(0)], None, T0)
        self.assertTrue(all(d['z'] is None for d in devs))


class SensorCalculationTests(unittest.TestCase):
    def test_data_quality_counts_gaps_above_the_limit(self):
        times = [T0 + timedelta(seconds=s) for s in [0, 1, 2, 8, 9, 14, 20]]   # gaps 6 and 6 (>5), 5 (not)
        q = calc.data_quality(times, T0, T0 + timedelta(minutes=1), times[-1])
        self.assertEqual(q['readings'], 7)
        self.assertEqual(q['readings_per_minute'], 7.0)
        self.assertEqual(q['gaps_over_limit'], 2)
        self.assertEqual(q['longest_gap_seconds'], 6.0)
        self.assertEqual(q['seconds_since_last_reading'], 40.0)
        empty = calc.data_quality([], T0, T0 + timedelta(minutes=5), None)
        self.assertEqual((empty['readings'], empty['gaps_over_limit'], empty['seconds_since_last_reading']), (0, 0, None))

    def test_downsample_keeps_extremes_and_short_series(self):
        times = list(range(10))
        self.assertEqual(calc.downsample(times, list(range(10)), 20), (times, list(range(10))))
        values = [0.0] * 1000
        values[500] = 9.0
        values[700] = -3.0
        t, v = calc.downsample(list(range(1000)), values, 100)
        self.assertLessEqual(len(v), 110)
        self.assertIn(9.0, v)
        self.assertIn(-3.0, v)
        self.assertEqual(t, sorted(t))


class MaintenanceCalculationTests(unittest.TestCase):
    def test_next_inspection_due(self):
        self.assertEqual(calc.next_inspection_due(T0, 30), T0 + timedelta(days=30))
        self.assertIsNone(calc.next_inspection_due(None, 30))
        self.assertIsNone(calc.next_inspection_due(T0, None))

    def test_alerts_without_inspection_afterwards(self):
        alerts = [{'id': 1, 'started_at': T0}, {'id': 2, 'started_at': T0 + timedelta(hours=2)}]
        self.assertEqual([a['id'] for a in calc.alerts_without_inspection(alerts, [])], [1, 2])
        self.assertEqual([a['id'] for a in calc.alerts_without_inspection(alerts, [T0 + timedelta(hours=1)])], [2])
        self.assertEqual(calc.alerts_without_inspection(alerts, [T0 + timedelta(hours=2)]), [])


class EvaluationCalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metrics = json.loads((REPO / 'results' / 'metrics.json').read_text())

    def test_method_rows_come_from_metrics(self):
        rows = {r['key']: r for r in calc.method_rows(self.metrics)}
        self.assertEqual(set(rows), {'ae_all', 'ae_vibration', 'ae_current', 'z_current', 'z_vib_rms'})
        fp_col = [title for _, title, _ in calc.SUMMARY_COLUMNS].index('FP')
        self.assertEqual(calc.SUMMARY_COLUMNS, calc.PER_SECOND_COLUMNS + calc.PER_SESSION_COLUMNS)
        z_fp = self.metrics['methods']['z_current']['summary']['per_second.fp']['mean']
        self.assertEqual(rows['z_current']['cells'][fp_col]['value'], f'{z_fp:g}')
        self.assertTrue(rows['ae_all']['seeded'])
        self.assertFalse(rows['z_current']['seeded'])

    def test_statements_follow_the_numbers(self):
        text = ' '.join(calc.comparison_statements(self.metrics))
        self.assertIn('performs as well as the autoencoder', text)
        self.assertIn('only partly', text)
        self.assertNotIn('ccuracy', text)
        broken = json.loads(json.dumps(self.metrics))
        broken['methods']['z_current']['summary']['fault_sessions_alerted']['mean'] = 2.0
        self.assertNotIn('performs as well', ' '.join(calc.comparison_statements(broken)))

    def test_false_positive_sentence(self):
        z_fp = self.metrics['methods']['z_current']['summary']['per_second.fp']['mean']
        ae_fp = self.metrics['methods']['ae_all']['summary']['per_second.fp']['mean']
        text = ' '.join(calc.comparison_statements(self.metrics))
        self.assertIn(f'({abs(z_fp - ae_fp):g} seconds in one session; not a significant difference)', text)

    def test_same_for_all_seeds_is_a_flag_not_a_cell_text(self):
        rows = {r['key']: r for r in calc.method_rows(self.metrics)}
        recall = [title for _, title, _ in calc.SUMMARY_COLUMNS].index('Recall')
        cell = rows['ae_all']['cells'][recall]
        self.assertEqual(cell['spread'], '')
        self.assertTrue(cell['same_for_all_seeds'])
        self.assertFalse(any(c['same_for_all_seeds'] for c in rows['z_current']['cells']))   # not seeded
        vib = rows['ae_vibration']['cells'][recall]
        self.assertFalse(vib['same_for_all_seeds'])
        self.assertTrue(vib['spread'].startswith('±'))

    def test_what_this_shows_follows_the_numbers(self):
        findings = json.loads((REPO / 'results' / 'negative_findings.json').read_text())
        current, vibration, others = calc.what_this_shows(self.metrics, findings)
        self.assertTrue(current.startswith('The current channel carries this fault, and a fixed current threshold '
                                           'does equally well'))
        self.assertTrue(vibration.startswith('Vibration alone detects it only partly and slowly'))
        vib_delay = self.metrics['methods']['ae_vibration']['summary']['mean_delay_alerted_faults']
        self.assertIn(f"mean delay of {vib_delay['min']:g} to {vib_delay['max']:g} s", vibration)
        self.assertTrue(others.startswith('Imbalance, a loosened mount, friction and frequency bands were not '
                                          'detectable on this rig'))
        # largest vibration or band change outside the drift and open-lead comparisons, and the drift itself
        faults = [ch for c in findings['comparisons']
                  if c['title'] not in (calc.DRIFT_TITLE, calc.DETECTED_FAULT_TITLE) for ch in c['changes']]
        largest = max(abs(v) for ch in faults for k, v in ch['percent'].items() if k != 'current_ma' and v is not None)
        self.assertIn(f'more than {largest:.1f} %', others)
        self.assertIn('58.9 % shift', others)

        broken = json.loads(json.dumps(self.metrics))
        broken['methods']['ae_vibration']['summary']['fault_sessions_alerted']['min'] = 3.0
        broken['methods']['z_current']['summary']['normal_test_episodes']['mean'] = 1.0
        current, vibration, _ = calc.what_this_shows(broken, findings)
        self.assertNotIn('equally well', current)
        self.assertNotIn('only partly', vibration)
        shifted = json.loads(json.dumps(findings))
        shifted['comparisons'][0]['changes'][1]['percent'] = {'vib_rms_g': 1.0, 'vib_peak_g': 1.0, 'current_ma': 0.0}
        shifted['comparisons'][0]['changes'][0]['percent'] = {'vib_rms_g': 1.0, 'vib_peak_g': 1.0, 'current_ma': 0.0}
        self.assertNotIn('not detectable', calc.what_this_shows(None, shifted)[0])
        self.assertEqual(calc.what_this_shows(None, None), [])

    def test_score_path(self):
        geometry = calc.score_path([None, 1.0, 10.0, None, 100.0], 2.95, 300, 90)
        self.assertEqual((geometry['lo'], geometry['hi']), (1, 1000))
        self.assertTrue(geometry['path'].startswith('M75.0,'))
        self.assertEqual(geometry['path'].count('M'), 2)          # the gap breaks the line
        self.assertIsNone(calc.score_path([None, None], 1.0, 300, 90))


class NegativeFindingsJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('nf', REPO / 'analysis' / 'negative_findings.py')
        cls.nf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.nf)

    def test_pct_value(self):
        self.assertEqual(self.nf.pct_value(110.0, 100.0), 10.0)
        self.assertEqual(self.nf.pct_value(0.1346, 0.1482), -9.2)
        self.assertIsNone(self.nf.pct_value(1.0, 0.0))

    def test_comparison_record_matches_the_printed_numbers(self):
        def rows(n, rms, cur):
            return [{'timestamp_utc': f'2026-01-01T00:{i // 60:02d}:{i % 60:02d}', 'vib_rms_g': rms,
                     'vib_peak_g': 0.3, 'current_ma': cur, **{b: None for b in self.nf.BANDS}} for i in range(n)]
        sessions = {'ref': rows(200, 0.10, 800.0), 'test': rows(200, 0.11, 800.0)}
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            record = self.nf.run_comparison('T', ['ref'], ['test', 'missing'], None, sessions)
        self.assertIn('vib_rms_g +10.0%', out.getvalue())
        self.assertEqual(record['missing'], ['missing'])
        self.assertEqual(record['changes'][0]['percent']['vib_rms_g'], 10.0)
        self.assertEqual([s['windows'] for s in record['sessions']], [90, 90])

    def test_runs_shorter_than_the_warm_up_report_only_current(self):
        from dashboard.ml.constants import WARMUP_SECONDS
        self.assertEqual(self.nf.WARMUP_WINDOWS, WARMUP_SECONDS)

        def rows(n, rms, cur):
            return [{'timestamp_utc': f'2026-01-01T00:{i // 60:02d}:{i % 60:02d}', 'vib_rms_g': rms,
                     'vib_peak_g': 0.3, 'current_ma': cur, **{b: 0.05 for b in self.nf.BANDS}} for i in range(n)]
        sessions = {'ref': rows(240, 0.10, 800.0), 'short': rows(60, 0.08, 816.0), 'long': rows(180, 0.11, 800.0)}
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            record = self.nf.run_comparison('T', ['ref'], ['short', 'long'], None, sessions)
        short, long_ = record['changes']
        self.assertEqual(short['percent'], {'vib_rms_g': None, 'vib_peak_g': None, 'current_ma': 2.0})
        self.assertEqual(short['not_compared'], ['vib_rms_g', 'vib_peak_g'] + self.nf.BANDS)
        self.assertEqual(short['not_compared_reason'], 'run shorter than the warm-up')
        self.assertEqual(short['shorter_than_warmup'], ['short'])
        self.assertNotIn('not_compared', long_)                      # 180 windows: not shorter than the warm-up
        self.assertEqual(long_['percent']['vib_rms_g'], 10.0)
        by_label = {s['label']: s for s in record['sessions']}
        self.assertIsNone(by_label['short']['vib_rms_g']['mean'])
        self.assertIsNone(by_label['short']['bands'])
        self.assertEqual(by_label['short']['current_ma']['mean'], 816.0)
        self.assertTrue(by_label['short']['shorter_than_warmup'])
        self.assertIn('short vs ref: current_ma +2.0%; vibration and bands n/a', out.getvalue())

        cells = calc.finding_cells(short)
        self.assertEqual([c['text'] for c in cells], ['n/a, run shorter than the warm-up'] * 2
                         + ['+2.0 %', 'n/a, run shorter than the warm-up'])

    def test_committed_json_leaves_out_vibration_only_for_the_short_friction_runs(self):
        data = json.loads((REPO / 'results' / 'negative_findings.json').read_text())
        short = {s['label'] for c in data['comparisons'] for s in c['sessions'] if s['shorter_than_warmup']}
        self.assertEqual(short, {'r4_tune', 'r4_tune2'})
        for c in data['comparisons']:
            for ch in c['changes']:
                if {ch['test'], ch['reference']} & short:
                    self.assertIsNone(ch['percent']['vib_rms_g'])
                    self.assertIsNotNone(ch['percent']['current_ma'])
                else:
                    self.assertNotIn('not_compared', ch)
                    self.assertIsNotNone(ch['percent']['vib_rms_g'])

    def test_finding_cells(self):
        cells = calc.finding_cells({'percent': {'vib_rms_g': 13.1, 'vib_peak_g': 11.0, 'current_ma': -14.6,
                                                'band_1_6_g': -5.3, 'band_6_20_g': -29.4, 'band_20_50_g': -6.2,
                                                'band_50_100_g': 26.6}})
        self.assertEqual([c['text'] for c in cells],
                         ['+13.1 %', '+11.0 %', '-14.6 %', '1–6 Hz -5.3 %, 6–20 Hz -29.4 %, 20–50 Hz -6.2 %, 50–100 Hz +26.6 %'])
        cells = calc.finding_cells({'percent': {'vib_rms_g': 1.0, 'vib_peak_g': 2.0, 'current_ma': 0.0}})
        self.assertEqual(cells[-1]['text'], '—')

    def test_committed_json_has_every_comparison(self):
        data = json.loads((REPO / 'results' / 'negative_findings.json').read_text())
        titles = [c['title'] for c in data['comparisons']]
        self.assertEqual(len(titles), len(self.nf.COMPARISONS))
        self.assertNotIn('/Users/', json.dumps(data))


class DateFormatTests(SimpleTestCase):
    def test_one_format_in_the_display_time_zone(self):
        from dashboard import formats
        with self.settings(TIME_ZONE='Asia/Riyadh'):
            self.assertEqual(formats.format_datetime(datetime(2026, 10, 22, 4, 23, 31, tzinfo=dt_timezone.utc)),
                             '22 Oct 2026, 07:23:31')
            self.assertEqual(formats.format_datetime(datetime(2026, 9, 5, 21, 0, 0, tzinfo=dt_timezone.utc)),
                             '6 Sep 2026, 00:00:00')
            self.assertEqual(formats.timezone_label(), 'Asia/Riyadh (UTC+3)')
        with self.settings(TIME_ZONE='Asia/Kolkata'):
            self.assertEqual(formats.timezone_label(), 'Asia/Kolkata (UTC+5:30)')
        self.assertEqual(formats.format_datetime(None), '')


# --------------------------------------------------------------------------- views

class TabTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', password='a-long-password')
        self.other = User.objects.create_user('other', password='a-long-password')
        self.client.force_login(self.user)
        self.eq = Equipment.objects.create(equipment_id='EQ-001', name='Bench rig', equipment_type='MOTOR',
                                           location='Bench', installation_date=T0.date())

    def add_readings(self, start, count, label='run', current=0.8, step=1):
        SensorData.objects.bulk_create([
            SensorData(equipment=self.eq, timestamp=start + timedelta(seconds=i * step), run_label=label,
                       temperature=25.0 + i * 0.01, current=current, vibration_rms=0.1, vibration_peak=0.3,
                       bus_voltage=7.8, source='pi')
            for i in range(count)])


class SensorViewTests(TabTestCase):
    def test_live_data_stats_quality_and_csv(self):
        now = timezone.now()
        self.add_readings(now - timedelta(seconds=100), 50)                          # 50 rows, then a gap
        self.add_readings(now - timedelta(seconds=40), 10, current=0.7)              # 10 more rows
        data = self.client.get(reverse('dashboard:sensor_data') + '?minutes=5').json()
        self.assertEqual((data['mode'], data['rows']), ('live', 60))
        self.assertEqual(data['stats']['current']['n'], 60)
        self.assertAlmostEqual(data['stats']['current']['mean'], (50 * 0.8 + 10 * 0.7) / 60)
        self.assertAlmostEqual(data['stats']['current']['min'], 0.7)
        self.assertEqual(data['quality']['gaps_over_limit'], 1)
        self.assertEqual(data['quality']['readings_per_minute'], 12.0)
        self.assertLess(data['quality']['seconds_since_last_reading'], 40)

        response = self.client.get(reverse('dashboard:sensor_csv') + '?minutes=5')
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        lines = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(lines[0], ['timestamp_utc', 'run_label', 'vibration_rms_g', 'vibration_peak_g',
                                    'current_a', 'pack_voltage_v', 'temperature_c'])
        self.assertEqual(len(lines) - 1, 60)

    def test_ranges_are_validated(self):
        self.assertEqual(self.client.get(reverse('dashboard:sensor_data') + '?minutes=7').status_code, 400)
        self.assertEqual(self.client.get(reverse('dashboard:sensor_csv') + '?minutes=x').status_code, 400)

    def test_replay_stops_at_the_playhead(self):
        self.add_readings(T0, 30, label='r5_normal_05_warmup')
        self.add_readings(T0 + timedelta(seconds=30), 30, label='r5_normal_05')
        q = '?mode=replay&session=r5_normal_05&pos=39'
        data = self.client.get(reverse('dashboard:sensor_data') + q).json()
        self.assertEqual((data['mode'], data['rows'], data['pos']), ('replay', 40, 39))
        self.assertIsNone(data['quality']['seconds_since_last_reading'])
        lines = self.client.get(reverse('dashboard:sensor_csv') + q).content.decode().strip().splitlines()
        self.assertEqual(len(lines) - 1, 40)
        whole = self.client.get(reverse('dashboard:sensor_data') + '?mode=replay&session=r5_normal_05').json()
        self.assertEqual(whole['rows'], 60)


class AlertViewTests(TabTestCase):
    def setUp(self):
        super().setUp()
        self.start = timezone.now() - timedelta(minutes=10)
        self.add_readings(self.start - timedelta(seconds=90), 90, current=0.8)
        self.add_readings(self.start, 60, current=0.7)
        self.episode = AlertEpisode.objects.create(equipment=self.eq, started_at=self.start,
                                                   ended_at=self.start + timedelta(seconds=40), peak_score=50.0,
                                                   run_label='run', mode='live')
        for i in range(-150, 150, 10):
            AnomalyScore.objects.create(equipment=self.eq, timestamp=self.start + timedelta(seconds=i),
                                        run_label='run', score=1.0, threshold=2.95, machine_state='running', mode='live')

    def test_table_has_the_columns_and_the_deviation_before_the_start(self):
        with mock.patch('dashboard.views_tabs._model_metadata', return_value=(BASELINE, 2.95)):
            data = self.client.get(reverse('dashboard:alert_table') + '?mode=live&days=1').json()
        self.assertEqual(data['count'], 1)
        e = data['episodes'][0]
        self.assertEqual((e['duration_seconds'], e['open'], e['peak_score'], e['run_label']), (40.0, False, 50.0, 'run'))
        # (start - 60 s, start]: 59 readings at 0.8 A and the start second itself at 0.7 A, as in "What changed"
        expected = ((59 * 0.8 + 0.7) / 60 - 0.8) / 0.005
        self.assertEqual(e['largest_deviation']['feature'], 'current')
        self.assertAlmostEqual(e['largest_deviation']['z'], expected)
        self.assertEqual(e['largest_deviation']['n'], 60)

    def test_filters_and_empty_state(self):
        self.assertEqual(self.client.get(reverse('dashboard:alert_table') + '?mode=replay').json()['count'], 0)
        self.assertEqual(self.client.get(reverse('dashboard:alert_table') + '?mode=bad').status_code, 400)
        self.assertEqual(self.client.get(reverse('dashboard:alert_table') + '?days=3').status_code, 400)
        old = AlertEpisode.objects.create(equipment=self.eq, started_at=timezone.now() - timedelta(days=3),
                                          peak_score=9.0, run_label='old', mode='live')
        ids = [e['id'] for e in self.client.get(reverse('dashboard:alert_table') + '?days=1').json()['episodes']]
        self.assertNotIn(old.id, ids)
        ids = [e['id'] for e in self.client.get(reverse('dashboard:alert_table') + '?days=7').json()['episodes']]
        self.assertIn(old.id, ids)

    def test_replay_rows_carry_the_session_name(self):
        AlertEpisode.objects.create(equipment=self.eq, started_at=T0, ended_at=T0 + timedelta(seconds=5),
                                    peak_score=9.0, run_label='r5_fault_open_01', mode='replay',
                                    open_at_end_of_recording=True)
        e = self.client.get(reverse('dashboard:alert_table') + '?mode=replay').json()['episodes'][0]
        self.assertEqual((e['mode'], e['session_name'], e['open_at_end_of_recording']),
                         ('replay', 'Fault: one motor disconnected, session 1', True))

    def test_detail_window_and_deviations(self):
        with mock.patch('dashboard.views_tabs._model_metadata', return_value=(BASELINE, 2.95)):
            data = self.client.get(reverse('dashboard:alert_detail', args=[self.episode.id])).json()
        times = [datetime.fromisoformat(s['timestamp']) for s in data['scores']]
        self.assertTrue(all(self.start - timedelta(seconds=120) <= t <= self.start + timedelta(seconds=120) for t in times))
        self.assertEqual(len(times), 25)                          # -120 s to +120 s, both ends included
        self.assertEqual([d['feature'] for d in data['deviations']], ['vib_rms_g', 'vib_peak_g', 'current'])
        self.assertEqual(self.client.get(reverse('dashboard:alert_detail', args=[999999])).status_code, 404)

    def test_detail_has_the_first_60_seconds_of_the_alert(self):
        with mock.patch('dashboard.views_tabs._model_metadata', return_value=(BASELINE, 2.95)):
            data = self.client.get(reverse('dashboard:alert_detail', args=[self.episode.id])).json()
        self.assertEqual(data['deviation_seconds'], 60)
        before = {d['feature']: d for d in data['deviations']}
        after = {d['feature']: d for d in data['deviations_after']}
        # (start, start + 60 s]: the readings after the start second, all at 0.7 A (start + 1 s to start + 59 s)
        self.assertEqual(after['current']['n'], 59)
        self.assertAlmostEqual(after['current']['z'], (0.7 - 0.8) / 0.005)
        self.assertAlmostEqual(before['current']['z'], ((59 * 0.8 + 0.7) / 60 - 0.8) / 0.005)
        # the same calculation as the window before the start, only shifted by 60 s
        readings = list(SensorData.objects.values('timestamp', 'vibration_rms', 'vibration_peak', 'current'))
        same = calc.window_deviations(readings, BASELINE, self.start + timedelta(seconds=60))
        self.assertEqual([d['z'] for d in same], [d['z'] for d in data['deviations_after']])


class MaintenanceViewTests(TabTestCase):
    def post(self, name, data, args=None):
        return self.client.post(reverse(name, args=args or []), data)

    def test_add_entry_and_next_inspection(self):
        when = timezone.localtime() - timedelta(days=2)
        response = self.post('dashboard:maintenance_add', {'performed_at': when.strftime('%d %b %Y, %H:%M'),
                                                            'kind': 'inspection', 'notes': 'Checked the mounts.'})
        self.assertEqual(response.status_code, 302)
        entry = MaintenanceEntry.objects.get()
        self.assertEqual((entry.performed_by, entry.kind, entry.equipment_id), (self.user, 'inspection', 'EQ-001'))
        self.post('dashboard:maintenance_interval', {'days': 14})
        self.assertEqual(InspectionInterval.objects.get().days, 14)
        html = self.client.get(reverse('dashboard:maintenance')).content.decode()
        due = timezone.localtime(entry.performed_at + timedelta(days=14))
        self.assertIn(f"{due.day} {due:%b %Y, %H:%M}:00", html)          # 22 Oct 2026, 07:23:00
        self.assertIn('Set by the operator. Not a prediction.', html)
        self.assertIn('In 1\xa0week, 4\xa0days.', html)              # 14 days after an inspection 2 days ago

    def test_performed_at_uses_the_page_date_format(self):
        form_html = self.client.get(reverse('dashboard:maintenance')).content.decode()
        now = timezone.localtime()
        self.assertIn(f'value="{now.day} {now:%b %Y, %H:}', form_html)
        self.assertNotIn('datetime-local', form_html)

    def test_kind_placeholder(self):
        html = self.client.get(reverse('dashboard:maintenance')).content.decode()
        self.assertIn('<option value="" selected>Select kind</option>', html)
        self.assertNotIn('---------', html)
        self.post('dashboard:maintenance_add', {'performed_at': '1 Oct 2026, 10:00', 'kind': ''})
        self.assertEqual(MaintenanceEntry.objects.count(), 0)
        for text, expected in [('5 Oct 2026, 07:23', (5, 7, 23, 0)), ('05 Oct 2026, 07:23:31', (5, 7, 23, 31)),
                               ('2026-10-05T07:23', (5, 7, 23, 0))]:
            MaintenanceEntry.objects.all().delete()
            self.post('dashboard:maintenance_add', {'performed_at': text, 'kind': 'repair'})
            at = timezone.localtime(MaintenanceEntry.objects.get().performed_at)
            self.assertEqual((at.day, at.hour, at.minute, at.second), expected, text)
            self.assertEqual(str(at.tzinfo), settings.TIME_ZONE)

    def test_overdue_inspection(self):
        MaintenanceEntry.objects.create(equipment=self.eq, performed_at=timezone.now() - timedelta(days=20, hours=1),
                                        performed_by=self.user, kind='inspection')
        InspectionInterval.objects.create(equipment=self.eq, days=14, set_by=self.user)
        html = self.client.get(reverse('dashboard:maintenance')).content.decode()
        self.assertIn('Overdue by 6\xa0days', html)

    def test_validation(self):
        future = (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        for data in [{'performed_at': future, 'kind': 'inspection'},
                     {'performed_at': '2026-01-01T10:00', 'kind': 'teleport'},
                     {'performed_at': 'yesterday', 'kind': 'repair'},
                     {'performed_at': '2026-01-01T10:00', 'kind': 'other', 'notes': 'x' * 2001}]:
            self.post('dashboard:maintenance_add', data)
        self.assertEqual(MaintenanceEntry.objects.count(), 0)
        for days in (0, 3651, 'x'):
            self.post('dashboard:maintenance_interval', {'days': days})
        self.assertEqual(InspectionInterval.objects.count(), 0)

    def test_only_own_entries_can_be_deleted_and_only_by_post(self):
        mine = MaintenanceEntry.objects.create(equipment=self.eq, performed_at=T0, performed_by=self.user, kind='repair')
        theirs = MaintenanceEntry.objects.create(equipment=self.eq, performed_at=T0, performed_by=self.other, kind='repair')
        self.assertEqual(self.client.get(reverse('dashboard:maintenance_delete', args=[mine.id])).status_code, 405)
        self.assertEqual(self.post('dashboard:maintenance_delete', {}, [theirs.id]).status_code, 403)
        self.assertEqual(self.post('dashboard:maintenance_delete', {}, [mine.id]).status_code, 302)
        self.assertEqual(list(MaintenanceEntry.objects.values_list('id', flat=True)), [theirs.id])

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse('dashboard:maintenance_add'),
                               {'performed_at': '2026-01-01T10:00', 'kind': 'repair'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(MaintenanceEntry.objects.count(), 0)

    def test_alerts_without_inspection_lists_live_alerts_only(self):
        AlertEpisode.objects.create(equipment=self.eq, started_at=T0, peak_score=5.0, run_label='live_run', mode='live')
        AlertEpisode.objects.create(equipment=self.eq, started_at=T0, peak_score=5.0, run_label='r5_fault_open_01',
                                    mode='replay')
        html = self.client.get(reverse('dashboard:maintenance')).content.decode()
        self.assertIn('live_run', html)
        self.assertNotIn('r5_fault_open_01', html)
        MaintenanceEntry.objects.create(equipment=self.eq, performed_at=T0 + timedelta(minutes=5),
                                        performed_by=self.user, kind='inspection')
        html = self.client.get(reverse('dashboard:maintenance')).content.decode()
        self.assertIn('every live alert has an inspection logged', html)

    def test_without_equipment(self):
        Equipment.objects.all().delete()
        html = self.client.get(reverse('dashboard:maintenance')).content.decode()
        self.assertIn('EQ-001 does not exist yet', html)
        self.post('dashboard:maintenance_add', {'performed_at': '2026-01-01T10:00', 'kind': 'repair'})
        self.assertEqual(MaintenanceEntry.objects.count(), 0)


class EvaluationAndSetupViewTests(TabTestCase):
    def test_evaluation_reads_the_result_files(self):
        html = self.client.get(reverse('dashboard:evaluation')).content.decode()
        self.assertIn('Test set: one normal session and three fault sessions, one fault type '
                      '(one motor disconnected), one bench rig. Not independent trials. No claim beyond this setup.', html)
        metrics = json.loads((REPO / 'results' / 'metrics.json').read_text())
        threshold = metrics['methods']['ae_all']['seeds']['0']['threshold']
        self.assertIn(f'{threshold:.3f}', html)
        self.assertIn(metrics['environment']['imported']['tensorflow'], html)
        self.assertIn('performs as well as the autoencoder', html)
        self.assertIn('Imbalance (taped weights)', html)
        self.assertIn('r4_test_drag', html)
        self.assertNotIn('ccuracy', html)
        self.assertEqual(html.count('Recorded, not live'), 5)
        self.assertEqual(html.count('same for all seeds'), 2)                   # once per table, not per cell
        self.assertLess(html.index('Not independent trials'), html.index('What this shows'))
        self.assertLess(html.index('What this shows'), html.index('Detectors on the test sessions'))
        self.assertIn('not a significant difference', html)
        self.assertIn('Runs shorter than the 180 s warm-up lie entirely inside it', html)
        from dashboard import formats
        from django.utils.dateparse import parse_datetime
        self.assertIn(f"From results/metrics.json ({formats.format_datetime(parse_datetime(metrics['created_at']))})",
                      html)
        # the friction runs are shorter than the warm-up: 4 rows x 2 vibration cells, and the band cell of
        # the 2 rows whose reference has frequency bands
        self.assertEqual(html.count('n/a, run shorter than the warm-up'), 10)

    def test_evaluation_without_result_files(self):
        with mock.patch('dashboard.views_tabs.RESULTS_DIR', Path('/nonexistent')):
            html = self.client.get(reverse('dashboard:evaluation')).content.decode()
        self.assertIn('results/metrics.json was not found', html)
        self.assertIn('results/negative_findings.json was not found', html)
        self.assertIn('Not independent trials', html)

    def test_setup_page(self):
        from dashboard.ml import constants as c
        html = self.client.get(reverse('dashboard:setup')).content.decode()
        for text in ('MPU&#8209;6050', 'INA219', 'DS18B20', 'Known limitations', 'without TLS', 'not calibrated',
                     'docs/media/testbed_photo.jpg', f'{int(c.WARMUP_SECONDS)} s', f'{c.RAW_RETENTION_DAYS} days',
                     f'{c.ALERT_SECONDS}th consecutive second'):
            self.assertIn(text, html)
        self.assertNotIn('<img', html)
