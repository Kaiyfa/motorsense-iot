# Testbed: the bench rig and its logger

`logger.py` runs on the Raspberry Pi. It reads the sensors, reduces the vibration samples to
one row per second, writes every row to a CSV file and, optionally, posts it to the
dashboard's ingest endpoint. This file is an unchanged copy of the logger used for every
recording.

## Hardware

**Pi.** Raspberry Pi 4 Model B with Raspberry Pi OS, running the logger with Python 3.13 in a
venv. The Pi is powered separately from the car's battery pack.

**Load.** An Elegoo Smart Robot Car V4.0 (shield V1.1, four TT gearmotors, sealed 7.4 V
2000 mAh Li-ion pack with its own switch). The wheels are removed and the motors run free at
a fixed speed on a bench.

**Sensors**

| Sensor | Connection | Settings |
|---|---|---|
| DFRobot Fermion MPU-6050 (vibration) | I2C, address 0x68 | Range ±2 g, 16384 LSB per g |
| CJMCU-219 INA219 breakout (current, pack voltage) | I2C, address 0x40 | 0.1 Ω shunt (R100); shunt LSB 10 µV, bus LSB 4 mV; averaging configured by writing 0x3FFF to register 0x00 |
| DS18B20 probe (temperature) | 1-Wire on GPIO4 (pin 7) | 3.3 V on pin 1, GND on pin 9, 4.7 kΩ pull-up |

Both I2C sensors share SDA and SCL on pins 3 and 5.

**Mounting**
- **INA219:** in series with the pack's positive wire. The pack's red wire goes to VIN+ and the board side to VIN−.
- **Ground:** the shield's GND header is tied to the breadboard GND.
- **MPU-6050:** sits on a breadboard that rests on the chassis and is not rigidly fixed.
- **DS18B20:** attached with tape near a motor; its exact position was not recorded.

## What the logger does

Every second (one window):

1. **Vibration.** The logger reads the MPU-6050 accelerometer at 200 Hz for one second.
   - **Glitch rejection:** a sample whose total acceleration is outside 0.6 to 1.6 g (for example all zeros) is dropped.
   - **Bad windows:** a window with fewer than 150 valid samples is written as `nan` and not posted. After 20 bad windows in a row the logger stops.
2. **Gravity removal.** The window mean of each axis is subtracted from every sample. The logger then writes the RMS and the peak of the remaining deviation, in g, as `vib_rms_g` and `vib_peak_g`.
3. **Frequency bands.** The logger computes the vibration RMS in four bands: 1 to 6, 6 to 20, 20 to 50 and 50 to 100 Hz. It uses a Hann-windowed FFT of each axis, summed over the three axes. Recordings made before the band columns were added do not have them.
4. **Current and voltage.** The INA219 is read once per window:
   - current in mA = shunt register × 10 µV / 0.1 Ω, never below 0;
   - pack voltage = bus register >> 3 × 4 mV.
5. **Temperature.** A background thread reads the DS18B20 from `/sys/bus/w1/devices/28-*/temperature` once per second.

**I2C errors.** Failed reads are retried:
- **MPU-6050:** a failed read is skipped and the device is woken again after every 20 errors.
- **INA219:** each register is read up to three times.

The `i2c_errors` column counts failed reads and rejected glitch samples together.

### CSV output

The logger writes `data/log_<UTC start time>.csv`, relative to the folder it is started from.

| Column | Content |
|---|---|
| `timestamp_utc` | End of the window, ISO 8601, UTC |
| `temp_c` | Temperature, °C |
| `vib_rms_g`, `vib_peak_g` | RMS and peak of the vibration deviation, g |
| `current_ma` | Current, mA |
| `bus_v` | Pack voltage, V |
| `n_samples` | Valid samples in the window |
| `i2c_errors` | Failed reads and rejected samples in the window |
| `label` | Session label (see below) |
| `band_1_6_g`, `band_6_20_g`, `band_20_50_g`, `band_50_100_g` | Vibration RMS per frequency band, g |

### Command-line flags

| Flag | Meaning |
|---|---|
| `--label NAME` | Label written to every row |
| `--seconds N` | Stop after N windows (0, the default, runs until Ctrl+C) |
| `--warmup N` | The first N windows get the label `NAME_warmup` instead of `NAME` |
| `--no-post` | Write the CSV only; do not post to the server |

The `_warmup` label rule is how the recorded sessions mark their warm-up segment. The
evaluation and the live scorer exclude these rows (see `docs/evaluation_plan.md`).

### Posting to the dashboard

The logger reads `INGEST_URL` and `INGEST_TOKEN` from a `.env` file in the folder it is
started from. On the Pi this is `testbed/.env`; `testbed/.env.example` shows the format.

When both values are set and `--no-post` is not given, each complete row is posted as JSON
to the ingest endpoint with the header `Authorization: Bearer <token>`. Posting:
- happens on a background thread with a queue of up to 600 rows (the oldest row is dropped when the queue is full);
- skips rows whose temperature or current is `nan`;
- does not stop the logger when the server is unreachable: the CSV is written either way.

The token must equal `INGEST_TOKEN` in the dashboard's `.env`.

## Pi setup

1. Enable I2C and 1-Wire, for example with `sudo raspi-config` (Interface Options), then reboot.
2. Create a venv and install the packages:
   ```
   cd testbed
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in the dashboard's ingest URL and token.
4. Run, for example:
   ```
   python logger.py --label my_session --warmup 180 --seconds 660
   ```

`requirements.txt` lists smbus2, requests and numpy, the three packages the logger imports.
Their versions on the Pi were not recorded, so they are not pinned.

## Known issues

- **I2C read errors:** a few per session normally, hundreds when the rig is disturbed.
- **One invalid session:** recorded after a motor lead was reconnected.
- **No TLS:** rows are posted over plain HTTP on a home network, so the bearer token travels in clear text.
