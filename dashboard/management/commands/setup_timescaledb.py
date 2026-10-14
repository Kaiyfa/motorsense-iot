"""
Custom management command to set up TimescaleDB hypertables
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

# Tables converted to hypertables, partitioned on their timestamp column
HYPERTABLES = [
    ('sensor_data', 'timestamp', '1 day'),
]


class Command(BaseCommand):
    help = 'Set up TimescaleDB hypertables for time-series data'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            try:
                # Enable TimescaleDB extension
                cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
                self.stdout.write(self.style.SUCCESS('✓ TimescaleDB extension enabled'))

                for table, time_column, chunk_interval in HYPERTABLES:
                    self._ensure_composite_pk(cursor, table, time_column)

                    # Convert table to hypertable
                    cursor.execute(
                        """
                        SELECT create_hypertable(
                            %s::regclass,
                            %s::name,
                            chunk_time_interval => %s::interval,
                            if_not_exists => TRUE,
                            migrate_data => TRUE
                        );
                        """,
                        [table, time_column, chunk_interval],
                    )
                    self.stdout.write(self.style.SUCCESS(f'✓ {table} converted to hypertable'))

                # Create continuous aggregate for hourly averages
                cursor.execute("""
                    CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_data_hourly
                    WITH (timescaledb.continuous) AS
                    SELECT
                        equipment_id,
                        time_bucket('1 hour', timestamp) AS hour,
                        AVG(vibration_x) AS avg_vibration_x,
                        AVG(vibration_y) AS avg_vibration_y,
                        AVG(vibration_z) AS avg_vibration_z,
                        AVG(temperature) AS avg_temperature,
                        AVG(current) AS avg_current,
                        MAX(vibration_rms) AS max_vibration_rms
                    FROM sensor_data
                    GROUP BY equipment_id, hour
                    WITH NO DATA;
                """)
                self.stdout.write(self.style.SUCCESS('✓ Continuous aggregate created'))

                # Add retention policy (keep raw data for 30 days)
                cursor.execute("""
                    SELECT add_retention_policy('sensor_data', INTERVAL '30 days', if_not_exists => TRUE);
                """)
                self.stdout.write(self.style.SUCCESS('✓ Retention policy added (30 days)'))

                self.stdout.write(self.style.SUCCESS('\n✅ TimescaleDB setup completed successfully!'))

            except Exception as e:
                raise CommandError(f'❌ Error: {e}') from e

    def _ensure_composite_pk(self, cursor, table, time_column):
        """
        TimescaleDB requires every unique index to include the partitioning
        column, so replace Django's PRIMARY KEY (id) with PRIMARY KEY (id, <time_column>).
        Skipped if the primary key already includes the time column.
        """
        cursor.execute(
            """
            SELECT c.conname, array_agg(a.attname::text ORDER BY a.attnum)
            FROM pg_constraint c
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
            WHERE c.conrelid = %s::regclass AND c.contype = 'p'
            GROUP BY c.conname;
            """,
            [table],
        )
        row = cursor.fetchone()
        if row and time_column in row[1]:
            self.stdout.write(f'  {table} primary key already includes {time_column}, skipping')
            return

        qn = connection.ops.quote_name
        with transaction.atomic():
            if row:
                cursor.execute(f'ALTER TABLE {qn(table)} DROP CONSTRAINT {qn(row[0])};')
            cursor.execute(
                f'ALTER TABLE {qn(table)} ADD PRIMARY KEY ("id", {qn(time_column)});'
            )
        self.stdout.write(self.style.SUCCESS(f'✓ {table} primary key set to (id, {time_column})'))
