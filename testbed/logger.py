import argparse, csv, glob, math, os, queue, threading, time
from datetime import datetime, timezone
import numpy as np
import requests
from smbus2 import SMBus

MPU, INA = 0x68, 0x40
SAMPLE_HZ, WINDOW_S, MIN_SAMPLES = 200, 1.0, 150
G_PER_LSB = 1 / 16384.0          # MPU-6050 at +/-2 g
SHUNT_OHMS = 0.1
EQUIPMENT_ID = "EQ-001"
BANDS = ((1, 6), (6, 20), (20, 50), (50, 100))   # Hz

def band_rms(xs, ys, zs, elapsed):
    n = len(xs)
    freqs = np.fft.rfftfreq(n, d=elapsed / n)
    win = np.hanning(n)
    norm = n * np.sum(win ** 2)
    power = np.zeros(len(freqs))
    for a in (xs, ys, zs):
        a = np.asarray(a)
        spec = np.fft.rfft((a - a.mean()) * win)
        power += 2.0 * np.abs(spec) ** 2 / norm
    return [math.sqrt(power[(freqs >= lo) & (freqs < hi)].sum()) for lo, hi in BANDS]
latest_temp = {"c": float("nan")}
outbox = queue.Queue(maxsize=600)

def load_env(path=".env"):
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env

def temp_worker():
    while True:
        try:
            path = glob.glob("/sys/bus/w1/devices/28-*/temperature")[0]
            with open(path) as f:
                latest_temp["c"] = int(f.read().strip()) / 1000.0
        except Exception:
            latest_temp["c"] = float("nan")
        time.sleep(1.0)

def sender(url, token):
    session = requests.Session()
    headers = {"Authorization": f"Bearer {token}"}
    failures = 0
    while True:
        payload = outbox.get()
        try:
            r = session.post(url, json=payload, headers=headers, timeout=3)
            ok = r.status_code in (200, 201)
            if not ok:
                print(f"  server answered {r.status_code}: {r.text[:100]}")
        except requests.RequestException as e:
            ok = False
            if failures % 10 == 0:
                print(f"  send failed: {e.__class__.__name__}")
        if ok:
            if failures:
                print(f"  link restored after {failures} failed sends")
            failures = 0
        else:
            failures += 1

def i16(hi, lo):
    v = (hi << 8) | lo
    return v - 65536 if v & 0x8000 else v

def wake_mpu(bus):
    for _ in range(5):
        try:
            bus.write_byte_data(MPU, 0x6B, 0)
            return True
        except OSError:
            time.sleep(0.05)
    return False

def read_ina(bus, reg):
    for _ in range(3):
        try:
            d = bus.read_i2c_block_data(INA, reg, 2)
            return (d[0] << 8) | d[1]
        except OSError:
            time.sleep(0.01)
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="")
    ap.add_argument("--seconds", type=int, default=0, help="0 = run until Ctrl+C")
    ap.add_argument("--no-post", action="store_true")
    ap.add_argument("--warmup", type=int, default=0, help="seconds labelled as warm-up")
    args = ap.parse_args()
    env = load_env()
    url, token = env.get("INGEST_URL"), env.get("INGEST_TOKEN")
    posting = bool(url and token) and not args.no_post
    print("sending to server:", url if posting else "NO (saving to CSV only)")
    os.makedirs("data", exist_ok=True)
    fname = datetime.now(timezone.utc).strftime("data/log_%Y%m%dT%H%M%SZ.csv")
    threading.Thread(target=temp_worker, daemon=True).start()
    if posting:
        threading.Thread(target=sender, args=(url, token), daemon=True).start()
    count = bad_windows = total_errors = bad_streak = 0
    try:
        with SMBus(1) as bus, open(fname, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_utc", "temp_c", "vib_rms_g", "vib_peak_g",
                        "current_ma", "bus_v", "n_samples", "i2c_errors", "label",
                        "band_1_6_g", "band_6_20_g", "band_20_50_g", "band_50_100_g"])
            if not wake_mpu(bus):
                print("cannot wake the MPU-6050: check its wiring")
                return
            try:
                bus.write_i2c_block_data(INA, 0x00, [0x3F, 0xFF])   # INA219 averaging on
            except OSError:
                print("warning: could not configure the INA219")
            time.sleep(0.3)
            dt = 1.0 / SAMPLE_HZ
            while args.seconds == 0 or count < args.seconds:
                xs, ys, zs = [], [], []
                errors = 0
                t0 = time.perf_counter()
                nxt = t0
                while time.perf_counter() - t0 < WINDOW_S:
                    try:
                        d = bus.read_i2c_block_data(MPU, 0x3B, 6)
                    except OSError:
                        errors += 1
                        if errors % 20 == 0:
                            wake_mpu(bus)
                        time.sleep(0.005)
                        nxt = time.perf_counter() + dt
                        continue
                    x = i16(d[0], d[1]) * G_PER_LSB
                    y = i16(d[2], d[3]) * G_PER_LSB
                    z = i16(d[4], d[5]) * G_PER_LSB
                    if not 0.6 < math.sqrt(x * x + y * y + z * z) < 1.6:
                        errors += 1          # glitch sample, for example all zeros
                        nxt = time.perf_counter() + dt
                        continue
                    xs.append(x)
                    ys.append(y)
                    zs.append(z)
                    nxt += dt
                    delay = nxt - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                elapsed = time.perf_counter() - t0
                count += 1
                total_errors += errors
                n = len(xs)
                stamp = datetime.now(timezone.utc).isoformat()
                lab = f"{args.label}_warmup" if count <= args.warmup else args.label
                if n < MIN_SAMPLES:
                    bad_windows += 1
                    bad_streak += 1
                    w.writerow([stamp, "nan", "nan", "nan", "nan", "nan", n, errors, lab, "nan", "nan", "nan", "nan"])
                    f.flush()
                    print(f"  bad window: {n} samples, {errors} I2C errors")
                    if bad_streak >= 20:
                        print("too many bad windows in a row, stopping")
                        break
                    continue
                bad_streak = 0
                mx, my, mz = sum(xs) / n, sum(ys) / n, sum(zs) / n
                dev = [math.sqrt((x - mx) ** 2 + (y - my) ** 2 + (z - mz) ** 2)
                       for x, y, z in zip(xs, ys, zs)]
                rms = math.sqrt(sum(v * v for v in dev) / n)
                peak = max(dev)
                shunt, busraw = read_ina(bus, 0x01), read_ina(bus, 0x02)
                if shunt is None or busraw is None:
                    ma = bus_v = float("nan")
                else:
                    shunt = shunt - 65536 if shunt & 0x8000 else shunt
                    ma = max(0.0, shunt * 0.01 / SHUNT_OHMS)
                    bus_v = (busraw >> 3) * 0.004
                temp = latest_temp["c"]
                row = [stamp, round(temp, 2), round(rms, 5), round(peak, 5),
                       round(ma, 1), round(bus_v, 3), n, errors, lab] + [round(b, 5) for b in band_rms(xs, ys, zs, elapsed)]
                w.writerow(row)
                f.flush()
                print(row)
                if posting and math.isfinite(temp) and math.isfinite(ma):
                    payload = {"equipment_id": EQUIPMENT_ID, "timestamp": stamp,
                               "temp_c": round(temp, 2), "vib_rms_g": round(rms, 5),
                               "vib_peak_g": round(peak, 5), "current_ma": round(ma, 1),
                               "bus_v": round(bus_v, 3), "label": lab}
                    try:
                        outbox.put_nowait(payload)
                    except queue.Full:
                        outbox.get_nowait()
                        outbox.put_nowait(payload)
    except KeyboardInterrupt:
        print("stopped")
    deadline = time.time() + 3
    while posting and not outbox.empty() and time.time() < deadline:
        time.sleep(0.1)
    print(f"done: {count} windows, {bad_windows} bad, {total_errors} I2C read errors")

main()
