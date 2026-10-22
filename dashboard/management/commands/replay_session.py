"""
Replay recorded sessions through the live scoring code path (mode "replay").

    python manage.py replay_session --label r5_fault_open_01 [--label ...]

Reads the stored rows of the session including its _warmup rows, keeps their
original timestamps and run_label, and is idempotent.
"""
from django.core.management.base import BaseCommand, CommandError

from dashboard import scoring_service
from dashboard.ml import saved_model


class Command(BaseCommand):
    help = 'Replay recorded sessions through the live scorer (stored with mode "replay")'

    def add_arguments(self, parser):
        parser.add_argument('--label', action='append', required=True,
                            help='Session label without _warmup; repeat for several sessions')
        parser.add_argument('--model-dir', default=str(saved_model.DEFAULT_MODEL_DIR))

    def handle(self, *args, **options):
        try:
            detector = saved_model.load(options['model_dir'])
        except (ValueError, OSError) as e:
            raise CommandError(str(e))

        for label in options['label']:
            try:
                s = scoring_service.replay_session(label, detector)
            except ValueError as e:
                raise CommandError(str(e))
            self.stdout.write(
                f"{s.label}: {s.rows} rows, running from {s.first_running_at}, "
                f"{s.scored_seconds} scored seconds, {len(s.episodes)} alert episodes, "
                f"first alert {s.first_alert_at or 'none'}"
            )
            for started, ended, peak in s.episodes:
                self.stdout.write(f'    episode {started} -> {ended}, peak {peak:.4f}')
