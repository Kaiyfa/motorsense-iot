"""
Unit tests for dashboard/ml/evaluation.py on small synthetic data.
No TensorFlow and no database: plain unittest.TestCase, also runnable with
`python -m unittest dashboard.tests_evaluation`.
"""
import math
import unittest

import numpy as np

from dashboard.ml import evaluation as ev
from dashboard.ml.evaluation import FAULT, NORMAL


class SequenceTests(unittest.TestCase):
    def test_windows_are_consecutive_and_causal(self):
        values = np.arange(10, dtype=float).reshape(-1, 1)
        seqs = ev.build_sequences(values, length=4)
        self.assertEqual(seqs.shape, (7, 4, 1))
        np.testing.assert_array_equal(seqs[0, :, 0], [0, 1, 2, 3])
        np.testing.assert_array_equal(seqs[-1, :, 0], [6, 7, 8, 9])

    def test_sequences_never_cross_session_boundaries(self):
        # Session A holds values 0..9, session B 100..105. A window mixing the two
        # would contain values from both ranges.
        a = np.arange(10, dtype=float).reshape(-1, 1)
        b = np.arange(100, 106, dtype=float).reshape(-1, 1)
        seqs = ev.sequences_for_sessions([a, b], length=4)
        self.assertEqual(len(seqs), (10 - 3) + (6 - 3))
        for seq in seqs:
            in_a = np.all(seq < 50)
            in_b = np.all(seq >= 100)
            self.assertTrue(in_a or in_b, f'sequence crosses a session boundary: {seq.ravel()}')

    def test_short_session_gives_no_sequences(self):
        seqs = ev.build_sequences(np.zeros((3, 2)), length=4)
        self.assertEqual(seqs.shape, (0, 4, 2))

    def test_causal_scores_leave_first_seconds_unscored(self):
        scores = ev.causal_scores([1.0, 2.0, 3.0], n_seconds=6, length=4)
        self.assertTrue(np.all(np.isnan(scores[:3])))
        np.testing.assert_array_equal(scores[3:], [1.0, 2.0, 3.0])
        with self.assertRaises(ValueError):
            ev.causal_scores([1.0, 2.0], n_seconds=6, length=4)

    def test_zscore_baseline(self):
        session = {'features': {'current': np.array([1.0, 2.0, 3.0, 5.0, -1.0])}}
        scaler = {'current': {'mean': 2.0, 'std': 2.0}}
        scores = ev.zscore_scores(session, 'current', scaler, length=2)
        self.assertTrue(math.isnan(scores[0]))
        np.testing.assert_allclose(scores[1:], [0.0, 0.5, 1.5, 1.5])


class ThresholdTests(unittest.TestCase):
    def test_percentile_threshold_ignores_unscored(self):
        scores = np.concatenate([[np.nan] * 5, np.arange(1, 201, dtype=float)])
        self.assertAlmostEqual(ev.percentile_threshold(scores, 99.5), np.percentile(np.arange(1, 201), 99.5))
        self.assertAlmostEqual(ev.percentile_threshold(np.arange(1, 201, dtype=float), 50), 100.5)

    def test_above_is_strict_and_nan_is_false(self):
        above = ev.above_threshold([np.nan, 0.9, 1.0, 1.1], 1.0)
        np.testing.assert_array_equal(above, [False, False, False, True])

    def test_threshold_needs_scores(self):
        with self.assertRaises(ValueError):
            ev.percentile_threshold([np.nan, np.nan])


class AlertRuleTests(unittest.TestCase):
    def test_nine_seconds_do_not_fire(self):
        alert, starts = ev.alert_state([True] * 9 + [False] * 5, run_length=10)
        self.assertFalse(alert.any())
        self.assertEqual(starts, [])

    def test_fires_on_tenth_second_and_stays_on(self):
        above = [False] * 3 + [True] * 15 + [False] * 2
        alert, starts = ev.alert_state(above, run_length=10)
        self.assertEqual(starts, [12])  # 10th consecutive True is index 3 + 9
        self.assertFalse(alert[:12].any())
        self.assertTrue(alert[12:18].all())
        self.assertFalse(alert[18:].any())

    def test_interruption_resets_the_run_and_counts_episodes(self):
        above = [True] * 10 + [False] + [True] * 9 + [False] + [True] * 12
        alert, starts = ev.alert_state(above, run_length=10)
        self.assertEqual(starts, [9, 30])
        self.assertEqual(int(alert.sum()), 1 + 3)

    def test_session_alerts_delay_from_first_scored_second(self):
        scores = np.array([np.nan] * 29 + [5.0] * 20)
        result = ev.session_alerts(scores, threshold=1.0, run_length=10)
        self.assertEqual(result, {'scored_seconds': 20, 'alert': True, 'episodes': 1, 'delay_seconds': 9})

        quiet = ev.session_alerts(np.array([np.nan] * 29 + [0.5] * 20), threshold=1.0)
        self.assertEqual(quiet, {'scored_seconds': 20, 'alert': False, 'episodes': 0, 'delay_seconds': None})


class MetricsTests(unittest.TestCase):
    def test_per_second_counts(self):
        fault = np.array([np.nan, np.nan, 2.0, 2.0, 0.5])   # 2 TP, 1 FN
        normal = np.array([np.nan, 0.5, 0.5, 2.0, 0.5])     # 1 FP, 3 TN
        counts = ev.per_second_counts([(FAULT, fault), (NORMAL, normal)], threshold=1.0)
        self.assertEqual((counts['tp'], counts['fp'], counts['fn'], counts['tn']), (2, 1, 1, 3))
        self.assertAlmostEqual(counts['precision'], 2 / 3)
        self.assertAlmostEqual(counts['recall'], 2 / 3)
        self.assertAlmostEqual(counts['false_positive_rate'], 1 / 4)

    def test_undefined_ratios_are_none(self):
        counts = ev.per_second_counts([(NORMAL, np.array([0.1, 0.2]))], threshold=1.0)
        self.assertEqual((counts['tp'], counts['fp'], counts['fn'], counts['tn']), (0, 0, 0, 2))
        self.assertIsNone(counts['precision'])
        self.assertIsNone(counts['recall'])
        self.assertEqual(counts['false_positive_rate'], 0.0)

    def test_per_session_counts(self):
        results = [
            (FAULT, {'alert': True}), (FAULT, {'alert': False}), (FAULT, {'alert': True}),
            (NORMAL, {'alert': True}),
        ]
        counts = ev.per_session_counts(results)
        self.assertEqual((counts['tp'], counts['fp'], counts['fn'], counts['tn']), (2, 1, 1, 0))
        self.assertAlmostEqual(counts['precision'], 2 / 3)
        self.assertAlmostEqual(counts['recall'], 2 / 3)

    def test_summarize_across_seeds(self):
        s = ev.summarize_across_seeds([1.0, 2.0, 3.0, None])
        self.assertEqual((s['mean'], s['min'], s['max'], s['n']), (2.0, 1.0, 3.0, 3))
        self.assertAlmostEqual(s['std'], 1.0)
        self.assertIsNone(ev.summarize_across_seeds([None])['mean'])


class ScalerTests(unittest.TestCase):
    def test_scaler_uses_training_sessions_only(self):
        sessions = {
            'a': {'role': 'train', 'features': {'x': np.array([0.0, 2.0])}},
            'b': {'role': 'train', 'features': {'x': np.array([4.0, 6.0])}},
            'v': {'role': 'validation', 'features': {'x': np.array([1000.0])}},
        }
        scaler = ev.fit_scaler(sessions, ['x'])
        self.assertAlmostEqual(scaler['x']['mean'], 3.0)
        self.assertAlmostEqual(scaler['x']['std'], np.std([0.0, 2.0, 4.0, 6.0]))


class SharedConstantsTests(unittest.TestCase):
    """The evaluation and the live scorer must use the same fixed settings."""

    def test_values_fixed_by_the_plan(self):
        from dashboard.ml import constants as c
        self.assertEqual(c.SEQUENCE_LENGTH, 30)
        self.assertEqual(c.THRESHOLD_PERCENTILE, 99.5)
        self.assertEqual(c.ALERT_SECONDS, 10)
        self.assertEqual(c.MAX_GAP_SECONDS, 5.0)
        self.assertEqual(c.IDLE_CURRENT_A, 0.5)
        self.assertEqual(c.WARMUP_SECONDS, 180.0)

    def test_evaluation_uses_the_shared_constants(self):
        from dashboard.ml import constants as c
        self.assertIs(ev.SEQUENCE_LENGTH, c.SEQUENCE_LENGTH)
        self.assertIs(ev.THRESHOLD_PERCENTILE, c.THRESHOLD_PERCENTILE)
        self.assertIs(ev.ALERT_SECONDS, c.ALERT_SECONDS)


if __name__ == '__main__':
    unittest.main()
