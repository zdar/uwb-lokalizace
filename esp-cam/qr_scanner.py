import cv2
import json
import os
import time
import random
import winsound
import threading
import statistics
from datetime import datetime, timezone
from collections import defaultdict

import numpy as np
import requests
from pyzbar.pyzbar import decode

# --- KONFIGURACE -----------------------------------------------------------
ESP32_CAM_STREAM = "http://192.168.0.159:81/stream"
PC_ANL_URL = "http://localhost:5000/state"
TAG_ID = None                                 # None = prvni aktivni tag; jinak cislo

# Jak dlouho po detekci QR sbirame vzorky pro median (ms).
SAMPLE_WINDOW_MS = 500
# Cooldown mezi dvema ruznymi QR kody (ms).
QR_COOLDOWN_MS = 1500

# Kam se ukladaji scan soubory.
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Jednoduche "sifrovani" QR obsahu pomoci XOR s klicem. Zmen klic v produkci,
# nebo nahrad plnym sifrovanim ( Fernet z cryptography ).
QR_XOR_KEY = 0x7A


# --- SDILENY STAV ----------------------------------------------------------
class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.uwb_state = None       # posledni /state odpoved z PC ANL
        self.last_save_info = None  # (qr, x, y, z, source, cas)
        self.running = True


state = SharedState()


# --- ULOZISTE --------------------------------------------------------------
def xor_encrypt(text: str, key: int) -> str:
    """Jednoducha XOR maska pro citlivy obsah QR."""
    return "".join(chr(ord(c) ^ key) for c in text)


def output_filename():
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return os.path.join(OUTPUT_DIR, f"scans_{today}.jsonl")


def save_scan(record: dict):
    path = output_filename()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[ULOZENO] {path}: QR={record['qr_raw']}")


# --- UWB POZICE A RAW DATA -------------------------------------------------
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


# --- KAMERA ----------------------------------------------------------------
def capture_thread():
    cap = cv2.VideoCapture(ESP32_CAM_STREAM)
    if not cap.isOpened():
        print(f"[KAMERA] nelze otevrit stream {ESP32_CAM_STREAM}")
        state.running = False
        return
    print(f"[KAMERA] stream pripojen: {ESP32_CAM_STREAM}")

    while state.running:
        ret, frame = cap.read()
        if ret and frame is not None:
            with state.lock:
                state.frame = frame
    cap.release()


# --- QR S OVERSAMPLINGEM ---------------------------------------------------
def decode_latest_qr(frame):
    codes = decode(frame)
    if not codes:
        return None
    # Vezmeme prvni uspesne rozpoznany kod.
    return codes[0].data.decode("utf-8")


def median_3d(points):
    if not points:
        return None
    return (
        statistics.median([p[0] for p in points]),
        statistics.median([p[1] for p in points]),
        statistics.median([p[2] for p in points]),
    )


def qr_oversample_thread():
    last_qr_time = 0
    last_qr_text = None
    cooldown_until = 0

    while state.running:
        now_ms = int(time.time() * 1000)

        with state.lock:
            frame = state.frame
            uwb_data = state.uwb_state

        if frame is None:
            time.sleep(0.02)
            continue

        qr = decode_latest_qr(frame)
        if qr is None or now_ms < cooldown_until:
            time.sleep(0.05)
            continue

        # Zacatek oversampling okna.
        print(f"[QR] detekovan '{qr}', sbiram vzorky {SAMPLE_WINDOW_MS}ms...")
        samples = []
        qr_votes = defaultdict(int)
        window_end = now_ms + SAMPLE_WINDOW_MS

        while int(time.time() * 1000) < window_end and state.running:
            with state.lock:
                f = state.frame
                uwb = state.uwb_state

            if f is not None:
                q = decode_latest_qr(f)
                if q:
                    qr_votes[q] += 1
                    t_data = pick_tag_data(uwb)
                    if t_data:
                        pos = normalize_pos(t_data.get("pos"))
                        if pos:
                            samples.append({
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "pos": pos,
                                "ranges": {str(aid): float(r) for aid, r in t_data.get("ranges", {}).items()},
                            })
            time.sleep(0.03)

        if not qr_votes:
            continue

        # Vyber nejcastejsi QR kod v okne.
        winner = max(qr_votes, key=qr_votes.get)
        if winner != qr:
            print(f"[QR] zmena behem okna: '{qr}' -> '{winner}', ignoruji")
            continue

        # Vypocti median pozice ze vzorku.
        positions = [s["pos"] for s in samples if s.get("pos")]
        if positions:
            x, y, z = median_3d(positions)
            source = "UWB"
        else:
            x = max(0.0, min(100.0, 50.0 + random.uniform(-5.0, 5.0)))
            y = max(0.0, min(100.0, 50.0 + random.uniform(-5.0, 5.0)))
            z = max(0.0, min(10.0, 5.0 + random.uniform(-1.0, 1.0)))
            source = "SIM"

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "qr_raw": winner,
            "qr_encrypted": xor_encrypt(winner, QR_XOR_KEY),
            "computed": {
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 2),
                "source": source,
                "samples_used": len(positions),
            },
            "raw_samples": samples,
            "anchors": {str(aid): list(p) for aid, p in (uwb_data or {}).get("anchors", {}).items()},
        }

        save_scan(record)

        with state.lock:
            state.last_save_info = (winner, x, y, z, source, int(time.time() * 1000))

        winsound.Beep(1500, 150)
        last_qr_text = winner
        cooldown_until = int(time.time() * 1000) + QR_COOLDOWN_MS


# --- HUD -------------------------------------------------------------------
def draw_hud(display_frame, uwb_data, last_save):
    h, w = display_frame.shape[:2]
    BAR_H = 120
    canvas = np.zeros((h + BAR_H, w, 3), dtype=np.uint8)
    canvas[BAR_H:, :] = display_frame

    # Hlavni souradnice
    t_data = pick_tag_data(uwb_data)
    if t_data and t_data.get("pos"):
        x, y, z = normalize_pos(t_data["pos"])
        line1 = f"UWB: X={x:.2f}  Y={y:.2f}  Z={z:.2f}"
        color = (0, 255, 0)
    else:
        line1 = "UWB: ---  (SIM fallback)"
        color = (0, 165, 255)
    cv2.putText(canvas, line1, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    if last_save:
        qr, x, y, z, src, ts = last_save
        age_s = (int(time.time() * 1000) - ts) / 1000.0
        cv2.putText(canvas, f"POSLEDNI QR: {qr}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(canvas, f"ULOZENO: X={x:.2f} Y={y:.2f} Z={z:.2f} ({src}) pred {age_s:.1f}s",
                    (10, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    else:
        cv2.putText(canvas, "UKAZ QR KOD...", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

    cv2.putText(canvas, "[Q] konec", (w - 110, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
    return canvas


# --- MAIN ------------------------------------------------------------------
def main():
    print("\n--- QR SKENER (ESP32-CAM + UWB) ---")
    print(f"Stream: {ESP32_CAM_STREAM}")
    print(f"UWB:    {PC_ANL_URL}")
    print(f"Output: {OUTPUT_DIR}")
    print("[Q] - Ukoncit program\n")

    threads = [
        threading.Thread(target=capture_thread, daemon=True),
        threading.Thread(target=uwb_poller_thread, daemon=True),
        threading.Thread(target=qr_oversample_thread, daemon=True),
    ]
    for t in threads:
        t.start()

    timeout = time.time() + 10
    while state.frame is None and time.time() < timeout and state.running:
        time.sleep(0.05)

    if state.frame is None:
        print("[CHYBA] Nepodarilo se ziskat obraz.")
        state.running = False
        return

    SCALE = 1.2
    window_title = "QR Skener + UWB"
    cv2.namedWindow(window_title, cv2.WINDOW_NORMAL)

    while state.running:
        with state.lock:
            frame = state.frame.copy() if state.frame is not None else None
            uwb = state.uwb_state
            last_save = state.last_save_info

        if frame is None:
            time.sleep(0.01)
            continue

        display = cv2.resize(frame, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_LINEAR)
        canvas = draw_hud(display, uwb, last_save)
        cv2.imshow(window_title, canvas)

        if (cv2.waitKey(1) & 0xFF) == ord("q"):
            state.running = False

    cv2.destroyAllWindows()
    print("\nUkoncuji...")


if __name__ == "__main__":
    main()
