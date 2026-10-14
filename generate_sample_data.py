#!/usr/bin/env python
"""
Generate 90 days of sample sensor data for TimescaleDB

WHY 90 DAYS?
- LSTM models need historical context to learn patterns
- 90 days = ~25,920 data points (5-min intervals) per equipment
- Provides seasonal/cyclical pattern learning
- Allows model to detect degradation trends over time
"""

import os
import sys
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'monitor.settings')
django.setup()

from dashboard.models import SensorData, Equipment
from datetime import datetime, timedelta
import numpy as np

def create_equipment_if_not_exists():
    """Create equipment records if they don't exist"""
    print("📋 Checking equipment records...")
    
    equipment_data = [
        {
            'equipment_id': 'EQ-001', 
            'equipment_type': 'Pump', 
            'location': 'Ghawar Field',
            'installation_date': timezone.now().date() - timedelta(days=365*2)  # 2 years ago
        },
        {
            'equipment_id': 'EQ-002', 
            'equipment_type': 'Compressor', 
            'location': 'Safaniya Field',
            'installation_date': timezone.now().date() - timedelta(days=365*3)  # 3 years ago
        },
        {
            'equipment_id': 'EQ-003', 
            'equipment_type': 'Turbine', 
            'location': 'Khurais Field',
            'installation_date': timezone.now().date() - timedelta(days=365*1)  # 1 year ago
        },
        {
            'equipment_id': 'EQ-006', 
            'equipment_type': 'Pump', 
            'location': 'Ghawar Field',
            'installation_date': timezone.now().date() - timedelta(days=365*2)  # 2 years ago
        },
    ]
    
    created_count = 0
    for eq_data in equipment_data:
        equipment, created = Equipment.objects.get_or_create(
            equipment_id=eq_data['equipment_id'],
            defaults={
                'equipment_type': eq_data['equipment_type'],
                'location': eq_data['location'],
                'installation_date': eq_data['installation_date'],
                'status': 'OPERATIONAL'
            }
        )
        if created:
            created_count += 1
            print(f"  ✅ Created: {eq_data['equipment_id']}")
        else:
            print(f"  ℹ️  Exists: {eq_data['equipment_id']}")
    
    print(f"✅ Equipment check complete ({created_count} created)\n")

def generate_sample_data():
    print("=" * 70)
    print("🔄 GENERATING 90 DAYS OF SAMPLE SENSOR DATA")
    print("=" * 70)
    print("\n📖 WHY 90 DAYS?")
    print("   • LSTM models need historical patterns to learn from")
    print("   • ~25,920 readings per equipment (5-min intervals)")
    print("   • Captures degradation trends over time")
    print("   • Provides realistic operational context\n")
    print("=" * 70 + "\n")
    
    # Create equipment first
    create_equipment_if_not_exists()
    
    equipment_ids = ['EQ-001', 'EQ-002', 'EQ-003', 'EQ-006']
    
    # Delete existing data
    existing_count = SensorData.objects.count()
    if existing_count > 0:
        response = input(f"⚠️  Delete {existing_count:,} existing records? (y/N): ")
        if response.lower() == 'y':
            SensorData.objects.all().delete()
            print(f"✅ Deleted {existing_count:,} records\n")
        else:
            print("❌ Aborted - keeping existing data")
            return
    
    end_time = timezone.now()
    start_time = end_time - timedelta(days=90)
    
    batch_size = 1000
    records = []
    total_created = 0
    
    for equipment_id in equipment_ids:
        print(f"📊 Generating data for {equipment_id}...")
        
        current_time = start_time
        point_count = 0
        
        while current_time < end_time:
            # Generate realistic sensor values with degradation
            days_elapsed = (current_time - start_time).days
            degradation = 1 - (days_elapsed / 90) * 0.15  # 15% degradation over 90 days
            
            # Simulate daily cycles (more wear during day shifts)
            hour = current_time.hour
            day_factor = 1.0 if 8 <= hour <= 17 else 0.8
            
            records.append(SensorData(
                equipment_id=equipment_id,
                timestamp=current_time,
                vibration_x=np.random.normal(0.5, 0.1) * degradation * day_factor,
                vibration_y=np.random.normal(0.6, 0.12) * degradation * day_factor,
                vibration_z=np.random.normal(0.4, 0.08) * degradation * day_factor,
                vibration_rms=np.random.normal(0.5, 0.08) * degradation * day_factor,
                vibration_peak=np.random.normal(0.9, 0.15) * degradation * day_factor,
                temperature=np.random.normal(45.0 + (90 - days_elapsed) * 0.1, 5.0),
                current=np.random.normal(5.2, 0.5) * degradation * day_factor,
            ))
            
            point_count += 1
            
            # Bulk insert
            if len(records) >= batch_size:
                SensorData.objects.bulk_create(records)
                total_created += len(records)
                print(f"  ✅ Inserted {total_created:,} records...")
                records = []
            
            # Move to next reading (5 minutes)
            current_time += timedelta(minutes=5)
        
        print(f"  ✅ {equipment_id}: {point_count:,} data points generated")
    
    # Insert remaining
    if records:
        SensorData.objects.bulk_create(records)
        total_created += len(records)
    
    print("\n" + "=" * 70)
    print("🎉 DATA GENERATION COMPLETE!")
    print("=" * 70)
    print(f"📊 Total records: {total_created:,}")
    print(f"🏭 Equipment: {', '.join(equipment_ids)}")
    print(f"📅 Date range: {start_time.date()} to {end_time.date()}")
    print(f"⏱️  Interval: 5 minutes")
    print(f"💾 Database: TimescaleDB (sensor_data hypertable)")
    print("=" * 70 + "\n")

if __name__ == '__main__':
    try:
        generate_sample_data()
    except KeyboardInterrupt:
        print("\n⚠️  Cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()