"""Tests for the state timeline segmentation (dashboard/timeline.py). No database needed."""
import unittest
from datetime import datetime, timedelta, timezone as dt_timezone

from dashboard.timeline import build_segments, row_kind

T0 = datetime(2026, 10, 22, 12, 0, 0, tzinfo=dt_timezone.utc)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def rows(spec):
    """spec: list of (second, kind) with kind idle/warming/running/normal/alert."""
    out = []
    for second, kind in spec:
        state = {'idle': 'idle', 'warming': 'warming_up'}.get(kind, 'running')
        score = None if kind in ('idle', 'warming', 'running') else 1.0
        out.append((at(second), state, score, kind == 'alert'))
    return out


def summary(segments):
    return [(s['label'], (s['start'] - T0).total_seconds(), (s['end'] - T0).total_seconds()) for s in segments]


class RowKindTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(row_kind('idle', None, False), 'idle')
        self.assertEqual(row_kind('warming_up', None, False), 'warming')
        self.assertEqual(row_kind('running', None, False), 'running')
        self.assertEqual(row_kind('running', 1.2, False), 'normal')
        self.assertEqual(row_kind('running', 9.0, True), 'alert')


class SegmentTests(unittest.TestCase):
    def test_consecutive_rows_merge_and_states_split(self):
        spec = [(i, 'idle') for i in range(3)] + [(i, 'warming') for i in range(3, 6)] + \
               [(i, 'running') for i in range(6, 8)] + [(i, 'normal') for i in range(8, 10)] + \
               [(i, 'alert') for i in range(10, 12)]
        segs = build_segments(rows(spec), at(0), at(12))
        self.assertEqual(summary(segs), [
            ('Idle', 0, 3), ('Warm-up', 3, 6), ('Running', 6, 8), ('Normal', 8, 10), ('Alert', 10, 12)])

    def test_gap_of_five_seconds_is_not_a_gap(self):
        segs = build_segments(rows([(0, 'normal'), (5, 'normal')]), at(0), at(6))
        self.assertEqual(summary(segs), [('Normal', 0, 6)])

    def test_gap_larger_than_five_seconds_is_offline(self):
        segs = build_segments(rows([(0, 'normal'), (1, 'normal'), (9, 'warming'), (10, 'warming')]), at(0), at(11))
        self.assertEqual(summary(segs), [('Normal', 0, 2), ('Offline', 2, 9), ('Warm-up', 9, 11)])

    def test_gap_with_unscored_readings_is_not_scored_not_offline(self):
        segs = build_segments(rows([(0, 'normal'), (20, 'normal')]), at(0), at(21),
                              readings_between=lambda start, end: True)
        self.assertEqual(summary(segs), [('Normal', 0, 1), ('Not scored', 1, 20), ('Normal', 20, 21)])

    def test_same_state_on_both_sides_of_a_gap_stays_separate(self):
        segs = build_segments(rows([(0, 'idle'), (10, 'idle')]), at(0), at(11))
        self.assertEqual(summary(segs), [('Idle', 0, 1), ('Offline', 1, 10), ('Idle', 10, 11)])

    def test_trailing_offline_only_after_the_live_limit(self):
        data = rows([(0, 'normal'), (1, 'normal')])
        self.assertEqual(summary(build_segments(data, at(0), at(10), offline_after=15)), [('Normal', 0, 2)])
        self.assertEqual(summary(build_segments(data, at(0), at(30), offline_after=15)),
                         [('Normal', 0, 2), ('Offline', 2, 30)])
        # a finished recording never gets a trailing Offline segment
        self.assertEqual(summary(build_segments(data, at(0), at(30))), [('Normal', 0, 2)])

    def test_leading_time_is_offline_only_when_an_earlier_row_exists(self):
        data = rows([(20, 'idle')])
        self.assertEqual(summary(build_segments(data, at(0), at(21))), [('Idle', 20, 21)])
        self.assertEqual(summary(build_segments(data, at(0), at(21), previous_ts=at(-100))),
                         [('Offline', 0, 20), ('Idle', 20, 21)])

    def test_no_rows_in_range_after_an_old_row_is_offline(self):
        segs = build_segments([], at(0), at(60), previous_ts=at(-10), offline_after=15)
        self.assertEqual(summary(segs), [('Offline', 0, 60)])
        self.assertEqual(build_segments([], at(0), at(60)), [])

    def test_segments_are_clipped_to_the_range(self):
        segs = build_segments(rows([(0, 'normal'), (1, 'normal'), (2, 'normal')]), at(1), at(2))
        self.assertEqual(summary(segs), [('Normal', 1, 2)])


if __name__ == '__main__':
    unittest.main()
