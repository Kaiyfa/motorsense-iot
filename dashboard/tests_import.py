"""Tests for manage.py import_recordings."""
import csv
import io
import tempfile
from datetime import datetime
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from dashboard.management.commands import import_recordings as cmd
from dashboard.models import Equipment, SensorData

HEADER = ['timestamp_utc', 'temp_c', 'vib_rms_g', 'vib_peak_g', 'current_ma', 'bus_v', 'n_samples', 'i2c_errors',
          'label']


def row(second, label, current='816.0', temp='25.5'):
    return [f'2026-10-21T10:00:{second:02d}.123456+00:00', temp, '0.12345', '0.31', current, '7.85', '200', '0', label]


class ImportRecordingsTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / 'raw'
        self.dir.mkdir()
        with (self.dir / 'log_a.csv').open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            for s in range(3):
                w.writerow(row(s, 's1_warmup'))
            for s in range(3, 8):
                w.writerow(row(s, 's1'))
            w.writerow(row(8, 's1', current='nan'))          # a row the logger would not post
        with (self.dir / 'log_b.csv').open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerow(row(20, 'other'))
        self.skip = Path(self.tmp.name) / 'not_in_database.csv'
        self.skip.write_text('label,timestamp_utc\ns1,2026-10-21T10:00:07.123456+00:00\n')

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self, *args):
        out = io.StringIO()
        call_command('import_recordings', '--data', str(self.dir), '--not-in-database', str(self.skip), *args,
                     stdout=out)
        return out.getvalue()

    def test_import_like_the_ingest_endpoint(self):
        out = self.run_import('--label', 's1_warmup', '--label', 's1')
        self.assertIn('s1: 6 rows in the files, 1 not in the database, 1 not posted (no temperature or current); '
                      'imported 4', out)
        self.assertIn('s1_warmup: 3 rows in the files, 0 not in the database, 0 not posted', out)
        rows = SensorData.objects.filter(run_label='s1').order_by('timestamp')
        self.assertEqual(rows.count(), 4)
        first = rows.first()
        self.assertEqual(first.timestamp, datetime.fromisoformat('2026-10-21T10:00:03.123456+00:00'))
        self.assertEqual((first.source, first.equipment_id), ('pi', 'EQ-001'))
        self.assertEqual(first.current, 816.0 / 1000.0)
        self.assertEqual((first.vibration_rms, first.vibration_peak, first.bus_voltage, first.temperature),
                         (0.12345, 0.31, 7.85, 25.5))
        self.assertEqual(Equipment.objects.get().name, 'Motor testbed')
        self.assertFalse(SensorData.objects.filter(run_label='other').exists())

    def test_all_rows(self):
        self.run_import('--label', 's1', '--all-rows')
        self.assertEqual(SensorData.objects.filter(run_label='s1').count(), 5)

    def test_idempotent_and_refuses_to_touch_other_rows(self):
        self.run_import('--label', 's1')
        self.assertIn('s1: 6 rows in the files, 1 not in the database, 1 not posted (no temperature or current); '
                      'already imported, unchanged', self.run_import('--label', 's1'))
        self.assertEqual(SensorData.objects.filter(run_label='s1').count(), 4)
        # different rows under the label: stop before changing anything, also for the other label
        with self.assertRaisesMessage(CommandError, 's1 (4 rows)'):
            self.run_import('--label', 's1_warmup', '--label', 's1', '--all-rows')
        self.assertFalse(SensorData.objects.filter(run_label='s1_warmup').exists())
        self.assertEqual(SensorData.objects.filter(run_label='s1').count(), 4)
        out = self.run_import('--label', 's1', '--all-rows', '--replace')
        self.assertIn('imported 5 (replaced 4)', out)
        self.assertEqual(SensorData.objects.filter(run_label='s1').count(), 5)

    def test_unknown_label(self):
        with self.assertRaisesMessage(CommandError, 'No rows for nope'):
            self.run_import('--label', 'nope')

    def test_default_labels_and_the_published_recordings(self):
        self.assertEqual(len(cmd.DEFAULT_LABELS), 16)
        self.assertIn('r5_fault_open_01_warmup', cmd.DEFAULT_LABELS)
        out = io.StringIO()
        call_command('import_recordings', '--label', 'r5_fault_open_01_warmup', '--label', 'r5_normal_05', stdout=out)
        # the counts that reached the database (data/recordings/sessions.csv, rows_in_database)
        self.assertEqual(SensorData.objects.filter(run_label='r5_fault_open_01_warmup').count(), 153)
        self.assertEqual(SensorData.objects.filter(run_label='r5_normal_05').count(), 479)
        sessions = {r['label']: r for r in csv.DictReader(open(cmd.RECORDINGS / 'sessions.csv'))}
        self.assertEqual(sessions['r5_normal_05']['rows_in_database'], '479')
