"""
Database side of the live scorer: reads SensorData, runs it through
dashboard.ml.live_scoring.LiveScorer and writes AnomalyScore / AlertEpisode rows.

Used by the score_live and replay_session management commands. No TensorFlow
import here: the detector (model, scaler, threshold) is passed in.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from django.db import transaction
from django.utils import timezone

from dashboard.ml import dataset
from dashboard.ml.constants import ALERT_SECONDS, MAX_GAP_SECONDS
from dashboard.ml.live_scoring import RUNNING, Episode, LiveScorer, Reading
from dashboard.models import AlertEpisode, AnomalyScore, Equipment, ScorerHeartbeat, SensorData

LIVE = 'live'
REPLAY = 'replay'
LIVE_SOURCE = dataset.LIVE_SOURCE

FEATURE_FIELDS = [dataset.SENSORDATA_FIELDS[name] for name in dataset.FEATURES]
READING_FIELDS = ['timestamp', 'run_label'] + FEATURE_FIELDS

POLL_BATCH = 500
PRIME_MAX_ROWS = 7200


def to_reading(values):
    timestamp, run_label, *features = values
    return Reading(timestamp=timestamp, run_label=run_label or '',
                   features=dict(zip(dataset.FEATURES, features)))


def new_scorer(detector):
    return LiveScorer(detector.reconstruct, detector.scaler, detector.threshold, detector.features)


class Writer:
    """Turns scorer results into AnomalyScore and AlertEpisode rows for one equipment and mode."""

    def __init__(self, equipment_id, mode):
        self.equipment_id = equipment_id
        self.mode = mode
        self.episode_rows = {}  # id(Episode) -> AlertEpisode

    def adopt(self, episode, row):
        self.episode_rows[id(episode)] = row

    def _close(self, episode):
        row = self.episode_rows.pop(id(episode), None)
        if row is not None:
            row.ended_at = episode.ended_at
            row.peak_score = episode.peak_score
            row.save(update_fields=['ended_at', 'peak_score'])

    def write(self, results, final_ended=()):
        AnomalyScore.objects.bulk_create([
            AnomalyScore(
                equipment_id=self.equipment_id, timestamp=r.timestamp, run_label=r.run_label,
                score=r.score, threshold=r.threshold, above_threshold=r.above_threshold,
                alert_active=r.alert_active, machine_state=r.machine_state, mode=self.mode,
            )
            for r in results
        ])
        for r in results:
            for episode in r.ended:
                self._close(episode)
            if r.started is not None:
                self.episode_rows[id(r.started)] = AlertEpisode.objects.create(
                    equipment_id=self.equipment_id, started_at=r.started.started_at,
                    peak_score=r.started.peak_score, run_label=r.started.run_label, mode=self.mode,
                )
            if r.peak_updated is not None and id(r.peak_updated) in self.episode_rows:
                row = self.episode_rows[id(r.peak_updated)]
                row.peak_score = r.peak_updated.peak_score
                row.save(update_fields=['peak_score'])
        for episode in final_ended:
            self._close(episode)


# --------------------------------------------------------------------------- replay

@dataclass
class ReplaySummary:
    label: str
    equipment_id: str
    rows: int
    scored_seconds: int
    first_scored_at: Optional[datetime]
    first_running_at: Optional[datetime]
    episodes: list = field(default_factory=list)  # (started_at, ended_at, peak_score)

    @property
    def first_alert_at(self):
        return self.episodes[0][0] if self.episodes else None


def replay_labels(label):
    return [f'{label}{dataset.WARMUP_SUFFIX}', label]


def replay_session(label, detector):
    """
    Run one recorded session (its _warmup rows and its main rows) through the
    live code path and store the results with mode "replay". Idempotent: earlier
    replay rows of the same session are deleted in the same transaction.
    """
    if label.endswith(dataset.WARMUP_SUFFIX):
        raise ValueError(f'give the session label without {dataset.WARMUP_SUFFIX!r}')
    labels = replay_labels(label)
    rows = list(
        SensorData.objects.filter(source=LIVE_SOURCE, run_label__in=labels)
        .order_by('timestamp').values_list('equipment_id', *READING_FIELDS)
    )
    if not rows:
        raise ValueError(f'no stored rows for {label!r} (source {LIVE_SOURCE!r})')
    equipment_ids = {r[0] for r in rows}
    if len(equipment_ids) != 1:
        raise ValueError(f'{label!r} has rows for several equipment: {sorted(equipment_ids)}')
    equipment_id = equipment_ids.pop()

    scorer = new_scorer(detector)
    results = [scorer.process(to_reading(r[1:])) for r in rows]
    final_ended = scorer.finish()

    with transaction.atomic():
        AnomalyScore.objects.filter(mode=REPLAY, equipment_id=equipment_id, run_label__in=labels).delete()
        AlertEpisode.objects.filter(mode=REPLAY, equipment_id=equipment_id, run_label__in=labels).delete()
        Writer(equipment_id, REPLAY).write(results, final_ended)

    scored = [r for r in results if r.score is not None]
    running = [r for r in results if r.machine_state == RUNNING]
    episodes = list(AlertEpisode.objects.filter(mode=REPLAY, equipment_id=equipment_id, run_label__in=labels)
                    .order_by('started_at').values_list('started_at', 'ended_at', 'peak_score'))
    return ReplaySummary(
        label=label, equipment_id=equipment_id, rows=len(rows), scored_seconds=len(scored),
        first_scored_at=scored[0].timestamp if scored else None,
        first_running_at=running[0].timestamp if running else None,
        episodes=episodes,
    )


# --------------------------------------------------------------------------- live

class LiveRunner:
    """Polls new SensorData rows for one equipment and scores them with mode "live"."""

    def __init__(self, equipment_id, detector):
        self.equipment_id = equipment_id
        self.scorer = new_scorer(detector)
        self.writer = Writer(equipment_id, LIVE)
        self.last_timestamp = None

    def _rows(self):
        return SensorData.objects.filter(equipment_id=self.equipment_id, source=LIVE_SOURCE)

    def prime(self):
        """
        After a restart, rebuild the in-memory state from rows already scored:
        rows since the last gap (at most PRIME_MAX_ROWS) are fed through the same
        scorer without writing anything; only the last ALERT_SECONDS of them are
        scored, which is all the alert rule needs. Returns the number of rows used.
        """
        last = (AnomalyScore.objects.filter(mode=LIVE, equipment_id=self.equipment_id)
                .order_by('-timestamp').first())
        if last is None:
            return 0
        self.last_timestamp = last.timestamp

        previous = list(self._rows().filter(timestamp__lte=last.timestamp)
                        .order_by('-timestamp').values_list(*READING_FIELDS)[:PRIME_MAX_ROWS])
        segment = previous[:1]
        for newer, older in zip(previous, previous[1:]):
            if (newer[0] - older[0]).total_seconds() > MAX_GAP_SECONDS:
                break
            segment.append(older)
        segment.reverse()
        for i, values in enumerate(segment):
            self.scorer.process(to_reading(values), score=i >= len(segment) - ALERT_SECONDS)

        open_row = (AlertEpisode.objects.filter(mode=LIVE, equipment_id=self.equipment_id, ended_at__isnull=True)
                    .order_by('-started_at').first())
        self.scorer.episode = None
        if open_row is not None and self.scorer.rule.active:
            episode = Episode(started_at=open_row.started_at, run_label=open_row.run_label,
                              peak_score=open_row.peak_score)
            self.scorer.episode = episode
            self.writer.adopt(episode, open_row)
        elif open_row is not None:
            open_row.ended_at = last.timestamp
            open_row.save(update_fields=['ended_at'])
        return len(segment)

    def poll(self):
        """Score all new rows (up to POLL_BATCH). Returns the number of rows processed."""
        rows = self._rows()
        if self.last_timestamp is not None:
            rows = rows.filter(timestamp__gt=self.last_timestamp)
        rows = list(rows.order_by('timestamp').values_list(*READING_FIELDS)[:POLL_BATCH])

        results = [self.scorer.process(to_reading(values)) for values in rows]
        if results:
            with transaction.atomic():
                self.writer.write(results)
            self.last_timestamp = results[-1].timestamp

        ScorerHeartbeat.objects.update_or_create(
            equipment_id=self.equipment_id,
            defaults={'last_poll_at': timezone.now(), 'last_scored_reading_at': self.last_timestamp},
        )
        return len(results)


def ensure_equipment(equipment_id):
    if not Equipment.objects.filter(equipment_id=equipment_id).exists():
        raise ValueError(f'unknown equipment {equipment_id!r}')
