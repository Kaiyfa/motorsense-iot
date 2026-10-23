"""The README's results table must be the output of dashboard.ml.render_readme_results."""
import json
import re
import unittest
from pathlib import Path

from dashboard.ml import render_readme_results as rr

REPO = Path(__file__).resolve().parents[1]


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.readme = (REPO / 'README.md').read_text()

    def test_results_table_matches_metrics_json(self):
        metrics = json.loads((REPO / 'results' / 'metrics.json').read_text())
        self.assertIsNotNone(rr.readme_table(self.readme), 'results table markers missing from README.md')
        self.assertEqual(rr.readme_table(self.readme), rr.render(metrics),
                         'README results table is out of date: paste the output of '
                         'python -m dashboard.ml.render_readme_results between the markers')

    def test_linked_files_exist(self):
        for target in re.findall(r'\]\(([^)#]+)\)', self.readme):
            if target.startswith('http'):
                continue
            self.assertTrue((REPO / target).exists(), target)

    def test_no_em_dash_or_accuracy_claim(self):
        self.assertNotIn('—', self.readme)
        self.assertNotRegex(self.readme.lower(), r'\d+(\.\d+)? ?% accura|remaining useful life')

    def test_render_cell(self):
        self.assertEqual(rr.cell({'mean': 2.2, 'min': 2.0, 'max': 3.0}, 1), '2.2 (2 to 3)')
        self.assertEqual(rr.cell({'mean': 9.0, 'min': 9.0, 'max': 9.0}, 1), '9')
        self.assertEqual(rr.cell({'mean': 0.21955, 'min': None, 'max': None}, 3), '0.22')
