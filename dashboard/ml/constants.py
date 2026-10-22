"""
Settings shared by the offline evaluation and the live scorer.

Defined once here and imported by both, so they cannot drift apart. The values
are fixed in docs/evaluation_plan.md; do not change them without a new plan.
"""

# Length of one scoring sequence in seconds (1 Hz rows); the score of second t
# is the score of the sequence that ends at t.
SEQUENCE_LENGTH = 30

# Threshold: this percentile of the method's scores on the validation session.
THRESHOLD_PERCENTILE = 99.5

# An alert fires on the ALERT_SECONDS-th consecutive second above the threshold.
ALERT_SECONDS = 10

# Rows further apart than this break a session: the live scorer clears its buffer
# and state machine, and export_dataset warns about such gaps.
MAX_GAP_SECONDS = 5.0

# Machine state (live scorer). Below or at this current the motor is idle.
IDLE_CURRENT_A = 0.5

# Warm-up after the current first exceeds IDLE_CURRENT_A. Each recorded session
# starts with a 180 s warm-up segment (label suffix _warmup) that is excluded from
# training, validation and test, because vibration is still low and rising while
# the rig warms up. The model has therefore never seen warm-up data, so the live
# scorer does not score it either.
WARMUP_SECONDS = 180.0

# Raw readings (sensor_data) older than this are dropped by the TimescaleDB retention
# policy that `manage.py setup_timescaledb` adds. Scores and alerts are not pruned.
RAW_RETENTION_DAYS = 30
