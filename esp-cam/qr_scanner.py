import os
import socket
import time
import random
import winsound
import threading
from collections import deque

import cv2
import numpy as np
import requests
from pyzbar.pyzbar import decode

# --- KONFIGURACE -----------------------------------------------------------
ESP32_CAM_URL = os.environ.get(
    "ESP32_CAM_URL", "http://192.168.0.159/capture"
)
PC_ANL_URL = "http://localhost:5000/state"
RAW_RPT_PORT = 50001
QR_EVENT_HOST = "127.0.0.1"
QR_EVENT_PORT = 50002                         # musi odpovidat pc_anl.py
TAG_ID = None                                 # None = prvni aktivni tag; jinak cislo

# Jak dlouho po detekci QR sbirame vzorky pro median (ms).
SAMPLE_WINDOW_MS = int(os.environ.get("QR_SAMPLE_WINDOW_MS", 5000))
# Cooldown mezi dvema skeny (ms).
SCAN_COOLDOWN_MS = int(os.environ.get("QR_SCAN_COOLDOWN_MS", 1000))
# Frekvence stahovani snimku z ESP32-CAM (s).
CAPTURE_INTERVAL_S = float(os.environ.get("QR_CAPTURE_INTERVAL_S", 0.1))
# Timeout pro jeden HTTP pozadavek na kameru (s).
CAMERA_REQUEST_TIMEOUT_S = 5

ANCHOR_COUNT = 10


# --- SDILENY STAV ----------------------------------------------------------
RPT_HISTORY_MAXLEN = 2000
# Velka hodnota, aby kamera zustala "pripravena" i mezi pomalymi snimky.
# Az kdyz se opravdu vypne, UI po teto dobe zcervena.
CAMERA_TIMEOUT_MS = 60000


class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.uwb_state = None
        self.latest_rpt = None
        self.rpt_history = deque(maxlen=RPT_HISTORY_MAXLEN)
        self.last_qr_info = None
        self.camera_last_frame_ms = 0
        self.camera_connected = False
        self.running = True


state = SharedState()


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
            state.rpt_history.append({
                "timestamp": now_ms,
                "tag_id": tid,
                "ranges": dict(ranges),
            })
    sock.close()


# --- KAMERA ----------------------------------------------------------------
def capture_thread():
    print(f"[KAMERA] stahuji snimky z {ESP32_CAM_URL} (QVGA, kazdych {CAPTURE_INTERVAL_S*1000:.0f} ms)")
    consecutive_errors = 0
    while state.running:
        try:
            response = requests.get(ESP32_CAM_URL, timeout=CAMERA_REQUEST_TIMEOUT_S)
            if response.status_code == 200:
                img_array = np.frombuffer(response.content, dtype=np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if frame is not None:
                    with state.lock:
                        state.frame = frame
                        state.camera_last_frame_ms = int(time.time() * 1000)
                        state.camera_connected = True
                    consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= 3 or consecutive_errors % 10 == 0:
                print(f"[KAMERA] chyba: {e}")
        time.sleep(CAPTURE_INTERVAL_S)


def decode_latest_qr(frame):
    """Pokus o dekodovani QR z BGR snimku s nekolika predzpracovanimi.

    ESP32-CAM casto posila snimky s nizkym kontrastem nebo sikmo natoceny
    QR kod. Zkusime proto primy BGR preklad, grayscale + CLAHE a Otsu
    prahovani, abychom detekci urychlili a zvysili uspesnost.
    """
    if frame is None:
        return None

    # 1) primy preklad z barevneho snimku
    codes = decode(frame)
    if codes:
        return codes[0].data.decode("utf-8")

    # 2) grayscale + CLAHE (lokalni kontrast)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    codes = decode(gray)
    if codes:
        return codes[0].data.decode("utf-8")

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    codes = decode(enhanced)
    if codes:
        return codes[0].data.decode("utf-8")

    # 3) Otsu prahovani jako posledni pokus
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    codes = decode(binary)
    if codes:
        return codes[0].data.decode("utf-8")

    return None


# --- QR DETEKCE ------------------------------------------------------------
def print_status(uwb_data, last_qr, fps):
    t_data = pick_tag_data(uwb_data)
    if t_data and t_data.get("pos"):
        x, y, z = normalize_pos(t_data["pos"])
        pos_line = f"UWB: X={x:.2f} Y={y:.2f} Z={z:.2f}"
    else:
        pos_line = "UWB: ---"

    if last_qr:
        qr, ts = last_qr
        age_s = (int(time.time() * 1000) - ts) / 1000.0
        save_line = f"| posledni: {qr} pred {age_s:.1f}s"
    else:
        save_line = "| cekam na QR..."

    print(f"\r[{fps:.1f} FPS] {pos_line} {save_line}", end="", flush=True)


def qr_scan_thread():
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
                last_qr = state.last_qr_info
            print_status(uwb, last_qr, fps)

        qr = decode_latest_qr(frame)
        if qr is None or now_ms < cooldown_until:
            continue

        print(f"\n[QR] detekovan '{qr}', odesilam do PC ANL...")
        winsound.Beep(1500, 150)
        notify_pc_anl(qr)

        # Pockame na vzorkovaci okno, aby se stejny QR nescanoval opakovane
        # a uzivatel dostal zpetnou vazbu. Ulozeni resi PC ANL.
        window_end = now_ms + SAMPLE_WINDOW_MS
        while int(time.time() * 1000) < window_end and state.running:
            time.sleep(0.05)

        winsound.Beep(700, 250)  # jiny ton = okno dokonceno
        print(f"[QR] '{qr}' - vzorkovani dokonceno ({SAMPLE_WINDOW_MS}ms)")

        with state.lock:
            state.last_qr_info = (qr, int(time.time() * 1000))

        cooldown_until = int(time.time() * 1000) + SCAN_COOLDOWN_MS


# --- KOMUNIKACE S PC ANL ---------------------------------------------------
def notify_pc_anl(qr_code):
    """Posli UDP udalost QR,<kod> do pc_anl.py (port 50002)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(f"QR,{qr_code}".encode("utf-8"), (QR_EVENT_HOST, QR_EVENT_PORT))
        sock.close()
    except Exception as e:
        print(f"\n[QR] chyba notifikace PC ANL: {e}")


def qr_heartbeat_thread():
    """Pravidelne posila prazdnou QR udalost, pouze kdyz kamera nedavno poslala snimek."""
    last_connected = None
    while state.running:
        now_ms = int(time.time() * 1000)
        with state.lock:
            last_frame = state.camera_last_frame_ms
        connected = (last_frame > 0) and (now_ms - last_frame < CAMERA_TIMEOUT_MS)
        with state.lock:
            state.camera_connected = connected
        if last_connected is None or connected != last_connected:
            print(f"[KAMERA] stav: {'pripojena' if connected else 'ODPOJENA'}")
            last_connected = connected
        if connected:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(b"QR,", (QR_EVENT_HOST, QR_EVENT_PORT))
                sock.close()
            except Exception:
                pass
        time.sleep(5.0)


# --- MAIN ------------------------------------------------------------------
def main():
    print("\n--- QR SKENER (ESP32-CAM + UWB) ---")
    print(f"Kamera: {ESP32_CAM_URL}")
    print(f"UWB:    {PC_ANL_URL}")
    print(f"RPT:    UDP {RAW_RPT_PORT}")
    print("Data se ukladaji do session CSV pres PC ANL.")
    print("[Ctrl+C] - Ukoncit program\n")

    threads = [
        threading.Thread(target=capture_thread, daemon=True),
        threading.Thread(target=rpt_listener_thread, daemon=True),
        threading.Thread(target=uwb_poller_thread, daemon=True),
        threading.Thread(target=qr_scan_thread, daemon=True),
        threading.Thread(target=qr_heartbeat_thread, daemon=True),
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
