"""
Live scoring core: machine state, 30-second buffer, scoring and the alert rule,
one reading at a time.

No Django and no TensorFlow here. The model is passed in as a function
`reconstruct(sequences) -> reconstruction`, so the same code runs with the
saved Keras model (score_live, replay_session) and with a fake model in tests.
Scaling, sequence building, the score, the threshold comparison and the alert
rule are the evaluation's own functions (dashboard.ml.evaluation).

Machine state
-------------
idle        current <= IDLE_CURRENT_A (0.5 A). Not scored.
warming_up  the first WARMUP_SECONDS (180 s) after the current first exceeds
            0.5 A. Not scored: every recorded session starts with a 180 s
            warm-up segment (label suffix _warmup) during which vibration is
            still low and rising, and those segments were excluded from
            training, validation and test. The model has never seen warm-up
            data, so scoring it would raise alerts the evaluation never tested.
running     afterwards. Scored once the buffer holds SEQUENCE_LENGTH (30)
            consecutive running seconds.

Only running seconds enter the buffer, so every scored sequence contains post-
warm-up data only, exactly like the evaluation; the first 29 running seconds are
unscored. A non-running second empties the buffer. A dip to idle while running
does not restart the warm-up; only a gap of more than MAX_GAP_SECONDS (5 s)
between consecutive readings resets the state machine (and the buffer).

Unscored seconds count as "not above the threshold" for the alert rule, as in
the evaluation, so an alert ends when the machine leaves the running state.
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np

from dashboard.ml import dataset
from dashboard.ml import evaluation as ev
from dashboard.ml.constants import (
    ALERT_SECONDS, IDLE_CURRENT_A, MAX_GAP_SECONDS, SEQUENCE_LENGTH, WARMUP_SECONDS,
)

IDLE = 'idle'
WARMING_UP = 'warming_up'
RUNNING = 'running'
MACHINE_STATES = (IDLE, WARMING_UP, RUNNING)


@dataclass
class Reading:
    timestamp: datetime
    run_label: str
    features: dict  # feature name (dataset.FEATURES) -> value; current in amperes


@dataclass
class Episode:
    started_at: datetime
    run_label: str
    peak_score: float
    ended_at: Optional[datetime] = None


@dataclass
class Result:
    timestamp: datetime
    run_label: str
    machine_state: str
    score: Optional[float]
    threshold: float
    above_threshold: Optional[bool]  # None when the second is not scored
    alert_active: bool
    started: Optional[Episode] = None              # episode that fired on this second
    ended: list = field(default_factory=list)      # episodes that ended at or before this second
    peak_updated: Optional[Episode] = None         # active episode whose peak rose on this second


class LiveScorer:
    def __init__(self, reconstruct: Callable, scaler: dict, threshold: float,
                 features=None, alert_seconds=ALERT_SECONDS):
        self.reconstruct = reconstruct
        self.scaler = scaler
        self.threshold = float(threshold)
        self.features = list(features or dataset.FEATURES)
        self.rule = ev.AlertRule(alert_seconds)
        self.buffer = deque(maxlen=SEQUENCE_LENGTH)
        self.warmup_started_at = None
        self.last_timestamp = None
        self.episode = None

    # ------------------------------------------------------------------ state

    def reset(self):
        """Forget everything (after a gap): buffer, warm-up timer and alert run."""
        self.buffer.clear()
        self.warmup_started_at = None
        self.rule.reset()

    def machine_state(self, reading):
        if reading.features['current'] <= IDLE_CURRENT_A:
            return IDLE
        if self.warmup_started_at is None:
            self.warmup_started_at = reading.timestamp
        elapsed = (reading.timestamp - self.warmup_started_at).total_seconds()
        return RUNNING if elapsed >= WARMUP_SECONDS else WARMING_UP

    def _score_buffer(self):
        raw = np.array([[row[name] for name in self.features] for row in self.buffer])
        sequences = ev.build_sequences(ev.standardise_array(raw, self.features, self.scaler)).astype('float32')
        return float(ev.reconstruction_scores(sequences, self.reconstruct(sequences))[0])

    # ------------------------------------------------------------------ main step

    def process(self, reading: Reading, score: bool = True) -> Result:
        """
        Feed one reading (in timestamp order). With score=False the second is
        treated as unscored (used only to rebuild state after a restart).
        """
        ended = []
        if (self.last_timestamp is not None and
                (reading.timestamp - self.last_timestamp).total_seconds() > MAX_GAP_SECONDS):
            if self.episode is not None:
                self.episode.ended_at = self.last_timestamp  # last reading before the gap
                ended.append(self.episode)
                self.episode = None
            self.reset()
        self.last_timestamp = reading.timestamp

        state = self.machine_state(reading)
        value = None
        if state == RUNNING:
            self.buffer.append({name: float(reading.features[name]) for name in self.features})
            if score and len(self.buffer) == SEQUENCE_LENGTH:
                value = self._score_buffer()
        else:
            self.buffer.clear()

        above = None if value is None else bool(ev.above_threshold([value], self.threshold)[0])
        alert_on, fired = self.rule.update(bool(above))

        started = peak_updated = None
        if fired:
            self.episode = Episode(started_at=reading.timestamp, run_label=reading.run_label, peak_score=value)
            started = self.episode
        elif self.episode is not None and alert_on:
            if value > self.episode.peak_score:
                self.episode.peak_score = value
                peak_updated = self.episode
        elif self.episode is not None and not alert_on:
            self.episode.ended_at = reading.timestamp  # first second not above the threshold
            ended.append(self.episode)
            self.episode = None

        return Result(
            timestamp=reading.timestamp, run_label=reading.run_label, machine_state=state,
            score=value, threshold=self.threshold, above_threshold=above, alert_active=alert_on,
            started=started, ended=ended, peak_updated=peak_updated,
        )

    def finish(self):
        """End of a recording (replay): close an open episode at the last reading."""
        if self.episode is None:
            return []
        self.episode.ended_at = self.last_timestamp
        ended, self.episode = [self.episode], None
        return ended
