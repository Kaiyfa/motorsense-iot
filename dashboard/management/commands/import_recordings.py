"""
Load the published recordings (data/recordings/raw) into sensor_data, so the dashboard
can be tried without the rig.

    python manage.py import_recordings [--label LABEL ...] [--replace] [--all-rows]

Default labels: the evaluation's sessions (training, validation and test) with their
_warmup labels. Rows are stored as the ingest endpoint stores a reading from the Pi:
source "pi", equipment EQ-001, the original timestamps and labels, current in A.

By default the rows listed in data/recordings/not_in_database.csv are left out, so the
imported data is the data the evaluation used; --all-rows imports every row. Rows the
logger would not have posted (temperature or current not a number) are always left out.

A label that already has rows is left alone: unchanged if they are exactly the rows this
command would import, otherwise the command stops before changing anything, unless
--replace is given (its rows are then deleted and imported again).
"""
import csv
import math
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.ml import dataset
from dashboard.models import SensorData
from dashboard.views import live_equipment

RECORDINGS = Path(settings.BASE_DIR) / 'data' / 'recordings'
DEFAULT_LABELS = [label + suffix
                  for role in (dataset.TRAIN_LABELS, dataset.VALIDATION_LABELS, dataset.TEST_NORMAL_LABELS,
                               dataset.TEST_FAULT_LABELS)
                  for label in role for suffix in (dataset.WARMUP_SUFFIX, '')]


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_recordings(data_dir, labels):
    """{label: [row dict, ...]} for the requested labels, from every CSV file in data_dir."""
    rows = {label: [] for label in labels}
    for path in sorted(Path(data_dir).glob('*.csv')):
        with path.open(newline='') as f:
            for row in csv.DictReader(f):
                label = (row.get('label') or '').strip()
                if label in rows:
                    rows[label].append(row)
    return rows


def read_not_in_database(path):
    if not Path(path).exists():
        return set()
    with Path(path).open(newline='') as f:
        return {(r['label'], datetime.fromisoformat(r['timestamp_utc'])) for r in csv.DictReader(f)}


class Command(BaseCommand):
    help = 'Load published recordings (data/recordings/raw) into sensor_data'

    def add_arguments(self, parser):
        parser.add_argument('--label', action='append',
                            help='Label to import (repeatable; a session and its _warmup label are separate '
                                 'labels). Default: the evaluation sessions with their warm-up labels')
        parser.add_argument('--data', default=str(RECORDINGS / 'raw'), help='Folder with the CSV files')
        parser.add_argument('--not-in-database', default=str(RECORDINGS / 'not_in_database.csv'),
                            help='Rows to leave out unless --all-rows')
        parser.add_argument('--all-rows', action='store_true',
                            help='Import every row, including those that never reached the database')
        parser.add_argument('--replace', action='store_true',
                            help='Delete and re-import labels that already have different rows')

    def handle(self, *args, **options):
        labels = options['label'] or DEFAULT_LABELS
        if not Path(options['data']).is_dir():
            raise CommandError(f"Not a directory: {options['data']}")
        recorded = read_recordings(options['data'], labels)
        unknown = [label for label, rows in recorded.items() if not rows]
        if unknown:
            raise CommandError(f"No rows for {', '.join(unknown)} in {options['data']}")
        skip = set() if options['all_rows'] else read_not_in_database(options['not_in_database'])

        plan = {}
        for label, rows in recorded.items():
            keep, not_posted, not_in_db = [], 0, 0
            for row in rows:
                timestamp = datetime.fromisoformat(row['timestamp_utc'])
                values = {k: _number(row.get(k)) for k in ('temp_c', 'vib_rms_g', 'vib_peak_g', 'current_ma', 'bus_v')}
                if (label, timestamp) in skip:
                    not_in_db += 1
                elif values['temp_c'] is None or values['current_ma'] is None:
                    not_posted += 1      # the logger posts a row only when both are numbers
                else:
                    keep.append((timestamp, values))
            plan[label] = {'rows': len(rows), 'keep': keep, 'not_in_db': not_in_db, 'not_posted': not_posted}

        equipment = live_equipment()
        conflicts = []
        for label, p in plan.items():
            stored = set(SensorData.objects.filter(equipment=equipment, source='pi', run_label=label)
                         .values_list('timestamp', flat=True))
            p['stored'] = len(stored)
            p['unchanged'] = bool(stored) and stored == {t for t, _ in p['keep']}
            if stored and not p['unchanged'] and not options['replace']:
                conflicts.append(f'{label} ({len(stored)} rows)')
        if conflicts:
            raise CommandError('These labels already have different rows; nothing was changed. Use --replace to '
                               'delete and re-import them: ' + ', '.join(conflicts))

        with transaction.atomic():
            for label, p in plan.items():
                if p['unchanged']:
                    action = 'already imported, unchanged'
                else:
                    deleted = 0
                    if p['stored']:
                        deleted, _ = SensorData.objects.filter(equipment=equipment, source='pi',
                                                               run_label=label).delete()
                    SensorData.objects.bulk_create([
                        SensorData(equipment=equipment, timestamp=t, run_label=label, source='pi',
                                   temperature=v['temp_c'], vibration_rms=v['vib_rms_g'],
                                   vibration_peak=v['vib_peak_g'], current=v['current_ma'] / 1000.0,
                                   bus_voltage=v['bus_v'])
                        for t, v in p['keep']])
                    action = f"imported {len(p['keep'])}" + (f' (replaced {deleted})' if deleted else '')
                self.stdout.write(f"{label}: {p['rows']} rows in the files, {p['not_in_db']} not in the database, "
                                  f"{p['not_posted']} not posted (no temperature or current); {action}")
