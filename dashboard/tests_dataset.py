"""
Unit tests for dashboard/ml/dataset.py. No database needed: these use plain
unittest.TestCase and can also run with `python -m unittest dashboard.tests_dataset`.
"""
import unittest

from dashboard.ml import dataset
from dashboard.ml.dataset import (
    EXCLUDED, TEST_FAULT, TEST_NORMAL, TRAIN, VALIDATION,
    PlanError, exclusion_reason, is_live_source, plan_labels, role_for_label, validate_plan,
)


class RoleForLabelTests(unittest.TestCase):
    def test_every_plan_label_maps_to_its_role(self):
        expected = {
            'r5_normal_01': TRAIN,
            'r5_normal_02': TRAIN,
            'r5_normal_03': TRAIN,
            'r5_normal_04_redo': VALIDATION,
            'r5_normal_05': TEST_NORMAL,
            'r5_fault_open_01': TEST_FAULT,
            'r5_fault_open_02': TEST_FAULT,
            'r5_fault_open_03': TEST_FAULT,
        }
        for label, role in expected.items():
            with self.subTest(label=label):
                self.assertEqual(role_for_label(label), role)
        self.assertEqual(sorted(plan_labels()), sorted(expected))

    def test_excluded_labels_are_excluded(self):
        for label in ('r5_check', 'r5_normal_04'):
            with self.subTest(label=label):
                self.assertEqual(role_for_label(label), EXCLUDED)
                self.assertEqual(exclusion_reason(label), 'excluded in the plan')

    def test_warmup_labels_are_excluded(self):
        warmups = [f'{label}_warmup' for label in plan_labels()] + [
            'r5_normal_04_warmup', 'r5_normal_04_redo_warmup', 'anything_warmup',
        ]
        for label in warmups:
            with self.subTest(label=label):
                self.assertEqual(role_for_label(label), EXCLUDED)
                self.assertEqual(exclusion_reason(label), 'warm-up segment')

    def test_unknown_labels_are_excluded(self):
        unknown = [
            '', None, 'r5_normal_06', 'r5_fault_open_04', 'r5_normal_01 ', 'R5_NORMAL_01',
            'r2_normal_01', 'r3_normal_01', 'normal_01', 'warmup_01', 'r2_check',
            'r2_fault_imbalance_01', 'curl_test', 'r5_normal_04_redo_2',
        ]
        for label in unknown:
            with self.subTest(label=label):
                self.assertEqual(role_for_label(label), EXCLUDED)
        self.assertEqual(exclusion_reason('r5_normal_06'), 'not in the plan')

    def test_fault_labels_never_map_to_train_or_validation(self):
        for label in dataset.TEST_FAULT_LABELS:
            with self.subTest(label=label):
                self.assertNotIn(role_for_label(label), (TRAIN, VALIDATION))
        for label in dataset.TRAIN_LABELS + dataset.VALIDATION_LABELS:
            with self.subTest(label=label):
                self.assertNotIn('fault', label)

    def test_features_constant(self):
        self.assertEqual(dataset.FEATURES, ['vib_rms_g', 'vib_peak_g', 'current'])
        self.assertNotIn('bus_v', dataset.FEATURES)
        self.assertNotIn('temperature', dataset.FEATURES)

    def test_only_live_source_is_used(self):
        self.assertTrue(is_live_source('pi'))
        self.assertFalse(is_live_source('sample'))
        self.assertFalse(is_live_source(''))


class ValidatePlanTests(unittest.TestCase):
    def test_real_plan_is_valid(self):
        validate_plan()

    def test_label_in_two_roles_is_rejected(self):
        roles = {TRAIN: ('a',), VALIDATION: ('b',), TEST_NORMAL: ('a',), TEST_FAULT: ()}
        with self.assertRaises(PlanError):
            validate_plan(roles, excluded_labels=(), fault_labels=())
        with self.assertRaises(PlanError):
            role_for_label('a', roles, excluded_labels=())

    def test_label_both_in_role_and_excluded_is_rejected(self):
        roles = {TRAIN: ('a',), VALIDATION: (), TEST_NORMAL: (), TEST_FAULT: ()}
        with self.assertRaises(PlanError):
            validate_plan(roles, excluded_labels=('a',), fault_labels=())

    def test_warmup_label_in_a_role_is_rejected(self):
        roles = {TRAIN: ('a_warmup',), VALIDATION: (), TEST_NORMAL: (), TEST_FAULT: ()}
        with self.assertRaises(PlanError):
            validate_plan(roles, excluded_labels=(), fault_labels=())

    def test_fault_session_in_train_or_validation_is_rejected(self):
        for role in (TRAIN, VALIDATION):
            with self.subTest(role=role):
                roles = {TRAIN: (), VALIDATION: (), TEST_NORMAL: (), TEST_FAULT: ('f',)}
                roles[role] = ('f',)
                with self.assertRaises(PlanError):
                    validate_plan(roles, excluded_labels=(), fault_labels=('f',))
                roles = {TRAIN: (), VALIDATION: (), TEST_NORMAL: (), TEST_FAULT: ()}
                roles[role] = ('r9_fault_x',)
                with self.assertRaises(PlanError):
                    validate_plan(roles, excluded_labels=(), fault_labels=())


if __name__ == '__main__':
    unittest.main()
