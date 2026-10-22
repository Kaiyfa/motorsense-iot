"""
Plain-language names of the recorded sessions that can be replayed in the
dashboard. The sessions and their roles come from dashboard.ml.dataset.
"""
from dashboard.ml import dataset

_NAMES = {
    'r5_normal_01': 'Normal: training session 1',
    'r5_normal_02': 'Normal: training session 2',
    'r5_normal_03': 'Normal: training session 3',
    'r5_normal_04_redo': 'Normal: validation session (sets the threshold)',
    'r5_normal_05': 'Normal: test session',
    'r5_fault_open_01': 'Fault: one motor disconnected, session 1',
    'r5_fault_open_02': 'Fault: one motor disconnected, session 2',
    'r5_fault_open_03': 'Fault: one motor disconnected, session 3',
}

ROLE_NAMES = {
    dataset.TRAIN: 'Training',
    dataset.VALIDATION: 'Validation',
    dataset.TEST_NORMAL: 'Test, normal',
    dataset.TEST_FAULT: 'Test, fault',
}

# Fault sessions first, then the normal test, validation and training sessions
ORDER = (dataset.TEST_FAULT, dataset.TEST_NORMAL, dataset.VALIDATION, dataset.TRAIN)

REPLAY_SESSIONS = [
    {'label': label, 'name': _NAMES[label], 'role': role, 'role_name': ROLE_NAMES[role]}
    for role in ORDER for label in dataset.ROLE_LABELS[role]
]


def session_name(label):
    return _NAMES.get(label, label)
