"""
Live anomaly scorer: a separate process, so the web server never loads TensorFlow.

    python manage.py score_live [--equipment EQ-001] [--interval 1]
"""
import time

from django.core.management.base import BaseCommand, CommandError

from dashboard import scoring_service
from dashboard.ml import saved_model


class Command(BaseCommand):
    help = 'Score new live sensor readings with the saved autoencoder and record alerts'

    def add_arguments(self, parser):
        parser.add_argument('--equipment', default='EQ-001')
        parser.add_argument('--interval', type=float, default=1.0, help='Poll interval in seconds (default 1)')
        parser.add_argument('--model-dir', default=str(saved_model.DEFAULT_MODEL_DIR))
        parser.add_argument('--once', action='store_true', help='Poll once and exit')

    def handle(self, *args, **options):
        equipment_id = options['equipment']
        try:
            scoring_service.ensure_equipment(equipment_id)
            detector = saved_model.load(options['model_dir'])
        except (ValueError, OSError) as e:
            raise CommandError(str(e))

        runner = scoring_service.LiveRunner(equipment_id, detector)
        primed = runner.prime()
        self.stdout.write(f'Scoring {equipment_id} (threshold {detector.threshold:.4f}); '
                          f'resumed after {runner.last_timestamp or "nothing"} using {primed} earlier rows')
        try:
            while True:
                processed = runner.poll()
                if processed:
                    self.stdout.write(f'{processed} rows scored up to {runner.last_timestamp}')
                if options['once']:
                    break
                if processed < scoring_service.POLL_BATCH:
                    time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write('Stopped.')
