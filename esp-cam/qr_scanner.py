import csv
import os
import socket
import time
import random
import winsound
import threading
from datetime import datetime, timezone
from collections import defaultdict

import cv2
import numpy as np
import requests
from pyzbar.pyzbar import decode

# --- KONFIGURACE -----------------------------------------------------------
ESP32_CAM_URL = "http://192.168.0.159/capture"
PC_ANL_URL = "http://localhost:5000/state"
RAW_RPT_PORT = 50001
TAG_ID = None                                 # None = prvni aktivni tag; jinak cislo

# Jak dlouho po detekci QR sbirame vzorky pro median (ms).
SAMPLE_WINDOW_MS = 500
# Cooldown mezi dvema skeny (ms).
SCAN_COOLDOWN_MS = 1500
# Frekvence stahovani snimku z ESP32-CAM (s).
CAPTURE_INTERVAL_S = 0.10

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scans"
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

ANCHOR_COUNT = 10


# --- SDILENY STAV ----------------------------------------------------------
class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.uwb_state = None
        self.latest_rpt = None
        self.last_save_info = None
        self.running = True


state = SharedState()


# --- ULOZISTE CSV ----------------------------------------------------------
def output_filenames():
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    raw = os.path.join(OUTPUT_DIR, f"scans_raw_{today}.csv")
    computed = os.path.join(OUTPUT_DIR, f"scans_computed_{today}.csv")
    return raw, computed


def init_csv_files():
    raw, computed = output_filenames()
    if not os.path.exists(raw):
        with open(raw, "w", newline="", encoding="utf-8") as f:
            header = [
                "timestamp", "scan_id", "qr_raw", "tag_id",
                *[f"range_{i}" for i in range(ANCHOR_COUNT)],
                "pos_x", "pos_y", "pos_z", "pos_source", "rpt_age_ms"
            ]
            csv.writer(f).writerow(header)
    if not os.path.exists(computed):
        with open(computed, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "timestamp", "scan_id", "qr_raw", "x", "y", "z",
                "source", "samples_count"
            ])
    return raw, computed


def append_raw_rows(rows):
    raw, _ = output_filenames()
    init_csv_files()
    with open(raw, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)


def append_computed_row(row):
    _, computed = output_filenames()
    init_csv_files()
    with open(computed, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


# --- UWB / PC ANL ----------------------------------------------------------
def normalize_pos(pos):
    if not pos:
        return None
    x = float(pos[0]) if len(pos) > 0 else 0.0
    y = float(pos[1]) if len(pos) > 1 else 0.0
    z = float(pos[2]) if len(pos) > 2 else 0.0
    return (x, y, z)


def get_uwb_state():
    try:
        response = requests.get(PC_ANL_URL, timeout=1)
        if response.status_code != 200:
            return None
        return response.json()
    except Exception:
        return None


def pick_tag_data(data):
    tags = data.get("tags", {}) if data else {}
    if not tags:
        return None
    if TAG_ID is not None:
        tid = str(TAG_ID)
        if tid in tags and tags[tid].get("pos"):
            return tags[tid]
        return None
    for tid, t in tags.items():
        if t.get("pos"):
            return t
    return None


def uwb_poller_thread():
    while state.running:
        uwb = get_uwb_state()
        with state.lock:
            state.uwb_state = uwb
        time.sleep(0.15)


# --- RAW RPT UDP LISTENER --------------------------------------------------
def parse_rpt(text):
    try:
        text = text[4:]
        tid_str, rest = text.split(":", 1)
        tid = int(tid_str)
        ranges = {}
        for pair in rest.split(","):
            if "=" not in pair:
                continue
            aid, dist = pair.split("=", 1)
            ranges[int(aid)] = float(dist)
        return tid, ranges
    except Exception:
        return None, None


def rpt_listener_thread():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", RAW_RPT_PORT))
    except OSError as e:
        print(f"[RPT] nelze bindnout port {RAW_RPT_PORT}: {e}")
        state.running = False
        return
    sock.settimeout(0.5)
    print(f"[RPT] nasloucham na portu {RAW_RPT_PORT}")

    while state.running:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        except OSError:
            break

        text = data.decode("utf-8", errors="ignore").strip()
        if not text.startswith("RPT,"):
            continue

        tid, ranges = parse_rpt(text)
        if tid is None:
            continue

        now_ms = int(time.time() * 1000)
        with state.lock:
            state.latest_rpt = {
                "timestamp": now_ms,
                "tag_id": tid,
                "ranges": ranges,
            }
    sock.close()


# --- KAMERA ----------------------------------------------------------------
def capture_thread():
    print(f"[KAMERA] stahuji snimky z {ESP32_CAM_URL} (QVGA, kazdych {CAPTURE_INTERVAL_S*1000:.0f} ms)")
    while state.running:
        try:
            response = requests.get(ESP32_CAM_URL, timeout=2)
            if response.status_code == 200:
                img_array = np.frombuffer(response.content, dtype=np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if frame is not None:
                    with state.lock:
                        state.frame = frame
        except Exception as e:
            print(f"[KAMERA] chyba: {e}")
        time.sleep(CAPTURE_INTERVAL_S)


def decode_latest_qr(frame):
    codes = decode(frame)
    if not codes:
        return None
    return codes[0].data.decode("utf-8")


# --- QR S OVERSAMPLINGEM ---------------------------------------------------
def median_3d(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (
        sum(xs) / len(xs),
        sum(ys) / len(ys),
        sum(zs) / len(zs),
    )


def print_status(uwb_data, last_save, fps):
    t_data = pick_tag_data(uwb_data)
    if t_data and t_data.get("pos"):
        x, y, z = normalize_pos(t_data["pos"])
        pos_line = f"UWB: X={x:.2f} Y={y:.2f} Z={z:.2f}"
    else:
        pos_line = "UWB: ---"

    if last_save:
        qr, x, y, z, src, ts = last_save
        age_s = (int(time.time() * 1000) - ts) / 1000.0
        save_line = f"| posledni: {qr} -> X={x:.2f} Y={y:.2f} Z={z:.2f} ({src}) pred {age_s:.1f}s"
    else:
        save_line = "| cekam na QR..."

    print(f"\r[{fps:.1f} FPS] {pos_line} {save_line}", end="", flush=True)


def qr_scan_thread():
    init_csv_files()
    cooldown_until = 0
    frame_count = 0
    last_fps_time = time.time()

    while state.running:
        now_ms = int(time.time() * 1000)

        with state.lock:
            frame = state.frame

        if frame is None:
            time.sleep(0.02)
            continue

        frame_count += 1
        if time.time() - last_fps_time >= 1.0:
            fps = frame_count / (time.time() - last_fps_time)
            frame_count = 0
            last_fps_time = time.time()
            with state.lock:
                uwb = state.uwb_state
                last_save = state.last_save_info
            print_status(uwb, last_save, fps)

        qr = decode_latest_qr(frame)
        if qr is None or now_ms < cooldown_until:
            continue

        print(f"\n[QR] detekovan '{qr}', sbiram vzorky {SAMPLE_WINDOW_MS}ms...")
        scan_id = now_ms
        window_end = now_ms + SAMPLE_WINDOW_MS

        samples = []
        qr_votes = defaultdict(int)
        collected_positions = []

        while int(time.time() * 1000) < window_end and state.running:
            with state.lock:
                f = state.frame
                latest_rpt = state.latest_rpt
                uwb = state.uwb_state

            if f is not None:
                q = decode_latest_qr(f)
                if q:
                    qr_votes[q] += 1

            if latest_rpt:
                rpt_age = int(time.time() * 1000) - latest_rpt["timestamp"]
                if rpt_age < 500:
                    row_ranges = [latest_rpt["ranges"].get(i, "") for i in range(ANCHOR_COUNT)]
                    t_data = pick_tag_data(uwb)
                    if t_data and t_data.get("pos"):
                        pos = normalize_pos(t_data["pos"])
                        pos_source = "UWB"
                        collected_positions.append(pos)
                    else:
                        pos = None
                        pos_source = "SIM"
                    samples.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tag_id": latest_rpt["tag_id"],
                        "ranges": row_ranges,
                        "pos": pos,
                        "pos_source": pos_source,
                        "rpt_age_ms": rpt_age,
                    })

            time.sleep(0.03)

        if not qr_votes:
            continue

        winner = max(qr_votes, key=qr_votes.get)
        if winner != qr:
            print(f"[QR] zmena behem okna: '{qr}' -> '{winner}', ignoruji")
            continue

        if collected_positions:
            x, y, z = median_3d(collected_positions)
            source = "UWB"
        else:
            x = max(0.0, min(100.0, 50.0 + random.uniform(-5.0, 5.0)))
            y = max(0.0, min(100.0, 50.0 + random.uniform(-5.0, 5.0)))
            z = max(0.0, min(10.0, 5.0 + random.uniform(-1.0, 1.0)))
            source = "SIM"

        ts = datetime.now(timezone.utc).isoformat()

        raw_rows = []
        for s in samples:
            pos = s["pos"] or (None, None, None)
            raw_rows.append([
                s["timestamp"], scan_id, winner, s["tag_id"],
                *s["ranges"],
                pos[0] if pos[0] is not None else "",
                pos[1] if pos[1] is not None else "",
                pos[2] if pos[2] is not None else "",
                s["pos_source"], s["rpt_age_ms"]
            ])
        append_raw_rows(raw_rows)

        append_computed_row([
            ts, scan_id, winner, round(x, 2), round(y, 2), round(z, 2),
            source, len(samples)
        ])

        print(f"[ULOZENO] QR={winner} X={x:.2f} Y={y:.2f} Z={z:.2f} ({source}) vzorku={len(samples)}")

        with state.lock:
            state.last_save_info = (winner, x, y, z, source, int(time.time() * 1000))

        winsound.Beep(1500, 150)
        cooldown_until = int(time.time() * 1000) + SCAN_COOLDOWN_MS


# --- MAIN ------------------------------------------------------------------
def main():
    print("\n--- QR SKENER (ESP32-CAM + UWB) ---")
    print(f"Kamera: {ESP32_CAM_URL}")
    print(f"UWB:    {PC_ANL_URL}")
    print(f"RPT:    UDP {RAW_RPT_PORT}")
    print(f"Output: {OUTPUT_DIR}")
    print("[Ctrl+C] - Ukoncit program\n")

    threads = [
        threading.Thread(target=capture_thread, daemon=True),
        threading.Thread(target=rpt_listener_thread, daemon=True),
        threading.Thread(target=uwb_poller_thread, daemon=True),
        threading.Thread(target=qr_scan_thread, daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        while state.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        state.running = False
        time.sleep(0.3)
        print("\n\nUkoncuji...")


if __name__ == "__main__":
    main()
