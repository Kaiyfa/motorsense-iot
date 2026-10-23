"""
Train and evaluate every detector as fixed in docs/evaluation_plan.md.

    python -m dashboard.ml.run_evaluation [--data data/dataset] [--results results]
                                          [--models models/motorsense_ae]

Writes results/metrics.json, results/scores/<session>.csv and, for the
three-feature autoencoder with seed 0, the model, scaler and threshold in
models/motorsense_ae/. No setting here may change after results are seen.
"""
import argparse
import csv
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import numpy as np

from dashboard.ml import dataset
from dashboard.ml import evaluation as ev

# Fixed settings (plan, "Implementation details")
SEEDS = [0, 1, 2, 3, 4]
EPOCHS = 50
BATCH_SIZE = 32
LEARNING_RATE = 0.001
UNITS = 32

AUTOENCODERS = {
    'ae_all': ['vib_rms_g', 'vib_peak_g', 'current'],
    'ae_vibration': ['vib_rms_g', 'vib_peak_g'],
    'ae_current': ['current'],
}
BASELINES = {
    'z_current': 'current',
    'z_vib_rms': 'vib_rms_g',
}
METHOD_NAMES = {
    'ae_all': 'Autoencoder, all features',
    'ae_vibration': 'Autoencoder, vibration only',
    'ae_current': 'Autoencoder, current only',
    'z_current': '|z| of current',
    'z_vib_rms': '|z| of vib_rms_g',
}
PACKAGES = ['tensorflow-macos', 'tensorflow-metal', 'tensorflow', 'keras', 'numpy', 'h5py']

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- environment

def git_state():
    def git(*args):
        return subprocess.run(['git', *args], cwd=REPO, capture_output=True, text=True, check=True).stdout
    try:
        status = git('status', '--porcelain').splitlines()
        return {'commit': git('rev-parse', 'HEAD').strip(), 'clean': not status, 'status': status}
    except (OSError, subprocess.CalledProcessError) as e:
        return {'commit': None, 'clean': None, 'status': [f'git unavailable: {e}']}


def keras_package_version():
    import keras as keras_package  # tensorflow.keras has no __version__ in TF 2.13
    return keras_package.__version__


def environment(tf, keras):
    installed = {}
    for name in PACKAGES:
        try:
            installed[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed[name] = None
    return {
        'python': platform.python_version(),
        'platform': platform.platform(),
        'machine': platform.machine(),
        'imported': {
            'tensorflow': tf.__version__,
            'keras': keras_package_version(),
            'numpy': np.__version__,
        },
        'installed_distributions': installed,
        'note': ('The venv lists both tensorflow-macos and tensorflow; the version under '
                 '"imported" is the one actually used.'),
        'devices_used': 'CPU only (GPU hidden with tf.config.set_visible_devices)',
    }


# --------------------------------------------------------------------------- models

def import_tensorflow():
    import tensorflow as tf
    tf.config.set_visible_devices([], 'GPU')  # CPU only, for reproducible seeds
    from tensorflow import keras
    return tf, keras


def build_autoencoder(keras, n_features):
    model = keras.Sequential([
        keras.layers.LSTM(UNITS, input_shape=(ev.SEQUENCE_LENGTH, n_features)),
        keras.layers.RepeatVector(ev.SEQUENCE_LENGTH),
        keras.layers.LSTM(UNITS, return_sequences=True),
        keras.layers.TimeDistributed(keras.layers.Dense(n_features)),
    ])
    model.compile(optimizer=keras.optimizers.Adam(learning_rate=LEARNING_RATE), loss='mse')
    return model


def train_and_score(keras, sessions, scaler, features, seed):
    keras.utils.set_random_seed(seed)
    standardised = {label: ev.standardise(s, features, scaler) for label, s in sessions.items()}
    train_x = ev.sequences_for_sessions(
        [standardised[label] for label in dataset.TRAIN_LABELS]
    ).astype('float32')

    model = build_autoencoder(keras, len(features))
    started = time.time()
    history = model.fit(train_x, train_x, batch_size=BATCH_SIZE, epochs=EPOCHS,
                        shuffle=True, verbose=0)
    train_seconds = time.time() - started

    scores = {}
    for label, values in standardised.items():
        seqs = ev.build_sequences(values).astype('float32')
        reconstruction = model.predict(seqs, batch_size=256, verbose=0)
        sequence_scores = ev.reconstruction_scores(seqs, reconstruction)
        scores[label] = ev.causal_scores(sequence_scores, len(values))

    info = {
        'train_sequences': int(len(train_x)),
        'final_train_loss': float(history.history['loss'][-1]),
        'first_train_loss': float(history.history['loss'][0]),
        'train_seconds': round(train_seconds, 1),
    }
    return model, scores, info


# --------------------------------------------------------------------------- evaluation

def evaluate(sessions, scores):
    """Apply threshold, alert rule and metrics to one method's scores (one seed)."""
    validation = dataset.VALIDATION_LABELS[0]
    threshold = ev.percentile_threshold(scores[validation])

    test_labels = list(dataset.TEST_NORMAL_LABELS) + list(dataset.TEST_FAULT_LABELS)
    truth = {label: (ev.FAULT if sessions[label]['role'] == dataset.TEST_FAULT else ev.NORMAL)
             for label in test_labels}

    per_second = ev.per_second_counts([(truth[l], scores[l]) for l in test_labels], threshold)
    session_results = {label: ev.session_alerts(scores[label], threshold) for label in test_labels}
    per_session = ev.per_session_counts([(truth[l], session_results[l]) for l in test_labels])

    fault_delays = [session_results[l]['delay_seconds'] for l in dataset.TEST_FAULT_LABELS]
    detected = [d for d in fault_delays if d is not None]
    normal = dataset.TEST_NORMAL_LABELS[0]

    return {
        'threshold': threshold,
        'validation_episodes': ev.session_alerts(scores[validation], threshold)['episodes'],
        'per_second': per_second,
        'per_session': per_session,
        'sessions': session_results,
        'summary': {
            'normal_test_episodes': session_results[normal]['episodes'],
            'fault_sessions_alerted': len(detected),
            'mean_delay_alerted_faults': float(np.mean(detected)) if detected else None,
        },
    }


SUMMARY_KEYS = [
    ('threshold', lambda r: r['threshold']),
    ('validation_episodes', lambda r: r['validation_episodes']),
    ('per_second.tp', lambda r: r['per_second']['tp']),
    ('per_second.fp', lambda r: r['per_second']['fp']),
    ('per_second.fn', lambda r: r['per_second']['fn']),
    ('per_second.tn', lambda r: r['per_second']['tn']),
    ('per_second.precision', lambda r: r['per_second']['precision']),
    ('per_second.recall', lambda r: r['per_second']['recall']),
    ('per_second.false_positive_rate', lambda r: r['per_second']['false_positive_rate']),
    ('per_session.tp', lambda r: r['per_session']['tp']),
    ('per_session.fp', lambda r: r['per_session']['fp']),
    ('per_session.fn', lambda r: r['per_session']['fn']),
    ('per_session.tn', lambda r: r['per_session']['tn']),
    ('per_session.precision', lambda r: r['per_session']['precision']),
    ('per_session.recall', lambda r: r['per_session']['recall']),
    ('normal_test_episodes', lambda r: r['summary']['normal_test_episodes']),
    ('fault_sessions_alerted', lambda r: r['summary']['fault_sessions_alerted']),
    ('mean_delay_alerted_faults', lambda r: r['summary']['mean_delay_alerted_faults']),
]


def sanity_checks(method, seed, scores, result):
    """Report problems; nothing here changes any result."""
    problems = []
    for label, s in scores.items():
        scored = s[~np.isnan(s)]
        if len(scored) != len(s) - (ev.SEQUENCE_LENGTH - 1):
            problems.append(f'{method} seed {seed}: {label} has NaN among scored seconds')
        elif len(scored) and np.ptp(scored) == 0:
            problems.append(f'{method} seed {seed}: {label} scores are constant ({scored[0]})')
    ps = result['per_second']
    if ps['tp'] + ps['fp'] == 0:
        problems.append(f'{method} seed {seed}: no test second scored above the threshold')
    return problems


# --------------------------------------------------------------------------- output

def write_scores(scores_dir, sessions, all_scores):
    scores_dir.mkdir(parents=True, exist_ok=True)
    columns = [(method, seed) for method, per_seed in all_scores.items() for seed in per_seed]
    for label, session in sessions.items():
        with (scores_dir / f'{label}.csv').open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'run_label', 'role'] + dataset.FEATURES +
                            [f'{m}_seed{s}' if s is not None else m for m, s in columns])
            for i, ts in enumerate(session['timestamps']):
                values = [all_scores[m][s][label][i] for m, s in columns]
                writer.writerow([ts, label, session['role']] +
                                [session['features'][f][i] for f in dataset.FEATURES] +
                                ['' if np.isnan(v) else f'{v:.6g}' for v in values])


def save_seed0_model(models_dir, model, scaler, features, result, git):
    models_dir.mkdir(parents=True, exist_ok=True)
    model.save(models_dir / 'model.keras')
    with (models_dir / 'scaler.json').open('w') as f:
        json.dump({'features': features, 'mean': [scaler[n]['mean'] for n in features],
                   'std': [scaler[n]['std'] for n in features], 'std_ddof': 0}, f, indent=2)
    with (models_dir / 'threshold.json').open('w') as f:
        json.dump({'threshold': result['threshold'], 'percentile': ev.THRESHOLD_PERCENTILE,
                   'set_on': dataset.VALIDATION_LABELS[0], 'sequence_length': ev.SEQUENCE_LENGTH,
                   'alert_seconds': ev.ALERT_SECONDS, 'seed': 0, 'features': features,
                   'git_commit': git['commit']}, f, indent=2)


def fmt(value, digits=3):
    if value is None:
        return 'n/a'
    if float(value).is_integer():
        return f'{value:g}'
    return f'{value:.{digits}f}'


def cell(summary, key, digits=3):
    s = summary[key]
    if s['mean'] is None:
        return 'n/a', ''
    if s['n'] == 1 or s['std'] is None:
        return fmt(s['mean'], digits), ''
    return (f"{s['mean']:.{digits}f}±{s['std']:.{digits}f}",
            f"{s['min']:.{digits}f}–{s['max']:.{digits}f}")


def print_table(methods):
    cols = [
        ('threshold', 'thr', 3), ('validation_episodes', 'val ep', 1),
        ('per_second.tp', 'TP', 1), ('per_second.fp', 'FP', 1),
        ('per_second.fn', 'FN', 1), ('per_second.tn', 'TN', 1),
        ('per_second.precision', 'prec', 3), ('per_second.recall', 'recall', 3),
        ('per_second.false_positive_rate', 'FPR', 3),
        ('normal_test_episodes', 'normal ep', 1), ('fault_sessions_alerted', 'faults alerted', 1),
        ('mean_delay_alerted_faults', 'delay s', 1),
        ('per_session.precision', 'sess prec', 3), ('per_session.recall', 'sess rec', 3),
    ]
    rows = []
    for method, data in methods.items():
        mean_row, range_row = [METHOD_NAMES[method]], [f'  (min–max over {len(SEEDS)} seeds)']
        for key, _, digits in cols:
            m, r = cell(data['summary'], key, digits)
            mean_row.append(m)
            range_row.append(r)
        rows.append(mean_row)
        if any(range_row[1:]):
            rows.append(range_row)
    header = ['Method'] + [title for _, title, _ in cols]
    widths = [max(len(str(r[i])) for r in rows + [header]) for i in range(len(header))]
    line = '  '.join(h.ljust(widths[0]) if i == 0 else h.rjust(widths[i]) for i, h in enumerate(header))
    print(line)
    print('-' * len(line))
    for r in rows:
        print('  '.join(str(v).ljust(widths[0]) if i == 0 else str(v).rjust(widths[i]) for i, v in enumerate(r)))
    print(f'\nPer-second columns (TP .. FPR) are on the 4 test sessions, scored seconds only. '
          f'Autoencoder rows: mean ± sample std over seeds {SEEDS[0]}–{SEEDS[-1]}, next line min–max. '
          '"val ep": alert episodes on the validation session; "normal ep": episodes on r5_normal_05; '
          '"faults alerted": fault sessions (of 3) with at least one alert; '
          '"delay s": mean delay over alerted fault sessions, from the first scored second.')


# --------------------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data', default='data/dataset')
    parser.add_argument('--results', default='results')
    parser.add_argument('--models', default='models/motorsense_ae')
    args = parser.parse_args(argv)

    git = git_state()
    tf, keras = import_tensorflow()
    sessions = ev.load_sessions(args.data)
    scaler = ev.fit_scaler(sessions, dataset.FEATURES)

    all_scores, methods, problems = {}, {}, []

    for method, features in AUTOENCODERS.items():
        all_scores[method], per_seed, training = {}, {}, {}
        for seed in SEEDS:
            print(f'Training {method} seed {seed} ...', flush=True)
            model, scores, info = train_and_score(keras, sessions, scaler, features, seed)
            result = evaluate(sessions, scores)
            problems += sanity_checks(method, seed, scores, result)
            all_scores[method][seed] = scores
            per_seed[seed] = result
            training[seed] = info
            print(f"  loss {info['first_train_loss']:.4f} -> {info['final_train_loss']:.4f} "
                  f"in {info['train_seconds']} s, threshold {result['threshold']:.4f}", flush=True)
            if method == 'ae_all' and seed == 0:
                save_seed0_model(Path(args.models), model, scaler, features, result, git)
        methods[method] = {
            'inputs': features, 'seeds': per_seed, 'training': training,
            'summary': {key: ev.summarize_across_seeds([get(per_seed[s]) for s in SEEDS])
                        for key, get in SUMMARY_KEYS},
        }

    for method, feature in BASELINES.items():
        scores = {label: ev.zscore_scores(s, feature, scaler) for label, s in sessions.items()}
        result = evaluate(sessions, scores)
        problems += sanity_checks(method, 'n/a', scores, result)
        all_scores[method] = {None: scores}
        methods[method] = {
            'inputs': [feature], 'deterministic': result,
            'summary': {key: ev.summarize_across_seeds([get(result)]) for key, get in SUMMARY_KEYS},
        }

    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)
    write_scores(results_dir / 'scores', sessions, all_scores)

    metrics = {
        'plan': 'docs/evaluation_plan.md',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'git': git,
        'environment': environment(tf, keras),
        'settings': {
            'sequence_length': ev.SEQUENCE_LENGTH, 'stride': 1,
            'unscored_seconds_per_session': ev.SEQUENCE_LENGTH - 1,
            'threshold_percentile': ev.THRESHOLD_PERCENTILE, 'threshold_set_on': dataset.VALIDATION_LABELS[0],
            'alert_seconds': ev.ALERT_SECONDS, 'epochs': EPOCHS, 'batch_size': BATCH_SIZE,
            'learning_rate': LEARNING_RATE, 'lstm_units': UNITS, 'seeds': SEEDS,
            'scaler': scaler, 'scaler_std_ddof': 0, 'seed_summary_std_ddof': 1,
            'sessions': {label: {'role': s['role'], 'rows': len(s['timestamps']),
                                 'scored_seconds': len(s['timestamps']) - (ev.SEQUENCE_LENGTH - 1)}
                         for label, s in sessions.items()},
        },
        'methods': methods,
        'sanity_problems': problems,
    }
    with (results_dir / 'metrics.json').open('w') as f:
        json.dump(metrics, f, indent=2)

    print()
    print_table(methods)
    print(f"\nGit commit {git['commit']} ({'clean' if git['clean'] else 'DIRTY'} working tree)")
    if problems:
        print('\nSANITY PROBLEMS (reported, nothing changed):')
        for p in problems:
            print(f'  - {p}')
    else:
        print('Sanity checks: no NaN among scored seconds, no constant scores, '
              'every method has test seconds above its threshold.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
