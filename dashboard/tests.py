import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Equipment, SensorData

TOKEN = 'test-ingest-token'


def valid_body(**overrides):
    body = {
        'equipment_id': 'EQ-001',
        'timestamp': '2026-10-14T12:00:00Z',
        'temp_c': 31.5,
        'vib_rms_g': 0.42,
        'vib_peak_g': 1.10,
        'current_ma': 1250,
        'bus_v': 12.1,
        'label': 'bench-run-1',
    }
    body.update(overrides)
    return body


@override_settings(INGEST_TOKEN=TOKEN)
class IngestEndpointTests(TestCase):
    url = reverse('dashboard:ingest')

    def post(self, body, token=TOKEN, raw=None):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token is not None else {}
        data = raw if raw is not None else json.dumps(body)
        return self.client.post(self.url, data=data, content_type='application/json', **headers)

    def test_missing_token_returns_401(self):
        response = self.post(valid_body(), token=None)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(SensorData.objects.count(), 0)

    def test_wrong_token_returns_401(self):
        response = self.post(valid_body(), token='not-the-token')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(SensorData.objects.count(), 0)

    def test_out_of_range_values_return_400(self):
        cases = {
            'temp_c': 151,
            'vib_rms_g': -0.1,
            'vib_peak_g': 25,
            'current_ma': 5001,
            'bus_v': 31,
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                response = self.post(valid_body(**{field: value}))
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['error'])
        self.assertEqual(SensorData.objects.count(), 0)

    def test_non_finite_and_non_numeric_values_return_400(self):
        response = self.post(None, raw='{"temp_c": NaN, "vib_rms_g": 0.1, "vib_peak_g": 0.2, '
                                       '"current_ma": 10, "bus_v": 12}')
        self.assertEqual(response.status_code, 400)
        response = self.post(valid_body(temp_c='31.5'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SensorData.objects.count(), 0)

    def test_valid_body_returns_201_and_converts_units(self):
        response = self.post(valid_body())
        self.assertEqual(response.status_code, 201)

        reading = SensorData.objects.get(id=response.json()['id'])
        self.assertEqual(reading.equipment_id, 'EQ-001')
        self.assertEqual(reading.equipment.name, 'Motor testbed')
        self.assertEqual(reading.timestamp.isoformat(), '2026-10-14T12:00:00+00:00')
        self.assertAlmostEqual(reading.temperature, 31.5)
        self.assertAlmostEqual(reading.vibration_rms, 0.42)
        self.assertAlmostEqual(reading.vibration_peak, 1.10)
        self.assertAlmostEqual(reading.current, 1.25)  # 1250 mA -> 1.25 A
        self.assertAlmostEqual(reading.bus_voltage, 12.1)
        self.assertEqual(reading.run_label, 'bench-run-1')
        self.assertEqual(reading.source, 'pi')

    def test_duplicate_returns_200_and_stores_nothing(self):
        self.assertEqual(self.post(valid_body()).status_code, 201)

        response = self.post(valid_body(temp_c=40.0))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'duplicate'})
        self.assertEqual(SensorData.objects.count(), 1)

    def test_body_over_4kb_is_rejected(self):
        response = self.post(valid_body(label='x' * 5000))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(SensorData.objects.count(), 0)

    def test_get_not_allowed(self):
        response = self.client.get(self.url, HTTP_AUTHORIZATION=f'Bearer {TOKEN}')
        self.assertEqual(response.status_code, 405)


class LiveReadingTests(TestCase):
    url = reverse('dashboard:live_reading')

    def setUp(self):
        user = User.objects.create_user('tester', password='a-long-password')
        self.client.force_login(user)
        self.equipment = Equipment.objects.create(
            equipment_id='EQ-001',
            name='Motor testbed',
            equipment_type='MOTOR',
            location='Test bench',
            installation_date=timezone.now().date(),
        )

    def add_reading(self, age_seconds, source='pi'):
        return SensorData.objects.create(
            equipment=self.equipment,
            timestamp=timezone.now() - timedelta(seconds=age_seconds),
            temperature=30.0,
            vibration_rms=0.5,
            vibration_peak=1.2,
            current=0.8,
            bus_voltage=12.0,
            source=source,
        )

    def test_no_data_when_empty(self):
        data = self.client.get(self.url).json()
        self.assertEqual(data['status'], 'no_data')
        self.assertIsNone(data['last_timestamp'])
        self.assertNotIn('reading', data)

    def test_ok_when_fresh(self):
        self.add_reading(age_seconds=3)
        data = self.client.get(self.url).json()
        self.assertEqual(data['status'], 'ok')
        self.assertLess(data['age_seconds'], 15)
        self.assertEqual(data['reading']['temperature'], 30.0)
        self.assertEqual(data['reading']['current'], 0.8)
        self.assertEqual(data['reading']['bus_voltage'], 12.0)

    def test_no_data_when_older_than_15_seconds(self):
        reading = self.add_reading(age_seconds=20)
        data = self.client.get(self.url).json()
        self.assertEqual(data['status'], 'no_data')
        self.assertEqual(data['last_timestamp'], reading.timestamp.isoformat())
        self.assertGreater(data['age_seconds'], 15)
        self.assertNotIn('reading', data)

    def test_sample_rows_are_ignored(self):
        self.add_reading(age_seconds=1, source='sample')
        data = self.client.get(self.url).json()
        self.assertEqual(data['status'], 'no_data')
