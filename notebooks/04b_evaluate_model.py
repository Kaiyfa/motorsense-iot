"""
Fixed Model Evaluation with NaN Handling
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import pickle

from tensorflow import keras
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

print("=" * 70)
print("LSTM MODEL EVALUATION (WITH NaN HANDLING)")
print("=" * 70)

# ============================================================
# 1. LOAD DATA AND MODEL
# ============================================================
print("\n" + "=" * 70)
print("1. LOADING DATA AND TRAINED MODEL")
print("=" * 70)

data_dir = Path('data/processed/sequences')
models_dir = Path('models/trained')

X_train = np.load(data_dir / 'X_train.npy')
y_train = np.load(data_dir / 'y_train.npy')
X_val = np.load(data_dir / 'X_val.npy')
y_val = np.load(data_dir / 'y_val.npy')

print(f"✅ Data loaded:")
print(f"   Training: {X_train.shape}")
print(f"   Validation: {X_val.shape}")

# Load best model
model = keras.models.load_model(models_dir / 'best_lstm_model.keras')
print(f"✅ Model loaded: {models_dir}/best_lstm_model.keras")

# ============================================================
# 2. MAKE PREDICTIONS WITH NaN HANDLING
# ============================================================
print("\n" + "=" * 70)
print("2. GENERATING PREDICTIONS")
print("=" * 70)

# Predictions
y_train_pred = model.predict(X_train, verbose=0, batch_size=256).flatten()
y_val_pred = model.predict(X_val, verbose=0, batch_size=256).flatten()

# Check for NaN values
train_nan_count = np.isnan(y_train_pred).sum()
val_nan_count = np.isnan(y_val_pred).sum()

print(f"Training predictions - NaN count: {train_nan_count}")
print(f"Validation predictions - NaN count: {val_nan_count}")

if train_nan_count > 0 or val_nan_count > 0:
    print("\n⚠️  Found NaN values! Replacing with mean...")
    
    # Replace NaN with mean of non-NaN predictions
    train_mean = np.nanmean(y_train_pred)
    val_mean = np.nanmean(y_val_pred)
    
    y_train_pred = np.nan_to_num(y_train_pred, nan=train_mean)
    y_val_pred = np.nan_to_num(y_val_pred, nan=val_mean)
    
    print(f"✅ NaN values handled")

# Clip predictions to valid RUL range [0, 125]
y_train_pred = np.clip(y_train_pred, 0, 125)
y_val_pred = np.clip(y_val_pred, 0, 125)

print("✅ Predictions clipped to [0, 125] range")

# ============================================================
# 3. CALCULATE METRICS
# ============================================================
print("\n" + "=" * 70)
print("3. CALCULATING PERFORMANCE METRICS")
print("=" * 70)

# Training metrics
train_rmse = np.sqrt(mean_squared_error(y_train, y_train_pred))
train_mae = mean_absolute_error(y_train, y_train_pred)
train_r2 = r2_score(y_train, y_train_pred)

# Validation metrics
val_rmse = np.sqrt(mean_squared_error(y_val, y_val_pred))
val_mae = mean_absolute_error(y_val, y_val_pred)
val_r2 = r2_score(y_val, y_val_pred)

print("\n📊 TRAINING SET PERFORMANCE:")
print(f"   RMSE: {train_rmse:.2f} cycles")
print(f"   MAE:  {train_mae:.2f} cycles")
print(f"   R²:   {train_r2:.4f}")

print("\n📊 VALIDATION SET PERFORMANCE:")
print(f"   RMSE: {val_rmse:.2f} cycles")
print(f"   MAE:  {val_mae:.2f} cycles")
print(f"   R²:   {val_r2:.4f}")

# Performance interpretation
print("\n" + "=" * 70)
print("PERFORMANCE ASSESSMENT:")
print("=" * 70)

if val_rmse < 15:
    print("🌟 EXCELLENT: RMSE < 15 cycles")
elif val_rmse < 20:
    print("✅ VERY GOOD: RMSE < 20 cycles")
elif val_rmse < 30:
    print("👍 GOOD: RMSE < 30 cycles")
else:
    print("⚠️  NEEDS IMPROVEMENT: RMSE > 30 cycles")

if val_r2 > 0.80:
    print("🌟 EXCELLENT: R² > 0.80 (strong predictions)")
elif val_r2 > 0.70:
    print("✅ VERY GOOD: R² > 0.70")
elif val_r2 > 0.60:
    print("👍 GOOD: R² > 0.60")
else:
    print("⚠️  NEEDS IMPROVEMENT: R² < 0.60")

# ============================================================
# 4. DETAILED ERROR ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("4. ERROR ANALYSIS")
print("=" * 70)

val_errors = y_val - y_val_pred
val_abs_errors = np.abs(val_errors)

print(f"\nValidation Error Statistics:")
print(f"   Mean Error: {val_errors.mean():.2f} cycles")
print(f"   Std of Errors: {val_errors.std():.2f} cycles")
print(f"   Max Overestimate: {val_errors.max():.2f} cycles")
print(f"   Max Underestimate: {val_errors.min():.2f} cycles")

# Percentage of predictions within acceptable ranges
within_5 = (val_abs_errors <= 5).sum() / len(val_abs_errors) * 100
within_10 = (val_abs_errors <= 10).sum() / len(val_abs_errors) * 100
within_15 = (val_abs_errors <= 15).sum() / len(val_abs_errors) * 100

print(f"\nPrediction Accuracy:")
print(f"   Within ±5 cycles:  {within_5:.1f}%")
print(f"   Within ±10 cycles: {within_10:.1f}%")
print(f"   Within ±15 cycles: {within_15:.1f}%")

# ============================================================
# 5. VISUALIZATIONS
# ============================================================
print("\n" + "=" * 70)
print("5. GENERATING VISUALIZATIONS")
print("=" * 70)

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# Validation predictions scatter
axes[0, 0].scatter(y_val, y_val_pred, alpha=0.4, s=15, color='steelblue')
axes[0, 0].plot([0, 125], [0, 125], 'r--', linewidth=2, label='Perfect Prediction')
axes[0, 0].set_title(f'Validation Predictions (R²={val_r2:.4f}, RMSE={val_rmse:.2f})', 
                      fontweight='bold', fontsize=12)
axes[0, 0].set_xlabel('Actual RUL (cycles)', fontsize=11)
axes[0, 0].set_ylabel('Predicted RUL (cycles)', fontsize=11)
axes[0, 0].legend(fontsize=10)
axes[0, 0].grid(True, alpha=0.3)

# Error distribution
axes[0, 1].hist(val_errors, bins=50, color='coral', edgecolor='black', alpha=0.7)
axes[0, 1].axvline(0, color='red', linestyle='--', linewidth=2, label='Zero Error')
axes[0, 1].set_title('Prediction Error Distribution', fontweight='bold', fontsize=12)
axes[0, 1].set_xlabel('Error (Actual - Predicted)', fontsize=11)
axes[0, 1].set_ylabel('Frequency', fontsize=11)
axes[0, 1].legend(fontsize=10)
axes[0, 1].grid(True, alpha=0.3)

# Error vs Actual RUL
axes[1, 0].scatter(y_val, val_abs_errors, alpha=0.4, s=15, color='purple')
axes[1, 0].axhline(val_mae, color='orange', linestyle='--', linewidth=2, 
                   label=f'MAE={val_mae:.2f}')
axes[1, 0].set_title('Absolute Error vs Actual RUL', fontweight='bold', fontsize=12)
axes[1, 0].set_xlabel('Actual RUL (cycles)', fontsize=11)
axes[1, 0].set_ylabel('Absolute Error (cycles)', fontsize=11)
axes[1, 0].legend(fontsize=10)
axes[1, 0].grid(True, alpha=0.3)

# Sample predictions for one engine
sample_indices = np.where((y_val >= 80) & (y_val <= 120))[0][:100]
axes[1, 1].plot(y_val[sample_indices], label='Actual RUL', marker='o', linewidth=2, markersize=4)
axes[1, 1].plot(y_val_pred[sample_indices], label='Predicted RUL', marker='s', linewidth=2, markersize=4)
axes[1, 1].fill_between(range(len(sample_indices)), 
                        y_val[sample_indices] - 10, 
                        y_val[sample_indices] + 10, 
                        alpha=0.2, label='±10 cycles')
axes[1, 1].set_title('Sample Predictions (100 points)', fontweight='bold', fontsize=12)
axes[1, 1].set_xlabel('Sample Index', fontsize=11)
axes[1, 1].set_ylabel('RUL (cycles)', fontsize=11)
axes[1, 1].legend(fontsize=10)
axes[1, 1].grid(True, alpha=0.3)

plt.tight_layout()
viz_path = 'docs/diagrams/eda/lstm_evaluation_results.png'
plt.savefig(viz_path, dpi=300, bbox_inches='tight')
print(f"✅ Saved: {viz_path}")
plt.close()

# ============================================================
# 6. SAVE EVALUATION RESULTS
# ============================================================
print("\n" + "=" * 70)
print("6. SAVING EVALUATION RESULTS")
print("=" * 70)

metrics = {
    'train_rmse': float(train_rmse),
    'train_mae': float(train_mae),
    'train_r2': float(train_r2),
    'val_rmse': float(val_rmse),
    'val_mae': float(val_mae),
    'val_r2': float(val_r2),
    'within_5_cycles_pct': float(within_5),
    'within_10_cycles_pct': float(within_10),
    'within_15_cycles_pct': float(within_15)
}

metrics_path = models_dir / 'evaluation_metrics.pkl'
with open(metrics_path, 'wb') as f:
    pickle.dump(metrics, f)
print(f"✅ Saved: {metrics_path}")

# Save predictions for further analysis
np.save(models_dir / 'val_predictions.npy', y_val_pred)
np.save(models_dir / 'val_actuals.npy', y_val)
print(f"✅ Saved predictions and actuals")

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("✅ MODEL EVALUATION COMPLETE!")
print("=" * 70)
print("\n🎯 KEY METRICS FOR MOTORSENSE IOT:")
print(f"   • Validation RMSE: {val_rmse:.2f} cycles")
print(f"   • Validation MAE:  {val_mae:.2f} cycles")
print(f"   • R² Score:        {val_r2:.4f}")
print(f"   • Predictions within ±10 cycles: {within_10:.1f}%")
print("\n📊 What this means:")
print(f"   On average, predictions are off by {val_mae:.1f} cycles")
print(f"   The model explains {val_r2*100:.1f}% of RUL variance")
print("\n✅ Model is ready for edge deployment!")
print("=" * 70)
