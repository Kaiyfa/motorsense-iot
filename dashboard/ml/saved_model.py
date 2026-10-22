"""
Load the saved three-feature autoencoder (seed 0) written by run_evaluation.

TensorFlow is imported only when load() is called, and only by the scorer
processes (score_live, replay_session), never by the web server.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dashboard.ml import dataset
from dashboard.ml.constants import ALERT_SECONDS, SEQUENCE_LENGTH

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / 'ml_models' / 'motorsense_ae'


@dataclass
class SavedDetector:
    reconstruct: Callable
    scaler: dict
    threshold: float
    features: list
    meta: dict


def read_metadata(model_dir=DEFAULT_MODEL_DIR):
    """Scaler and threshold files, checked against the shared constants."""
    model_dir = Path(model_dir)
    with (model_dir / 'scaler.json').open() as f:
        scaler_file = json.load(f)
    with (model_dir / 'threshold.json').open() as f:
        meta = json.load(f)

    problems = []
    if meta.get('sequence_length') != SEQUENCE_LENGTH:
        problems.append(f"sequence_length {meta.get('sequence_length')} != {SEQUENCE_LENGTH}")
    if meta.get('alert_seconds') != ALERT_SECONDS:
        problems.append(f"alert_seconds {meta.get('alert_seconds')} != {ALERT_SECONDS}")
    if meta.get('features') != dataset.FEATURES or scaler_file.get('features') != dataset.FEATURES:
        problems.append(f'features differ from {dataset.FEATURES}')
    if problems:
        raise ValueError(f'saved model in {model_dir} does not match the fixed settings: ' + '; '.join(problems))

    scaler = {name: {'mean': m, 'std': s}
              for name, m, s in zip(scaler_file['features'], scaler_file['mean'], scaler_file['std'])}
    return scaler, float(meta['threshold']), meta


def load(model_dir=DEFAULT_MODEL_DIR):
    from dashboard.ml.run_evaluation import import_tensorflow  # CPU only, as in training

    scaler, threshold, meta = read_metadata(model_dir)
    _, keras = import_tensorflow()
    model = keras.models.load_model(Path(model_dir) / 'model.keras')

    def reconstruct(sequences):
        return model.predict(sequences, verbose=0)

    return SavedDetector(reconstruct=reconstruct, scaler=scaler, threshold=threshold,
                         features=list(dataset.FEATURES), meta=meta)
