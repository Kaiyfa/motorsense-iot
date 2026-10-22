"""Every dashboard page returns 200 for a logged-in user and redirects to the login page otherwise."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dashboard.models import AnomalyScore, Equipment

PAGES = [
    ('dashboard:dashboard', []),
    ('dashboard:replay', []),
    ('dashboard:tab', ['sensors']),
    ('dashboard:tab', ['alerts']),
    ('dashboard:tab', ['maintenance']),
    ('dashboard:tab', ['evaluation']),
    ('dashboard:tab', ['setup']),
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
                html = response.content.decode()
                for text in REMOVED_TEXT:
                    self.assertNotIn(text, html)
                self.assertIn('EQ-001 · Bench rig, 4 DC motors', html)

    def test_login_page_is_public_and_clean(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for text in REMOVED_TEXT + ['googleapis', 'cdn.jsdelivr']:
            self.assertNotIn(text, html)

    def test_unknown_section_is_404(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('dashboard:tab', args=['nope'])).status_code, 404)

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
        self.assertIn('live.js', html)
        self.assertNotIn('replay.js', html)

    def test_replay_page_always_shows_the_banner(self):
        html = self.client.get(reverse('dashboard:replay') + '?session=r5_fault_open_01').content.decode()
        self.assertIn('REPLAY of recorded session <span class="mono">r5_fault_open_01</span>. Not live data.', html)
        self.assertIn('has not been replayed into the database yet', html)   # nothing replayed in the test DB
        self.assertNotIn('live.js', html)

    def test_replay_page_with_replayed_session(self):
        t0 = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
        AnomalyScore.objects.create(equipment=self.eq, timestamp=t0, run_label='r5_normal_05', threshold=1.0,
                                    machine_state='idle', mode='replay')
        html = self.client.get(reverse('dashboard:replay') + '?session=r5_normal_05').content.decode()
        self.assertIn('REPLAY of recorded session <span class="mono">r5_normal_05</span>. Not live data.', html)
        self.assertIn('replay.js', html)
        self.assertIn('Fault: one motor disconnected, session 1 (not replayed yet)', html)

    def test_unknown_replay_session_falls_back_to_a_known_one(self):
        response = self.client.get(reverse('dashboard:replay') + '?session=../../etc')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('../../etc', response.content.decode())

    def test_placeholders_keep_replay_mode(self):
        html = self.client.get(reverse('dashboard:tab', args=['alerts']) +
                               '?mode=replay&session=r5_fault_open_02').content.decode()
        self.assertIn('Not live data', html)
        self.assertIn('Coming in part 2.', html)
