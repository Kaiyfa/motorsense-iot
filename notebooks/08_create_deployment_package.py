"""
Create Deployment Package using Keras Model
Alternative to TFLite for Raspberry Pi deployment
"""

import shutil
from pathlib import Path
import pickle
import json

print("=" * 70)
print("CREATING RASPBERRY PI DEPLOYMENT PACKAGE")
print("=" * 70)

# ============================================================
# 1. ORGANIZE DEPLOYMENT FILES
# ============================================================
print("\n" + "=" * 70)
print("1. ORGANIZING DEPLOYMENT FILES")
print("=" * 70)

deploy_dir = Path('deployment')
deploy_dir.mkdir(exist_ok=True)

# Copy model
model_src = Path('models/trained/best_model_top_sensors.keras')
model_dst = deploy_dir / 'model.keras'
shutil.copy(model_src, model_dst)
model_size = model_dst.stat().st_size / (1024 * 1024)
print(f"✅ Copied model: {model_dst} ({model_size:.2f} MB)")

# Copy scaler
scaler_src = Path('models/scaler_top_sensors.pkl')
scaler_dst = deploy_dir / 'scaler.pkl'
shutil.copy(scaler_src, scaler_dst)
print(f"✅ Copied scaler: {scaler_dst}")

# ============================================================
# 2. CREATE DEPLOYMENT CONFIG
# ============================================================
print("\n" + "=" * 70)
print("2. CREATING DEPLOYMENT CONFIGURATION")
print("=" * 70)

config = {
    'model_info': {
        'model_file': 'model.keras',
        'model_size_mb': float(model_size),
        'framework': 'TensorFlow/Keras',
        'input_shape': [1, 30, 13],
        'output_shape': [1, 1]
    },
    'preprocessing': {
        'scaler_file': 'scaler.pkl',
        'scaler_type': 'StandardScaler',
        'sequence_length': 30,
        'n_features': 13
    },
    'features': {
        'sensor_features': [
            'sensor_12', 'sensor_7', 'sensor_21', 'sensor_20',
            'sensor_14', 'sensor_9', 'sensor_13', 'sensor_8',
            'sensor_3', 'sensor_17'
        ],
        'operational_settings': [
            'op_setting_1', 'op_setting_2', 'op_setting_3'
        ]
    },
    'performance': {
        'validation_rmse': 15.46,
        'validation_mae': 11.80,
        'validation_r2': 0.8657,
        'accuracy_description': 'Predictions accurate within ±11.8 cycles on average'
    },
    'alert_thresholds': {
        'critical': 20,
        'warning': 50,
        'healthy': 100
    }
}

config_path = deploy_dir / 'config.json'
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)
print(f"✅ Saved config: {config_path}")

# ============================================================
# 3. CREATE INFERENCE SERVICE
# ============================================================
print("\n" + "=" * 70)
print("3. CREATING INFERENCE SERVICE")
print("=" * 70)

inference_service = '''"""
FastAPI Inference Service for Predictive Maintenance
Deploy this on Raspberry Pi 4
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import numpy as np
import tensorflow as tf
import joblib
import json
from pathlib import Path
from typing import List
import uvicorn

# Initialize FastAPI
app = FastAPI(title="MotorSense IoT Predictive Maintenance API")

# Load model and scaler at startup
print("Loading model and scaler...")
model = tf.keras.models.load_model('model.keras')
scaler = joblib.load('scaler.pkl')

with open('config.json', 'r') as f:
    config = json.load(f)

print("✅ Model and scaler loaded successfully!")

# Request model
class SensorData(BaseModel):
    """30 time steps of 13 sensor readings"""
    data: List[List[float]]  # Shape: [30, 13]

class PredictionResponse(BaseModel):
    rul_prediction: float
    status: str
    alert_level: str
    confidence: str
    message: str

@app.get("/")
def root():
    return {
        "service": "MotorSense IoT Predictive Maintenance API",
        "version": "1.0",
        "model_performance": config['performance'],
        "status": "operational"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy", "model_loaded": True}

@app.post("/predict", response_model=PredictionResponse)
def predict_rul(sensor_data: SensorData):
    """
    Predict Remaining Useful Life from sensor data
    
    Input: 30 time steps × 13 sensor readings
    Output: RUL prediction in cycles
    """
    try:
        # Convert to numpy array
        data = np.array(sensor_data.data)
        
        # Validate shape
        if data.shape != (30, 13):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid shape {data.shape}. Expected (30, 13)"
            )
        
        # Scale features
        data_scaled = scaler.transform(data)
        data_reshaped = data_scaled.reshape(1, 30, 13)
        
        # Predict
        prediction = model.predict(data_reshaped, verbose=0)[0][0]
        rul = float(np.clip(prediction, 0, 125))
        
        # Determine status
        thresholds = config['alert_thresholds']
        if rul < thresholds['critical']:
            status = "CRITICAL"
            alert_level = "RED"
            message = f"Maintenance required immediately! Only {rul:.1f} cycles remaining."
        elif rul < thresholds['warning']:
            status = "WARNING"
            alert_level = "YELLOW"
            message = f"Schedule maintenance soon. {rul:.1f} cycles remaining."
        elif rul < thresholds['healthy']:
            status = "NORMAL"
            alert_level = "GREEN"
            message = f"Equipment operational. {rul:.1f} cycles remaining."
        else:
            status = "HEALTHY"
            alert_level = "GREEN"
            message = f"Equipment in excellent condition. {rul:.1f} cycles remaining."
        
        return PredictionResponse(
            rul_prediction=rul,
            status=status,
            alert_level=alert_level,
            confidence="86.6%",  # R² score
            message=message
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/model-info")
def model_info():
    return config

if __name__ == "__main__":
    print("="*70)
    print("🚀 STARTING MOTORSENSE IOT PREDICTIVE MAINTENANCE SERVICE")
    print("="*70)
    print(f"Model Performance: RMSE={config['performance']['validation_rmse']} cycles")
    print(f"Alert Thresholds: Critical<{config['alert_thresholds']['critical']}, "
          f"Warning<{config['alert_thresholds']['warning']}")
    print("="*70)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''

service_path = deploy_dir / 'inference_service.py'
with open(service_path, 'w') as f:
    f.write(inference_service)
print(f"✅ Created: {service_path}")

# ============================================================
# 4. CREATE REQUIREMENTS FILE
# ============================================================
print("\n" + "=" * 70)
print("4. CREATING REQUIREMENTS FILE")
print("=" * 70)

requirements = '''# Raspberry Pi Deployment Requirements
tensorflow==2.13.0  # or tensorflow-aarch64 for ARM
fastapi==0.103.0
uvicorn[standard]==0.23.0
pydantic==2.3.0
numpy==1.24.3
scikit-learn==1.3.0
joblib==1.3.2
'''

req_path = deploy_dir / 'requirements.txt'
with open(req_path, 'w') as f:
    f.write(requirements)
print(f"✅ Created: {req_path}")

# ============================================================
# 5. CREATE DEPLOYMENT GUIDE
# ============================================================
print("\n" + "=" * 70)
print("5. CREATING DEPLOYMENT GUIDE")
print("=" * 70)

guide = '''# 🚀 RASPBERRY PI DEPLOYMENT GUIDE

## MotorSense IoT Predictive Maintenance System

### Files in this Package:
- `model.keras` - Trained LSTM model (Validation RMSE: 15.46 cycles)
- `scaler.pkl` - Feature scaler
- `config.json` - Configuration and thresholds
- `inference_service.py` - FastAPI prediction service
- `requirements.txt` - Python dependencies

---

## 🔧 SETUP ON RASPBERRY PI 4

### Step 1: Transfer Files
```bash
# On your Mac, from project directory:
scp -r deployment/* pi@raspberrypi.local:~/predictive_maintenance/
```

### Step 2: SSH into Raspberry Pi
```bash
ssh pi@raspberrypi.local
cd ~/predictive_maintenance
```

### Step 3: Install Dependencies
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.9+
sudo apt install python3-pip python3-venv -y

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Test the Service
```bash
# Start service
python inference_service.py

# In another terminal, test:
curl http://localhost:8000/health
```

### Step 5: Test Prediction
```python
import requests
import numpy as np

# Generate test data (30 timesteps, 13 features)
test_data = np.random.randn(30, 13).tolist()

response = requests.post(
    'http://localhost:8000/predict',
    json={'data': test_data}
)

print(response.json())
```

---

## 📊 MODEL PERFORMANCE

- **Validation RMSE:** 15.46 cycles
- **Validation MAE:** 11.80 cycles  
- **R² Score:** 0.8657 (86.57% accuracy)

**Translation:** Predictions are accurate within ±11.8 cycles on average

---

## ⚠️ ALERT THRESHOLDS

- **🔴 CRITICAL:** RUL < 20 cycles → Immediate maintenance
- **🟡 WARNING:** RUL < 50 cycles → Schedule maintenance  
- **🟢 NORMAL:** RUL < 100 cycles → Monitor
- **🟢 HEALTHY:** RUL ≥ 100 cycles → Equipment OK

---

## 🔌 CONNECTING SENSORS

### With Raspberry Pi Pico:
1. Connect Pico via USB to Pi 4
2. Pico simulates/reads 13 sensor values
3. Sends data to Pi 4 via serial
4. Pi 4 runs inference and displays RUL

### Sensor Mapping:
Top 10 predictive sensors:
1. sensor_12 (highest correlation: 0.672)
2. sensor_7 (correlation: 0.657)
3. sensor_21, sensor_20, sensor_14
4. sensor_9, sensor_13, sensor_8
5. sensor_3, sensor_17

Plus 3 operational settings

---

## 🚀 PRODUCTION DEPLOYMENT

### Run as System Service:
```bash
sudo nano /etc/systemd/system/predictive-maintenance.service
```
```ini
[Unit]
Description=MotorSense IoT Predictive Maintenance Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/predictive_maintenance
Environment="PATH=/home/pi/predictive_maintenance/venv/bin"
ExecStart=/home/pi/predictive_maintenance/venv/bin/python inference_service.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable predictive-maintenance
sudo systemctl start predictive-maintenance
sudo systemctl status predictive-maintenance
```

---

## 📝 API ENDPOINTS

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service info |
| `/health` | GET | Health check |
| `/predict` | POST | RUL prediction |
| `/model-info` | GET | Model details |

---

## ✅ SUCCESS CRITERIA

✓ Model loads without errors  
✓ Inference completes in < 1 second  
✓ API responds on port 8000  
✓ Predictions within [0-125] range  
✓ Alert levels assigned correctly

---

**For support: Contact the MotorSense IoT team**
'''

guide_path = deploy_dir / 'DEPLOYMENT_GUIDE.md'
with open(guide_path, 'w') as f:
    f.write(guide)
print(f"✅ Created: {guide_path}")

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("✅ DEPLOYMENT PACKAGE COMPLETE!")
print("=" * 70)

print("\n📦 PACKAGE CONTENTS (deployment/):")
print(f"   1. model.keras ({model_size:.2f} MB)")
print(f"   2. scaler.pkl")
print(f"   3. config.json")
print(f"   4. inference_service.py (FastAPI)")
print(f"   5. requirements.txt")
print(f"   6. DEPLOYMENT_GUIDE.md")

print("\n🎯 MODEL PERFORMANCE:")
print(f"   • RMSE: 15.46 cycles")
print(f"   • MAE: 11.80 cycles")
print(f"   • R²: 0.8657 (86.57%)")

print("\n📋 NEXT STEPS:")
print("   1. ✅ Model trained (EXCELLENT performance!)")
print("   2. ✅ Deployment package created")
print("   3. ⏳ Transfer files to Raspberry Pi")
print("   4. ⏳ Install dependencies on Pi")
print("   5. ⏳ Start inference service")
print("   6. ⏳ Connect Pico sensors")

print("\n💡 TO TRANSFER TO RASPBERRY PI:")
print("   cd ~/MotorSensePredictiveMaintenance")
print("   scp -r deployment/* pi@raspberrypi.local:~/predictive_maintenance/")

print("\n" + "=" * 70)
print("🌟 READY FOR RASPBERRY PI DEPLOYMENT!")
print("=" * 70)
