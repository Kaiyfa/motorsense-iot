"""
Export the testbed sessions to one CSV per role, following docs/evaluation_plan.md.

    python manage.py export_dataset [--out data/dataset]
"""
import csv
import json
import statistics
import subprocess
from collections import defaultdict
from datetime import timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from dashboard.ml import dataset
from dashboard.models import SensorData

MIN_ROWS = 470
MAX_ROWS = 481
MAX_GAP_SECONDS = 5.0

# CSV column -> SensorData field
COLUMNS = {
    'timestamp': 'timestamp',
    'run_label': 'run_label',
    'vib_rms_g': 'vibration_rms',
    'vib_peak_g': 'vibration_peak',
    'current': 'current',          # amperes
    'bus_v': 'bus_voltage',        # plotting only
    'temperature': 'temperature',  # plotting only
}


def git_commit():
    try:
        commit = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=settings.BASE_DIR,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=settings.BASE_DIR,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return commit, bool(dirty)


def iso(ts):
    return ts.astimezone(dt_timezone.utc).isoformat()


class Command(BaseCommand):
    help = 'Export the evaluation dataset (one CSV per role plus manifest.json)'

    def add_arguments(self, parser):
        parser.add_argument('--out', default='data/dataset', help='Output directory (default: data/dataset)')

    def handle(self, *args, **options):
        try:
            dataset.validate_plan()
        except dataset.PlanError as e:
            raise CommandError(f'Session plan is inconsistent, nothing exported: {e}')

        out_dir = Path(options['out'])

        sessions = defaultdict(list)     # label -> rows (dicts with CSV columns)
        excluded = defaultdict(int)      # label -> row count
        dropped_by_source = defaultdict(int)

        fields = list(COLUMNS.values()) + ['source']
        for row in SensorData.objects.order_by('timestamp').values_list(*fields).iterator():
            record = dict(zip(fields, row))
            label = record['run_label']

            if not dataset.is_live_source(record['source']):
                dropped_by_source[record['source']] += 1
                continue

            try:
                role = dataset.role_for_label(label)
            except dataset.PlanError as e:
                raise CommandError(f'Session plan is inconsistent, nothing exported: {e}')

            if role == dataset.EXCLUDED:
                excluded[label] += 1
                continue
            if role in (dataset.TRAIN, dataset.VALIDATION) and label in dataset.TEST_FAULT_LABELS:
                raise CommandError(f'Fault session {label!r} would land in {role!r}; nothing exported')

            sessions[label].append({col: record[field] for col, field in COLUMNS.items()})

        manifest, warnings = self.build_manifest(sessions, excluded, dropped_by_source)

        out_dir.mkdir(parents=True, exist_ok=True)
        for role in dataset.ROLES:
            path = out_dir / f'{role}.csv'
            with path.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(COLUMNS))
                writer.writeheader()
                for label in dataset.ROLE_LABELS[role]:
                    for r in sessions.get(label, []):
                        writer.writerow({**r, 'timestamp': iso(r['timestamp'])})
        with (out_dir / 'manifest.json').open('w') as f:
            json.dump(manifest, f, indent=2)

        self.print_manifest(manifest, out_dir)

    # ------------------------------------------------------------------ manifest

    def build_manifest(self, sessions, excluded, dropped_by_source):
        warnings = []
        commit, dirty = git_commit()
        if commit is None:
            warnings.append('git commit could not be determined')
        elif dirty:
            warnings.append('working tree has uncommitted changes to tracked files')

        session_info = {}
        for role in dataset.ROLES:
            for label in dataset.ROLE_LABELS[role]:
                rows = sessions.get(label, [])
                if not rows:
                    warnings.append(f'{label}: no rows found (role {role})')
                    session_info[label] = {'role': role, 'rows': 0}
                    continue

                timestamps = [r['timestamp'] for r in rows]
                gaps = [(b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:])]
                max_gap = max(gaps) if gaps else None
                duplicates = len(timestamps) - len(set(timestamps))

                features = {}
                for name in dataset.FEATURES:
                    values = [r[name] for r in rows if r[name] is not None]
                    missing = len(rows) - len(values)
                    if missing:
                        warnings.append(f'{label}: {missing} rows with missing {name}')
                    features[name] = {
                        'mean': statistics.fmean(values) if values else None,
                        'std': statistics.stdev(values) if len(values) > 1 else None,
                    }

                if not MIN_ROWS <= len(rows) <= MAX_ROWS:
                    warnings.append(f'{label}: {len(rows)} rows (expected {MIN_ROWS} to {MAX_ROWS})')
                if duplicates:
                    warnings.append(f'{label}: {duplicates} duplicate timestamps')
                if max_gap is not None and max_gap > MAX_GAP_SECONDS:
                    n_large = sum(1 for g in gaps if g > MAX_GAP_SECONDS)
                    warnings.append(f'{label}: largest gap {max_gap:.2f} s '
                                    f'({n_large} gaps above {MAX_GAP_SECONDS:g} s)')

                session_info[label] = {
                    'role': role,
                    'rows': len(rows),
                    'first_timestamp': iso(timestamps[0]),
                    'last_timestamp': iso(timestamps[-1]),
                    'max_gap_seconds': round(max_gap, 3) if max_gap is not None else None,
                    'duplicate_timestamps': duplicates,
                    'features': features,
                }

        manifest = {
            'plan': 'docs/evaluation_plan.md',
            'git_commit': commit,
            'git_dirty': dirty,
            'exported_at': iso(timezone.now()),
            'features': dataset.FEATURES,
            'plot_only': dataset.PLOT_ONLY,
            'units': {'vib_rms_g': 'g', 'vib_peak_g': 'g', 'current': 'A', 'bus_v': 'V', 'temperature': '°C'},
            'std': 'sample standard deviation (n - 1)',
            'rows_per_role': {
                role: sum(session_info[label]['rows'] for label in dataset.ROLE_LABELS[role])
                for role in dataset.ROLES
            },
            'sessions': session_info,
            'excluded_sessions': {
                label: {'rows': n, 'reason': dataset.exclusion_reason(label)}
                for label, n in sorted(excluded.items())
            },
            'rows_dropped_by_source': dict(dropped_by_source),
            'warnings': warnings,
        }
        return manifest, warnings

    # ------------------------------------------------------------------ output

    def print_manifest(self, manifest, out_dir):
        w = self.stdout.write
        w(f"Export to {out_dir}/  (commit {manifest['git_commit'] or 'unknown'}"
          f"{', dirty' if manifest['git_dirty'] else ''}, at {manifest['exported_at']})\n")

        header = (f"{'session':<20} {'role':<12} {'rows':>5}  {'first (UTC)':<19}  {'last (UTC)':<19}"
                  f"  {'max gap s':>9}  {'vib_rms_g':>15}  {'vib_peak_g':>15}  {'current A':>15}")
        w(header)
        w('-' * len(header))
        for label, info in manifest['sessions'].items():
            if not info['rows']:
                w(f"{label:<20} {info['role']:<12} {0:>5}  (no rows)")
                continue
            stats = []
            for name in dataset.FEATURES:
                f = info['features'][name]
                stats.append(f"{f['mean']:.4f}±{f['std']:.4f}" if f['mean'] is not None else 'n/a')
            w(f"{label:<20} {info['role']:<12} {info['rows']:>5}  "
              f"{info['first_timestamp'][:19]:<19}  {info['last_timestamp'][:19]:<19}  "
              f"{info['max_gap_seconds']:>9.3f}  {stats[0]:>15}  {stats[1]:>15}  {stats[2]:>15}")
        w('(feature columns: mean ± sample std)\n')

        w('Rows per role: ' + ', '.join(f'{r} {n}' for r, n in manifest['rows_per_role'].items()))
        w(f"Excluded sessions: {len(manifest['excluded_sessions'])} "
          f"({sum(s['rows'] for s in manifest['excluded_sessions'].values())} rows)")
        for label, info in manifest['excluded_sessions'].items():
            w(f"  {label:<30} {info['rows']:>5}  {info['reason']}")
        dropped = manifest['rows_dropped_by_source']
        w(f"Rows dropped by source: {dropped if dropped else 'none'}\n")

        if manifest['warnings']:
            w(self.style.WARNING(f"Warnings ({len(manifest['warnings'])}):"))
            for warning in manifest['warnings']:
                w(self.style.WARNING(f'  - {warning}'))
        else:
            w(self.style.SUCCESS('Warnings: none'))
