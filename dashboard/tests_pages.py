"""Every dashboard page returns 200 for a logged-in user and redirects to the login page otherwise."""
import re
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dashboard.models import AnomalyScore, Equipment

PAGES = [
    ('dashboard:dashboard', []),
    ('dashboard:replay', []),
    ('dashboard:sensors', []),
    ('dashboard:alerts_page', []),
    ('dashboard:maintenance', []),
    ('dashboard:evaluation', []),
    ('dashboard:setup', []),
]

REMOVED_TEXT = ['86.6', '98.53', 'ccuracy', 'Powered by AI', 'RUL', 'Remaining useful', 'emaining Useful',
                'ailure probability', 'Cost', 'Saving', 'Simulated', 'SIMULATED', 'Ghawar', 'Pump']


class PageAccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', password='a-long-password')

    def test_pages_need_login(self):
        for name, args in PAGES:
            with self.subTest(page=name, args=args):
                url = reverse(name, args=args)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith(reverse('login')))

    def test_pages_return_200_when_logged_in(self):
        self.client.force_login(self.user)
        for name, args in PAGES:
            with self.subTest(page=name, args=args):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)
                # SVG path coordinates (for example 86.61) are not claims; leave them out of the text check
                html = re.sub(r' d="[^"]*"', '', response.content.decode())
                for text in REMOVED_TEXT:
                    self.assertNotIn(text, html)
                self.assertIn('EQ-001 · Bench rig, 4 DC motors', html)
                # the display time zone, named once in the header and handed to the scripts
                self.assertEqual(html.count('All times in Asia/Riyadh (UTC+3)'), 1)
                self.assertIn('data-timezone="Asia/Riyadh"', html)
                self.assertNotRegex(html, r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}')

    def test_login_page_is_public_and_clean(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for text in REMOVED_TEXT + ['googleapis', 'cdn.jsdelivr']:
            self.assertNotIn(text, html)

    def test_unknown_section_is_404(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/nope/').status_code, 404)

    def test_removed_simulated_endpoints_are_gone(self):
        self.client.force_login(self.user)
        for path in ['/api/prediction/', '/api/equipment/', '/api/live/prediction/', '/live/']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_login_redirect_rejects_other_hosts(self):
        response = self.client.post(reverse('login'), {
            'username': 'tester', 'password': 'a-long-password', 'next': 'https://evil.example/'})
        self.assertEqual(response['Location'], reverse('dashboard:dashboard'))
        self.client.logout()
        response = self.client.post(reverse('login'), {
            'username': 'tester', 'password': 'a-long-password', 'next': reverse('dashboard:replay')})
        self.assertEqual(response['Location'], reverse('dashboard:replay'))


class ModeTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('tester', password='a-long-password'))
        self.eq = Equipment.objects.create(equipment_id='EQ-001', name='Bench rig', equipment_type='MOTOR',
                                           location='Bench', installation_date=datetime(2026, 1, 1).date())

    def test_live_page_has_no_replay_banner(self):
        html = self.client.get(reverse('dashboard:dashboard')).content.decode()
        self.assertNotIn('Not live data', html)
        self.assertIn("import 'ms/live.js';", html)
        self.assertNotIn("import 'ms/replay.js';", html)

    def test_replay_page_always_shows_the_banner(self):
        html = self.client.get(reverse('dashboard:replay') + '?session=r5_fault_open_01').content.decode()
        self.assertIn('REPLAY of recorded session <span class="mono">r5_fault_open_01</span>. Not live data.', html)
        self.assertIn('has not been replayed into the database yet', html)   # nothing replayed in the test DB
        self.assertNotIn("import 'ms/live.js';", html)

    def test_replay_page_with_replayed_session(self):
        t0 = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
        AnomalyScore.objects.create(equipment=self.eq, timestamp=t0, run_label='r5_normal_05', threshold=1.0,
                                    machine_state='idle', mode='replay')
        html = self.client.get(reverse('dashboard:replay') + '?session=r5_normal_05').content.decode()
        self.assertIn('REPLAY of recorded session <span class="mono">r5_normal_05</span>. Not live data.', html)
        self.assertIn("import 'ms/replay.js';", html)
        self.assertIn('Fault: one motor disconnected, session 1 (not replayed yet)', html)

    def test_unknown_replay_session_falls_back_to_a_known_one(self):
        response = self.client.get(reverse('dashboard:replay') + '?session=../../etc')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('../../etc', response.content.decode())

    def test_data_tabs_keep_replay_mode(self):
        for name in ('dashboard:sensors', 'dashboard:alerts_page'):
            html = self.client.get(reverse(name) + '?mode=replay&session=r5_fault_open_02').content.decode()
            self.assertIn('REPLAY of recorded session <span class="mono">r5_fault_open_02</span>. Not live data.', html)

    def test_other_tabs_are_neither_live_nor_replay(self):
        for name in ('dashboard:maintenance', 'dashboard:evaluation', 'dashboard:setup'):
            html = self.client.get(reverse(name) + '?mode=replay&session=r5_fault_open_02').content.decode()
            self.assertIn('data-mode="none"', html)
            self.assertNotIn('Not live data', html)


class UnitTextTests(TestCase):
    """Units keep their case: the tiles render V, A, g and °C exactly, and no CSS changes the case."""

    def setUp(self):
        self.client.force_login(User.objects.create_user('tester', password='a-long-password'))

    def test_tile_units_render_with_their_case(self):
        import re
        html = self.client.get(reverse('dashboard:dashboard')).content.decode()
        tiles = re.findall(r'<h3 class="tile-name" id="tile-(\w+)">([^<]+)</h3>.*?<span class="tile-unit">([^<]+)</span>',
                           html, flags=re.S)
        self.assertEqual([(key, unit) for key, _, unit in tiles], [
            ('vibration_rms', 'g'), ('vibration_peak', 'g'), ('current', 'A'),
            ('bus_voltage', 'V'), ('temperature', '°C')])
        self.assertIn('"unit": "V"', html)   # the page config used for the tile range lines

    def test_no_css_rule_changes_the_case_of_units(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parent / 'static/dashboard/css/app.css').read_text()
        self.assertNotIn('lowercase', css)
        self.assertNotIn('capitalize', css)
        self.assertNotIn('small-caps', css)
        block = css[css.index('.tile-unit {'):]
        block = block[:block.index('}')]
        self.assertIn('text-transform: none', block)


class StaticVersionTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('tester', password='a-long-password'))

    def test_assets_and_modules_carry_a_content_version(self):
        import hashlib
        import json
        import re
        from django.contrib.staticfiles import finders
        from dashboard.templatetags.versioned_static import JS_MODULES

        html = self.client.get(reverse('dashboard:dashboard')).content.decode()
        importmap = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, flags=re.S).group(1))
        self.assertEqual(set(importmap['imports']), set(JS_MODULES))
        for spec, path in JS_MODULES.items():
            digest = hashlib.sha256(open(finders.find(path), 'rb').read()).hexdigest()[:12]
            self.assertEqual(importmap['imports'][spec], f'/static/{path}?v={digest}')
        self.assertRegex(html, r'/static/dashboard/css/app\.css\?v=[0-9a-f]{12}')
        self.assertRegex(html, r'/static/dashboard/vendor/chartjs-4\.4\.0/chart\.umd\.js\?v=[0-9a-f]{12}')

    def test_version_changes_when_the_file_changes(self):
        import os
        import tempfile
        from django.test import override_settings
        from dashboard.templatetags.versioned_static import file_version

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'probe.js')
            with open(path, 'w') as f:
                f.write('one')
            with override_settings(STATICFILES_DIRS=[tmp]):
                first = file_version('probe.js')
                with open(path, 'w') as f:
                    f.write('two')
                os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns + 1_000_000))
                second = file_version('probe.js')
        self.assertNotEqual(first, second)
        self.assertEqual(file_version('no/such/file.js'), 'missing')
