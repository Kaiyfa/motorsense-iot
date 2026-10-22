"""
Evaluation logic for the anomaly pipeline, as fixed in docs/evaluation_plan.md
("Implementation details").

numpy only: no TensorFlow and no database access, so every function here can be
unit tested on small synthetic data.
"""
import csv
import math
from pathlib import Path

import numpy as np

from dashboard.ml import dataset

SEQUENCE_LENGTH = 30
THRESHOLD_PERCENTILE = 99.5
ALERT_SECONDS = 10

NORMAL = 'normal'
FAULT = 'fault'


# --------------------------------------------------------------------------- data

def load_sessions(data_dir):
    """
    Read the CSVs written by export_dataset.

    Returns {label: {'role', 'timestamps', 'features': {name: np.ndarray}}}
    for every session in the plan, in plan order.
    """
    data_dir = Path(data_dir)
    sessions = {}
    for role in dataset.ROLES:
        path = data_dir / f'{role}.csv'
        if not path.exists():
            raise FileNotFoundError(f'{path} not found; run `python manage.py export_dataset` first')
        rows = {}
        with path.open(newline='') as f:
            for row in csv.DictReader(f):
                rows.setdefault(row['run_label'], []).append(row)
        for label in dataset.ROLE_LABELS[role]:
            if label not in rows:
                raise ValueError(f'session {label!r} ({role}) is missing from {path}')
            session_rows = rows[label]
            if dataset.role_for_label(label) != role:
                raise ValueError(f'{label!r} found in {path.name} but its role is {dataset.role_for_label(label)!r}')
            sessions[label] = {
                'role': role,
                'timestamps': [r['timestamp'] for r in session_rows],
                'features': {
                    name: np.array([float(r[name]) for r in session_rows], dtype=float)
                    for name in dataset.FEATURES
                },
            }
    return sessions


def fit_scaler(sessions, features):
    """Mean and population std of each feature over all rows of the training sessions pooled."""
    train = [s for s in sessions.values() if s['role'] == dataset.TRAIN]
    if not train:
        raise ValueError('no training sessions')
    scaler = {}
    for name in features:
        values = np.concatenate([s['features'][name] for s in train])
        std = float(np.std(values))  # ddof=0
        if std == 0 or not math.isfinite(std):
            raise ValueError(f'training standard deviation of {name} is {std}')
        scaler[name] = {'mean': float(np.mean(values)), 'std': std}
    return scaler


def standardise(session, features, scaler):
    """(n_seconds, n_features) array of standardised features for one session."""
    return np.stack(
        [(session['features'][name] - scaler[name]['mean']) / scaler[name]['std'] for name in features],
        axis=1,
    )


def build_sequences(values, length=SEQUENCE_LENGTH):
    """
    Sliding windows of `length` consecutive rows, stride 1, from ONE session.

    values: (n, n_features). Returns (n - length + 1, length, n_features); the
    sequence at index i ends at row i + length - 1. Call once per session, so a
    sequence never crosses a session boundary.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < length:
        return np.empty((0, length, values.shape[1]))
    return np.stack([values[i:i + length] for i in range(n - length + 1)])


def sequences_for_sessions(arrays, length=SEQUENCE_LENGTH):
    """Concatenate per-session sequences; each session is windowed on its own."""
    parts = [build_sequences(a, length) for a in arrays]
    return np.concatenate(parts) if parts else np.empty((0, length, 0))


def causal_scores(sequence_scores, n_seconds, length=SEQUENCE_LENGTH):
    """
    Map sequence scores to seconds: second t gets the score of the sequence
    ending at t. The first length - 1 seconds get NaN (unscored).
    """
    sequence_scores = np.asarray(sequence_scores, dtype=float)
    if len(sequence_scores) != max(n_seconds - length + 1, 0):
        raise ValueError('number of sequence scores does not match the session length')
    scores = np.full(n_seconds, np.nan)
    scores[length - 1:] = sequence_scores
    return scores


def zscore_scores(session, feature, scaler, length=SEQUENCE_LENGTH):
    """Baseline score |x - mean| / std; the first length - 1 seconds are left unscored."""
    x = session['features'][feature]
    scores = np.abs(x - scaler[feature]['mean']) / scaler[feature]['std']
    scores = scores.astype(float)
    scores[:length - 1] = np.nan
    return scores


# --------------------------------------------------------------------------- rules

def percentile_threshold(scores, percentile=THRESHOLD_PERCENTILE):
    """Percentile (numpy linear interpolation) of the scored seconds."""
    scores = np.asarray(scores, dtype=float)
    scored = scores[~np.isnan(scores)]
    if len(scored) == 0:
        raise ValueError('no scored seconds to set a threshold on')
    return float(np.percentile(scored, percentile))


def above_threshold(scores, threshold):
    """True where the score is strictly above the threshold; unscored seconds are False."""
    scores = np.asarray(scores, dtype=float)
    with np.errstate(invalid='ignore'):
        return np.where(np.isnan(scores), False, scores > threshold)


def alert_state(above, run_length=ALERT_SECONDS):
    """
    Apply the alert rule to a boolean array.

    The alert fires on the run_length-th consecutive second above the threshold
    and stays on while the score stays above it. Returns (alert_on, episode_starts)
    where episode_starts are the indices at which an alert fired.
    """
    above = np.asarray(above, dtype=bool)
    alert_on = np.zeros(len(above), dtype=bool)
    starts = []
    run = 0
    for i, is_above in enumerate(above):
        run = run + 1 if is_above else 0
        if run >= run_length:
            alert_on[i] = True
            if run == run_length:
                starts.append(i)
    return alert_on, starts


# --------------------------------------------------------------------------- metrics

def _ratio(num, den):
    return num / den if den else None


def per_second_counts(sessions_scores, threshold):
    """
    sessions_scores: list of (truth, scores) with truth NORMAL or FAULT for every
    second of the session. Unscored (NaN) seconds are not counted.
    """
    tp = fp = fn = tn = 0
    for truth, scores in sessions_scores:
        scores = np.asarray(scores, dtype=float)
        scored = ~np.isnan(scores)
        predicted = above_threshold(scores, threshold)[scored]
        positives = int(predicted.sum())
        negatives = int(len(predicted) - positives)
        if truth == FAULT:
            tp += positives
            fn += negatives
        elif truth == NORMAL:
            fp += positives
            tn += negatives
        else:
            raise ValueError(f'unknown truth {truth!r}')
    return {
        'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'precision': _ratio(tp, tp + fp),
        'recall': _ratio(tp, tp + fn),
        'false_positive_rate': _ratio(fp, fp + tn),
    }


def session_alerts(scores, threshold, run_length=ALERT_SECONDS):
    """
    Alert summary for one session: whether an alert fired, the number of
    episodes, and the delay from the first scored second to the first alert
    (in rows, i.e. seconds at 1 Hz).
    """
    scores = np.asarray(scores, dtype=float)
    scored_idx = np.flatnonzero(~np.isnan(scores))
    if len(scored_idx) == 0:
        return {'scored_seconds': 0, 'alert': False, 'episodes': 0, 'delay_seconds': None}
    first_scored = int(scored_idx[0])
    _, starts = alert_state(above_threshold(scores, threshold), run_length)
    return {
        'scored_seconds': int(len(scored_idx)),
        'alert': bool(starts),
        'episodes': len(starts),
        'delay_seconds': (starts[0] - first_scored) if starts else None,
    }


def per_session_counts(session_results):
    """session_results: list of (truth, session_alerts dict). Predicted fault = any alert."""
    tp = fp = fn = tn = 0
    for truth, result in session_results:
        if truth == FAULT:
            tp += result['alert']
            fn += not result['alert']
        else:
            fp += result['alert']
            tn += not result['alert']
    return {
        'tp': int(tp), 'fp': int(fp), 'fn': int(fn), 'tn': int(tn),
        'precision': _ratio(tp, tp + fp),
        'recall': _ratio(tp, tp + fn),
    }


def summarize_across_seeds(values):
    """Mean, sample std (n - 1), min and max of a list of numbers; None entries are ignored."""
    present = [float(v) for v in values if v is not None]
    if not present:
        return {'mean': None, 'std': None, 'min': None, 'max': None, 'n': 0}
    return {
        'mean': float(np.mean(present)),
        'std': float(np.std(present, ddof=1)) if len(present) > 1 else None,
        'min': float(min(present)),
        'max': float(max(present)),
        'n': len(present),
    }
