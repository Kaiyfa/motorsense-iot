"""
Tests for the live scorer, replay and anomaly API. No TensorFlow: the model is
replaced by a fake reconstruction function.

The LiveScorer tests are plain unittest.TestCase; the replay, live runner and
API tests use the Django test database.
"""
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dashboard import scoring_service
from dashboard.ml import dataset
from dashboard.ml import evaluation as ev
from dashboard.ml.constants import ALERT_SECONDS, SEQUENCE_LENGTH, WARMUP_SECONDS
from dashboard.ml.live_scoring import IDLE, RUNNING, WARMING_UP, LiveScorer, Reading
from dashboard.models import AlertEpisode, AnomalyScore, Equipment, SensorData

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
IDENTITY_SCALER = {name: {'mean': 0.0, 'std': 1.0} for name in dataset.FEATURES}


def zeros_model(sequences):
    """Fake autoencoder that reconstructs everything as zeros: score = mean of squares."""
    return np.zeros_like(sequences)


def reading(second, current=1.0, vib=0.0, label='run'):
    return Reading(timestamp=T0 + timedelta(seconds=second), run_label=label,
                   features={'vib_rms_g': vib, 'vib_peak_g': 0.0, 'current': current})


def scorer(threshold=1.0, model=zeros_model, scaler=IDENTITY_SCALER):
    return LiveScorer(model, scaler, threshold)


def feed(s, readings):
    return [s.process(r) for r in readings]


# With the zeros model, identity scaler, current 1.0 and vib_peak 0, the score of a
# window is mean((vib^2 + 1) / 3). A window of vib=0 scores 1/3; vib=3 scores 10/3.
QUIET, LOUD = 0.0, 3.0
WARMUP = int(WARMUP_SECONDS)


class MachineStateTests(unittest.TestCase):
    def test_idle_warming_up_running(self):
        s = scorer()
        results = feed(s, [reading(t, current=0.2) for t in range(3)] +
                          [reading(t) for t in range(3, 3 + WARMUP + 40)])
        states = [r.machine_state for r in results]
        self.assertEqual(states[:3], [IDLE] * 3)
        self.assertEqual(states[3:3 + WARMUP], [WARMING_UP] * WARMUP)
        self.assertEqual(states[3 + WARMUP:], [RUNNING] * 40)
        # nothing is scored before 30 running seconds are buffered
        scored = [i for i, r in enumerate(results) if r.score is not None]
        self.assertEqual(scored[0], 3 + WARMUP + SEQUENCE_LENGTH - 1)
        self.assertTrue(all(r.score is None for r in results if r.machine_state != RUNNING))

    def test_exactly_half_an_ampere_is_idle(self):
        self.assertEqual(scorer().process(reading(0, current=0.5)).machine_state, IDLE)

    def test_idle_dip_empties_buffer_but_does_not_restart_warmup(self):
        s = scorer()
        feed(s, [reading(t) for t in range(WARMUP + 40)])            # running and scored
        dip = s.process(reading(WARMUP + 40, current=0.1))
        self.assertEqual(dip.machine_state, IDLE)
        after = feed(s, [reading(t) for t in range(WARMUP + 41, WARMUP + 41 + 30)])
        self.assertTrue(all(r.machine_state == RUNNING for r in after))  # no new warm-up
        self.assertEqual([r.score is not None for r in after], [False] * 29 + [True])

    def test_gap_resets_buffer_and_state_machine(self):
        s = scorer()
        feed(s, [reading(t) for t in range(WARMUP + 40)])
        last = WARMUP + 39
        after_gap = s.process(reading(last + 6))                      # 6 s > 5 s gap
        self.assertEqual(after_gap.machine_state, WARMING_UP)
        self.assertEqual(len(s.buffer), 0)

    def test_gap_of_exactly_five_seconds_is_not_a_reset(self):
        s = scorer()
        feed(s, [reading(t) for t in range(WARMUP + 40)])
        result = s.process(reading(WARMUP + 39 + 5))
        self.assertEqual(result.machine_state, RUNNING)
        self.assertIsNotNone(result.score)


class AlertThroughScorerTests(unittest.TestCase):
    def run_session(self, vib_values, threshold=1.0):
        s = scorer(threshold)
        warm = [reading(t) for t in range(WARMUP)]
        run = [reading(WARMUP + i, vib=v) for i, v in enumerate(vib_values)]
        results = feed(s, warm + run)[WARMUP:]
        return s, results

    def test_alert_fires_on_tenth_second_above_and_ends_on_first_not_above(self):
        # Window i (ending at running second i) contains seconds i-29..i. LOUD seconds
        # push the window mean above 1.0 once enough of them are in the window.
        vib = [QUIET] * 60 + [LOUD] * 60 + [QUIET] * 60
        s, results = self.run_session(vib)
        above = [bool(r.above_threshold) for r in results]
        first_above = above.index(True)
        fired = [i for i, r in enumerate(results) if r.started is not None]
        self.assertEqual(fired, [first_above + ALERT_SECONDS - 1])
        ended = [i for i, r in enumerate(results) if r.ended]
        self.assertEqual(len(ended), 1)
        self.assertFalse(above[ended[0]])
        self.assertTrue(all(above[fired[0]:ended[0]]))
        episode = results[fired[0]].started
        self.assertEqual(episode.ended_at, results[ended[0]].timestamp)
        self.assertAlmostEqual(episode.peak_score,
                               max(r.score for r in results[fired[0]:ended[0]]))

    def test_nine_seconds_above_do_not_alert(self):
        s = scorer(threshold=1.0)
        feed(s, [reading(t) for t in range(WARMUP + SEQUENCE_LENGTH - 1)])  # buffer one short of full
        # each following second is scored; make exactly 9 of them above
        s.threshold = -1.0
        results = feed(s, [reading(WARMUP + SEQUENCE_LENGTH - 1 + i) for i in range(9)])
        s.threshold = 10.0
        results += feed(s, [reading(WARMUP + SEQUENCE_LENGTH + 8 + i) for i in range(5)])
        self.assertFalse(any(r.alert_active for r in results))
        self.assertFalse(any(r.started for r in results))

    def test_gap_ends_active_alert_at_last_reading_before_gap(self):
        s = scorer(threshold=-1.0)                                    # everything scored is above
        results = feed(s, [reading(t) for t in range(WARMUP + 50)])
        self.assertTrue(results[-1].alert_active)
        after = s.process(reading(WARMUP + 49 + 10))
        self.assertEqual(len(after.ended), 1)
        self.assertEqual(after.ended[0].ended_at, results[-1].timestamp)
        self.assertFalse(after.alert_active)

    def test_idle_dip_ends_active_alert(self):
        s = scorer(threshold=-1.0)
        feed(s, [reading(t) for t in range(WARMUP + 50)])
        dip = s.process(reading(WARMUP + 50, current=0.1))
        self.assertEqual(len(dip.ended), 1)
        self.assertEqual(dip.ended[0].ended_at, dip.timestamp)

    def test_scores_and_alerts_equal_the_offline_evaluation(self):
        """Same running rows through the scorer and through the evaluation functions."""
        rng = np.random.default_rng(0)
        n = 200
        values = {'vib_rms_g': rng.normal(0.12, 0.01, n), 'vib_peak_g': rng.normal(0.3, 0.04, n),
                  'current': rng.normal(0.82, 0.005, n)}
        values['current'][120:] -= 0.12                                # open-motor-like drop
        scaler = {'vib_rms_g': {'mean': 0.12, 'std': 0.01}, 'vib_peak_g': {'mean': 0.3, 'std': 0.04},
                  'current': {'mean': 0.82, 'std': 0.005}}
        weights = np.array([0.5, 0.8, 0.9], dtype='float32')

        def model(sequences):                                         # a fixed, non-trivial fake model
            return sequences * weights

        threshold = 1.5
        s = LiveScorer(model, scaler, threshold)
        feed(s, [Reading(T0 + timedelta(seconds=t), 'w', {'vib_rms_g': 0.12, 'vib_peak_g': 0.3, 'current': 0.82})
                 for t in range(WARMUP)])
        live = feed(s, [Reading(T0 + timedelta(seconds=WARMUP + i), 'run',
                                {k: float(v[i]) for k, v in values.items()}) for i in range(n)])

        session = {'features': values}
        seqs = ev.build_sequences(ev.standardise(session, dataset.FEATURES, scaler)).astype('float32')
        offline = ev.causal_scores(ev.reconstruction_scores(seqs, model(seqs)), n)
        live_scores = np.array([np.nan if r.score is None else r.score for r in live])
        np.testing.assert_array_equal(np.isnan(live_scores), np.isnan(offline))
        np.testing.assert_allclose(live_scores[~np.isnan(offline)], offline[~np.isnan(offline)], rtol=1e-6)

        _, offline_starts = ev.alert_state(ev.above_threshold(offline, threshold))
        self.assertEqual([i for i, r in enumerate(live) if r.started], offline_starts)
        self.assertTrue(offline_starts, 'test data should trigger an alert')


class NoTensorFlowTests(unittest.TestCase):
    def test_scoring_core_does_not_import_tensorflow(self):
        code = ('import sys, dashboard.ml.live_scoring, dashboard.ml.evaluation, dashboard.ml.saved_model; '
                'sys.exit(1 if "tensorflow" in sys.modules else 0)')
        result = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_web_views_do_not_import_tensorflow(self):
        code = ('import os, sys; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "monitor.settings"); '
                'import django; django.setup(); import monitor.urls, dashboard.views; '
                'sys.exit(1 if "tensorflow" in sys.modules else 0)')
        result = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


# --------------------------------------------------------------------------- database

FAKE_DETECTOR = SimpleNamespace(reconstruct=zeros_model, scaler=IDENTITY_SCALER,
                                threshold=1.0, features=list(dataset.FEATURES))


def add_session(equipment, label, start_second, warmup_rows=WARMUP, main_vib=(), source='pi'):
    rows = []
    t = start_second
    for _ in range(warmup_rows):
        rows.append(SensorData(equipment=equipment, timestamp=T0 + timedelta(seconds=t), run_label=f'{label}_warmup',
                               temperature=25, current=1.0, vibration_rms=QUIET, vibration_peak=0.0, source=source))
        t += 1
    for vib in main_vib:
        rows.append(SensorData(equipment=equipment, timestamp=T0 + timedelta(seconds=t), run_label=label,
                               temperature=25, current=1.0, vibration_rms=vib, vibration_peak=0.0, source=source))
        t += 1
    SensorData.objects.bulk_create(rows)
    return t


class ReplayTests(TestCase):
    def setUp(self):
        self.eq = Equipment.objects.create(equipment_id='EQ-001', name='Motor testbed', equipment_type='MOTOR',
                                           location='Test bench', installation_date=T0.date())
        add_session(self.eq, 'r9_fault', 0, main_vib=[QUIET] * 60 + [LOUD] * 60 + [QUIET] * 60)

    def test_replay_is_idempotent_and_marked_replay(self):
        first = scoring_service.replay_session('r9_fault', FAKE_DETECTOR)
        counts = (AnomalyScore.objects.count(), AlertEpisode.objects.count())
        second = scoring_service.replay_session('r9_fault', FAKE_DETECTOR)
        self.assertEqual((AnomalyScore.objects.count(), AlertEpisode.objects.count()), counts)
        self.assertEqual(counts[0], WARMUP + 180)
        self.assertEqual(first.scored_seconds, second.scored_seconds)
        self.assertEqual(first.episodes, second.episodes)
        self.assertEqual(len(second.episodes), 1)
        self.assertFalse(AnomalyScore.objects.exclude(mode='replay').exists())
        self.assertFalse(AlertEpisode.objects.exclude(mode='replay').exists())
        # original timestamps and labels are kept
        self.assertEqual(set(AnomalyScore.objects.values_list('run_label', flat=True)),
                         {'r9_fault_warmup', 'r9_fault'})
        self.assertEqual(AnomalyScore.objects.order_by('timestamp').first().timestamp, T0)

    def test_replay_of_unknown_or_warmup_label_is_rejected(self):
        with self.assertRaises(ValueError):
            scoring_service.replay_session('nope', FAKE_DETECTOR)
        with self.assertRaises(ValueError):
            scoring_service.replay_session('r9_fault_warmup', FAKE_DETECTOR)

    def test_sample_rows_are_never_replayed(self):
        add_session(self.eq, 'r9_sample', 10_000, main_vib=[QUIET] * 50, source='sample')
        with self.assertRaises(ValueError):
            scoring_service.replay_session('r9_sample', FAKE_DETECTOR)


class LiveRunnerTests(TestCase):
    def setUp(self):
        self.eq = Equipment.objects.create(equipment_id='EQ-001', name='Motor testbed', equipment_type='MOTOR',
                                           location='Test bench', installation_date=T0.date())

    def test_poll_scores_new_rows_once_and_resumes_after_restart(self):
        end = add_session(self.eq, 'live_run', 0, main_vib=[QUIET] * 40 + [LOUD] * 60)
        runner = scoring_service.LiveRunner('EQ-001', FAKE_DETECTOR)
        self.assertEqual(runner.prime(), 0)
        self.assertEqual(runner.poll(), WARMUP + 100)
        self.assertEqual(runner.poll(), 0)
        self.assertEqual(AnomalyScore.objects.filter(mode='live').count(), WARMUP + 100)
        open_episodes = AlertEpisode.objects.filter(mode='live', ended_at__isnull=True)
        self.assertEqual(open_episodes.count(), 1)

        # restart: a new runner resumes, keeps the open episode and closes it correctly
        SensorData.objects.bulk_create([
            SensorData(equipment=self.eq, timestamp=T0 + timedelta(seconds=end + i), run_label='live_run',
                       temperature=25, current=1.0, vibration_rms=QUIET, vibration_peak=0.0, source='pi')
            for i in range(40)
        ])
        restarted = scoring_service.LiveRunner('EQ-001', FAKE_DETECTOR)
        self.assertGreater(restarted.prime(), 0)
        self.assertTrue(restarted.scorer.rule.active)
        self.assertEqual(restarted.poll(), 40)
        self.assertEqual(AnomalyScore.objects.filter(mode='live').count(), WARMUP + 140)
        self.assertEqual(AlertEpisode.objects.filter(mode='live').count(), 1)
        self.assertIsNotNone(AlertEpisode.objects.get(mode='live').ended_at)


class AnomalyApiTests(TestCase):
    def setUp(self):
        self.eq = Equipment.objects.create(equipment_id='EQ-001', name='Motor testbed', equipment_type='MOTOR',
                                           location='Test bench', installation_date=T0.date())
        add_session(self.eq, 'r9_fault', 0, main_vib=[QUIET] * 60 + [LOUD] * 60 + [QUIET] * 60)
        scoring_service.replay_session('r9_fault', FAKE_DETECTOR)
        self.client.force_login(User.objects.create_user('tester', password='a-long-password'))

    def get(self, name, **kwargs):
        query = kwargs.pop('query', '')
        return self.client.get(reverse(f'dashboard:{name}', kwargs=kwargs) + query)

    def test_live_endpoints_never_show_replay_rows(self):
        status = self.get('live_status').json()
        self.assertEqual(set(status), {
            'equipment_id', 'mode', 'machine_state', 'latest_score', 'latest_score_timestamp', 'threshold',
            'alert_active', 'seconds_since_last_reading', 'scorer_alive', 'scorer_last_poll_seconds_ago'})
        self.assertEqual(status['mode'], 'live')
        self.assertIsNone(status['machine_state'])
        self.assertIsNone(status['latest_score'])
        self.assertFalse(status['alert_active'])
        self.assertFalse(status['scorer_alive'])
        self.assertIsNotNone(status['seconds_since_last_reading'])

        scores = self.get('live_scores', query='?minutes=60').json()
        self.assertEqual(set(scores), {'equipment_id', 'mode', 'minutes', 'count', 'scores'})
        self.assertEqual((scores['mode'], scores['count']), ('live', 0))

        self.assertEqual(self.get('alerts').json()['count'], 0)

    def test_live_status_and_scores_with_live_rows(self):
        now = scoring_service.timezone.now()
        AnomalyScore.objects.create(equipment=self.eq, timestamp=now, run_label='x', score=2.0, threshold=1.0,
                                    above_threshold=True, alert_active=False, machine_state='running', mode='live')
        scoring_service.ScorerHeartbeat.objects.create(equipment=self.eq, last_poll_at=now)
        status = self.get('live_status').json()
        self.assertEqual((status['machine_state'], status['latest_score'], status['threshold']), ('running', 2.0, 1.0))
        self.assertTrue(status['scorer_alive'])
        scores = self.get('live_scores', query='?minutes=5').json()
        self.assertEqual(scores['count'], 1)
        self.assertEqual(set(scores['scores'][0]), {'timestamp', 'run_label', 'machine_state', 'score',
                                                    'threshold', 'above_threshold', 'alert_active'})
        self.assertEqual(self.get('live_scores', query='?minutes=abc').status_code, 400)

    def test_alerts_filter_by_mode(self):
        replay = self.get('alerts', query='?mode=replay').json()
        self.assertEqual(replay['count'], 1)
        self.assertEqual(set(replay['episodes'][0]), {'equipment_id', 'started_at', 'ended_at', 'active',
                                                      'peak_score', 'run_label', 'mode'})
        self.assertEqual(replay['episodes'][0]['mode'], 'replay')
        self.assertEqual(self.get('alerts', query='?mode=all').json()['count'], 1)
        self.assertEqual(self.get('alerts', query='?mode=bogus').status_code, 400)

    def test_replay_detail(self):
        data = self.get('replay_detail', label='r9_fault').json()
        self.assertEqual(set(data), {'label', 'mode', 'equipment_id', 'threshold', 'count', 'scored_seconds',
                                     'scores', 'alerts'})
        self.assertEqual((data['mode'], data['count'], data['threshold']), ('replay', WARMUP + 180, 1.0))
        self.assertEqual(len(data['alerts']), 1)
        self.assertEqual(self.get('replay_detail', label='nope').status_code, 404)

    def test_login_required(self):
        self.client.logout()
        for name, kwargs in [('live_status', {}), ('live_scores', {}), ('alerts', {}),
                             ('replay_detail', {'label': 'r9_fault'})]:
            self.assertEqual(self.get(name, **kwargs).status_code, 302)



if __name__ == '__main__':
    unittest.main()
