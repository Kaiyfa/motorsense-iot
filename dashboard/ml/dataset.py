"""
Session roles for the anomaly pipeline, as fixed in docs/evaluation_plan.md.

Pure functions only: no database or Django access, so this module can be
imported and tested on its own.
"""

# Model inputs (column names in the exported CSVs)
FEATURES = ["vib_rms_g", "vib_peak_g", "current"]

# Exported for plotting only, never model inputs
PLOT_ONLY = ["bus_v", "temperature"]

# Column name used here -> field of dashboard.models.SensorData
SENSORDATA_FIELDS = {
    "vib_rms_g": "vibration_rms",
    "vib_peak_g": "vibration_peak",
    "current": "current",          # amperes
    "bus_v": "bus_voltage",
    "temperature": "temperature",
}

# Roles
TRAIN = "train"
VALIDATION = "validation"
TEST_NORMAL = "test_normal"
TEST_FAULT = "test_fault"
EXCLUDED = "excluded"

ROLES = (TRAIN, VALIDATION, TEST_NORMAL, TEST_FAULT)

# Explicit session lists from the plan
TRAIN_LABELS = ("r5_normal_01", "r5_normal_02", "r5_normal_03")
VALIDATION_LABELS = ("r5_normal_04_redo",)
TEST_NORMAL_LABELS = ("r5_normal_05",)
TEST_FAULT_LABELS = ("r5_fault_open_01", "r5_fault_open_02", "r5_fault_open_03")

ROLE_LABELS = {
    TRAIN: TRAIN_LABELS,
    VALIDATION: VALIDATION_LABELS,
    TEST_NORMAL: TEST_NORMAL_LABELS,
    TEST_FAULT: TEST_FAULT_LABELS,
}

# Explicitly excluded sessions (r5_normal_04: invalid session, see the plan)
EXCLUDED_LABELS = ("r5_check", "r5_normal_04")

# The only pattern rule: warm-up segments (first 180 s of each session)
WARMUP_SUFFIX = "_warmup"

# The plan keeps only rows from the live testbed. The ingest endpoint
# (/api/ingest/) stores those rows with source="pi"; generated rows use "sample".
LIVE_SOURCE = "pi"


class PlanError(ValueError):
    """The session plan is inconsistent; nothing may be exported."""


def validate_plan(role_labels=None, excluded_labels=EXCLUDED_LABELS,
                  fault_labels=TEST_FAULT_LABELS):
    """
    Raise PlanError if a label would land in two roles (including the
    excluded list or the warm-up rule), or if a fault session would land in
    train or validation.
    """
    if role_labels is None:
        role_labels = ROLE_LABELS

    seen = {}
    for role, labels in role_labels.items():
        for label in labels:
            if label in seen:
                raise PlanError(f"{label!r} is listed in both {seen[label]!r} and {role!r}")
            seen[label] = role
            if label in excluded_labels:
                raise PlanError(f"{label!r} is listed in {role!r} and in the excluded list")
            if label.endswith(WARMUP_SUFFIX):
                raise PlanError(f"{label!r} is listed in {role!r} but warm-up labels are excluded")

    for role in (TRAIN, VALIDATION):
        for label in role_labels.get(role, ()):
            if label in fault_labels or "fault" in label:
                raise PlanError(f"fault session {label!r} would land in {role!r}")


def role_for_label(label, role_labels=None, excluded_labels=EXCLUDED_LABELS):
    """
    Return the role of a run_label: train, validation, test_normal,
    test_fault or excluded. Unknown labels are excluded, never guessed.
    """
    if role_labels is None:
        role_labels = ROLE_LABELS
    if not isinstance(label, str) or not label:
        return EXCLUDED
    if label.endswith(WARMUP_SUFFIX) or label in excluded_labels:
        return EXCLUDED

    matches = [role for role, labels in role_labels.items() if label in labels]
    if len(matches) > 1:
        raise PlanError(f"{label!r} would land in {len(matches)} roles: {matches}")
    return matches[0] if matches else EXCLUDED


def exclusion_reason(label, role_labels=None, excluded_labels=EXCLUDED_LABELS):
    """Why a label is excluded, or None if it has a role."""
    if role_for_label(label, role_labels, excluded_labels) != EXCLUDED:
        return None
    if isinstance(label, str) and label.endswith(WARMUP_SUFFIX):
        return "warm-up segment"
    if label in excluded_labels:
        return "excluded in the plan"
    return "not in the plan"


def is_live_source(source):
    """Only rows from the live testbed are used."""
    return source == LIVE_SOURCE


def plan_labels(role_labels=None):
    """Every session that has a role, in plan order."""
    if role_labels is None:
        role_labels = ROLE_LABELS
    return [label for role in ROLES for label in role_labels.get(role, ())]
