import os
import socket
import time
import random
import winsound
import threading
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque, defaultdict

import cv2
import numpy as np
import requests
from pyzbar.pyzbar import decode


# --- AUTO-DISCOVERY ESP32-CAM ---------------------------------------------
def get_local_subnet():
    """Return the /24 subnet of the default local interface as a string."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # connect to a public address; no actual traffic is sent
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "192.168.0.1"
    net = ipaddress.ip_network(f"{ip}/24", strict=False)
    return str(net)


def _try_cam_url(url, timeout_s=1.0):
    """Try to fetch /capture from a candidate URL. Return URL if it works."""
    try:
        r = requests.get(url, timeout=timeout_s)
        if r.status_code == 200 and len(r.content) > 100:
            content_type = r.headers.get("Content-Type", "").lower()
            if "image" in content_type or r.content[:2] == b"\xff\xd8":
                return url
    except Exception:
        pass
    return None


def discover_esp32_cam_url(fallback="http://192.168.0.111/capture"):
    """Scan the local /24 subnet for an ESP32-CAM /capture endpoint."""
    if os.environ.get("ESP32_CAM_URL"):
        return os.environ.get("ESP32_CAM_URL")
    subnet = get_local_subnet()
    network = ipaddress.ip_network(subnet, strict=False)
    hosts = list(network.hosts())
    print(f"[KAMERA] hledam ESP32-CAM v siti {subnet} ({len(hosts)} adres)...")
    found = None
    with ThreadPoolExecutor(max_workers=50) as ex:
        futures = {
            ex.submit(_try_cam_url, f"http://{host}/capture", 0.6): host
            for host in hosts
        }
        for fut in as_completed(futures):
            url = fut.result()
            if url:
                found = url
                # cancel remaining futures as soon as possible
                for f in futures:
                    f.cancel()
                break
    if found:
        print(f"[KAMERA] nalezena ESP32-CAM: {found}")
        return found
    print(f"[KAMERA] ESP32-CAM nenalezena, pouzivam fallback {fallback}")
    return fallback


# --- KONFIGURACE -----------------------------------------------------------
PC_ANL_URL = "http://localhost:5000/state"
RAW_RPT_PORT = 50001
QR_EVENT_HOST = "127.0.0.1"
QR_EVENT_PORT = 50002                         # musi odpovidat pc_anl.py
TAG_ID = None                                 # None = prvni aktivni tag; jinak cislo

# Camera discovery via PC ANL heartbeats (same logic as UWB nodes).
CAMERA_DISCOVERY_INTERVAL_S = 5
CAMERA_STALE_MS = 10000

_esp32_cam_url_lock = threading.Lock()
_esp32_cam_url = None


def get_esp32_cam_url():
    """Return current ESP32-CAM capture URL, discovering one if needed."""
    global _esp32_cam_url
    with _esp32_cam_url_lock:
        if _esp32_cam_url:
            return _esp32_cam_url
    # First call: discover and cache.
    url = _discover_esp32_cam_url()
    set_esp32_cam_url(url)
    return url


def set_esp32_cam_url(url):
    global _esp32_cam_url
    with _esp32_cam_url_lock:
        if _esp32_cam_url != url:
            _esp32_cam_url = url
            print(f"[KAMERA] pouzivam URL: {url}")


def _discover_from_anl():
    """Ask pc_anl.py for the camera IP advertised by HB,CAM heartbeats."""
    try:
        r = requests.get(PC_ANL_URL, timeout=2)
        data = r.json()
        ip = data.get("esp32_cam_ip")
        age = data.get("esp32_cam_age_ms")
        if ip and age is not None and age < CAMERA_STALE_MS:
            return f"http://{ip}/capture"
    except Exception:
        pass
    return None


def _discover_esp32_cam_url():
    """Prefer PC ANL heartbeat registry, fall back to subnet scan."""
    env_url = os.environ.get("ESP32_CAM_URL")
    if env_url:
        return env_url
    anl_url = _discover_from_anl()
    if anl_url:
        print(f"[KAMERA] nalezena pres PC ANL: {anl_url}")
        return anl_url
    return discover_esp32_cam_url()


def discovery_thread():
    """Periodically refresh ESP32-CAM URL from PC ANL heartbeats."""
    while state.running:
        url = _discover_from_anl()
        if url:
            set_esp32_cam_url(url)
        time.sleep(CAMERA_DISCOVERY_INTERVAL_S)


# Cooldown po potvrzenem QR scanu (ms) - musi pokryt QR_COLLECT_MS v pc_anl.py.
QR_COOLDOWN_MS = int(os.environ.get("QR_COOLDOWN_MS", 6000))
# Délka UWB sběru v pc_anl.py (ms) - pipnuti naplánujeme na konec tohoto okna.
QR_COLLECT_MS = int(os.environ.get("QR_COLLECT_MS", 5000))
# Jak dlouho sbirame detekce pro potvrzeni QR (ms).
QR_CONFIRM_MS = int(os.environ.get("QR_CONFIRM_MS", 200))
# Kolik detekci v okne potrebujeme pro potvrzeni (majorita).
QR_CONFIRM_MIN = int(os.environ.get("QR_CONFIRM_MIN", 2))
# Frekvence stahovani snimku z ESP32-CAM (s).
CAPTURE_INTERVAL_S = float(os.environ.get("QR_CAPTURE_INTERVAL_S", 0.1))
# Timeout pro jeden HTTP pozadavek na kameru (s).
CAMERA_REQUEST_TIMEOUT_S = 5
# Zapnout agresivnejsi predzpracovani (CLAHE + Otsu) jen kdyz je to nutne;
# muze zpusobovat falesne detekce.
QR_AGGRESSIVE_DECODE = os.environ.get("QR_AGGRESSIVE_DECODE", "0") == "1"

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
    url = get_esp32_cam_url()
    print(f"[KAMERA] stahuji snimky z {url} (QVGA, kazdych {CAPTURE_INTERVAL_S*1000:.0f} ms)")
    consecutive_errors = 0
    while state.running:
        url = get_esp32_cam_url()
        try:
            response = requests.get(url, timeout=CAMERA_REQUEST_TIMEOUT_S)
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
    """Pokus o dekodovani QR z BGR snimku.

    Vychozi postup je rychly a bezpecny: primy barevny snimek a grayscale.
    Agresivnejsi metody (CLAHE, Otsu) jsou volitelne pres QR_AGGRESSIVE_DECODE,
    protoze mohou generovat falesne detekce z sumu.
    """
    if frame is None:
        return None

    # 1) primy preklad z barevneho snimku
    codes = decode(frame)
    if codes:
        return codes[0].data.decode("utf-8")

    # 2) grayscale
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    codes = decode(gray)
    if codes:
        return codes[0].data.decode("utf-8")

    if not QR_AGGRESSIVE_DECODE:
        return None

    # 3) volitelne agresivni predzpracovani
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    codes = decode(enhanced)
    if codes:
        return codes[0].data.decode("utf-8")

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
    qr_history = deque()
    pending_beep_end = 0

    def get_stable_qr(now_ms):
        if len(qr_history) < QR_CONFIRM_MIN:
            return None
        votes = defaultdict(int)
        for _, code in qr_history:
            votes[code] += 1
        winner = max(votes, key=votes.get)
        # majority = more than half
        if votes[winner] > len(qr_history) / 2:
            return winner
        return None

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

        # End-of-collection beep if scheduled.
        if pending_beep_end and now_ms >= pending_beep_end:
            winsound.Beep(700, 150)
            pending_beep_end = 0

        # During cooldown ignore all QR codes to prevent duplicates.
        if now_ms < cooldown_until:
            qr_history.clear()
            continue

        qr = decode_latest_qr(frame)
        if qr:
            qr_history.append((now_ms, qr))

        # Drop old detections outside confirmation window.
        while qr_history and now_ms - qr_history[0][0] > QR_CONFIRM_MS:
            qr_history.popleft()

        stable_qr = get_stable_qr(now_ms)
        if stable_qr is None:
            continue

        # Confirmed QR - accept it.
        print(f"\n[QR] potvrzen '{stable_qr}', odesilam do PC ANL...")
        winsound.Beep(1800, 80)  # rychly, vyrazny pipnuti
        notify_pc_anl(stable_qr)
        qr_history.clear()

        with state.lock:
            state.last_qr_info = (stable_qr, now_ms)

        # Lockout long enough to cover pc_anl.py's UWB collection.
        cooldown_until = now_ms + QR_COOLDOWN_MS
        pending_beep_end = now_ms + QR_COLLECT_MS


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
    print(f"Kamera: {get_esp32_cam_url()}")
    print(f"UWB:    {PC_ANL_URL}")
    print(f"RPT:    UDP {RAW_RPT_PORT}")
    print("Data se ukladaji do session CSV pres PC ANL.")
    print("[Ctrl+C] - Ukoncit program\n")

    threads = [
        threading.Thread(target=discovery_thread, daemon=True),
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
