"""Laptop webcam QR scanner for the PC ANL GUI.

This is an alternative to the ESP32-CAM QR scanner (esp-cam/qr_scanner.py).
It captures frames from the local webcam, decodes QR codes with pyzbar, and
sends the same UDP "QR,<code>" events to pc_anl.py. It is meant to work on
any laptop with a built-in or USB webcam.

Configuration is done through environment variables:
  WEBCAM_INDEX      camera index to try first (default 0)
  WEBCAM_WIDTH      requested frame width (default 640)
  WEBCAM_HEIGHT     requested frame height (default 480)
  WEBCAM_FPS        requested FPS (default 30)
  WEBCAM_PREVIEW    "1" to show the OpenCV preview window (default 1)
  QR_EVENT_HOST     pc_anl.py host for QR events (default 127.0.0.1)
  QR_EVENT_PORT     pc_anl.py port for QR events (default 50002)
  QR_COLLECT_MS     length of the UWB collection window (default 5000)
  QR_COOLDOWN_MS    lockout after a confirmed scan (default 6000)
  QR_CONFIRM_MS     confirmation window length (default 200)
  QR_CONFIRM_MIN    minimum detections for confirmation (default 2)
  QR_AGGRESSIVE_DECODE  "1" to enable CLAHE + Otsu preprocessing (default 0)
"""

import os
import socket
import sys
import threading
import time
from collections import deque, defaultdict

import cv2
import numpy as np
from pyzbar.pyzbar import decode

# winsound is Windows-only; make the beep a no-op on other platforms.
try:
    import winsound
except ImportError:  # pragma: no cover
    class _WinsoundStub:
        @staticmethod
        def Beep(_frequency, _duration):
            pass
    winsound = _WinsoundStub()


# --- CONFIGURATION ---------------------------------------------------------
QR_EVENT_HOST = os.environ.get("QR_EVENT_HOST", "127.0.0.1")
QR_EVENT_PORT = int(os.environ.get("QR_EVENT_PORT", 50002))

QR_COLLECT_MS = int(os.environ.get("QR_COLLECT_MS", 5000))
QR_COOLDOWN_MS = int(os.environ.get("QR_COOLDOWN_MS", 6000))
QR_CONFIRM_MS = int(os.environ.get("QR_CONFIRM_MS", 200))
QR_CONFIRM_MIN = int(os.environ.get("QR_CONFIRM_MIN", 2))
QR_AGGRESSIVE_DECODE = os.environ.get("QR_AGGRESSIVE_DECODE", "0") == "1"

WEBCAM_INDEX = int(os.environ.get("WEBCAM_INDEX", 0))
WEBCAM_WIDTH = int(os.environ.get("WEBCAM_WIDTH", 640))
WEBCAM_HEIGHT = int(os.environ.get("WEBCAM_HEIGHT", 480))
WEBCAM_FPS = int(os.environ.get("WEBCAM_FPS", 30))
WEBCAM_PREVIEW = os.environ.get("WEBCAM_PREVIEW", "1") == "1"

HEARTBEAT_INTERVAL_S = 5.0


def notify_pc_anl(qr_code=""):
    """Send a QR event (or empty heartbeat) to pc_anl.py."""
    try:
        payload = f"QR,{qr_code}".encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (QR_EVENT_HOST, QR_EVENT_PORT))
    except Exception as e:
        print(f"\n[WEBCAM] failed to notify PC ANL: {e}")


def decode_frame(frame):
    """Try to decode a QR code from a BGR frame.

    The default path is fast: try the color frame first, then grayscale.
    Aggressive preprocessing (CLAHE + Otsu) is optional because it can
    increase false detections on noisy webcam images.
    """
    if frame is None:
        return None

    codes = decode(frame)
    if codes:
        return codes[0].data.decode("utf-8")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    codes = decode(gray)
    if codes:
        return codes[0].data.decode("utf-8")

    if not QR_AGGRESSIVE_DECODE:
        return None

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


def open_webcam():
    """Open the first available webcam.

    The requested WEBCAM_INDEX is tried first, then index 0, then indices 1-4.
    On Windows the DirectShow backend is preferred because it handles exposure
    and resolution selection more reliably than the default Media Foundation
    backend for many laptop webcams.
    """
    indices = [WEBCAM_INDEX]
    if WEBCAM_INDEX != 0:
        indices.append(0)
    for i in range(1, 5):
        if i not in indices:
            indices.append(i)

    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY

    for idx in indices:
        cap = cv2.VideoCapture(idx, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, WEBCAM_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, WEBCAM_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, WEBCAM_FPS)
            ok, frame = cap.read()
            if ok and frame is not None:
                actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                print(f"[WEBCAM] opened camera {idx} at {actual_w}x{actual_h}")
                return cap
        cap.release()

    return None


def draw_overlay(frame, text):
    """Draw a small status label in the top-left corner of the preview."""
    if frame is None:
        return frame
    h, _, _ = frame.shape
    y = h - 20
    cv2.rectangle(frame, (10, y - 25), (400, y + 10), (0, 0, 0), -1)
    cv2.putText(frame, text, (15, y), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (0, 255, 0), 1, cv2.LINE_AA)
    return frame


def heartbeat_loop(running):
    """Send empty QR heartbeats so pc_anl.py keeps qr_connected true."""
    while running.is_set():
        notify_pc_anl("")
        time.sleep(HEARTBEAT_INTERVAL_S)


def main():
    print("--- Webcam QR Scanner ---")
    print(f"Target PC ANL: {QR_EVENT_HOST}:{QR_EVENT_PORT}")
    print("Press 'q' in the preview window or Ctrl+C to exit.\n")

    cap = open_webcam()
    if cap is None:
        print("[WEBCAM] ERROR: no webcam found")
        return 1

    running = threading.Event()
    running.set()
    threading.Thread(target=heartbeat_loop, args=(running,), daemon=True).start()

    cooldown_until = 0
    pending_beep_end = 0
    qr_history = deque()
    frame_count = 0
    last_fps_time = time.time()
    last_qr_info = None

    def get_stable_qr(now_ms):
        if len(qr_history) < QR_CONFIRM_MIN:
            return None
        votes = defaultdict(int)
        for _, code in qr_history:
            votes[code] += 1
        winner = max(votes, key=votes.get)
        # Require a simple majority to confirm.
        if votes[winner] > len(qr_history) / 2:
            return winner
        return None

    try:
        while running.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.02)
                continue

            now_ms = int(time.time() * 1000)
            frame_count += 1

            if time.time() - last_fps_time >= 1.0:
                fps = frame_count / (time.time() - last_fps_time)
                frame_count = 0
                last_fps_time = time.time()
                if last_qr_info:
                    age = (now_ms - last_qr_info[1]) / 1000.0
                    status = f"FPS {fps:.1f} | last QR: {last_qr_info[0]} ({age:.1f}s ago)"
                else:
                    status = f"FPS {fps:.1f} | waiting for QR..."
                print(f"\r{status}", end="", flush=True)

            overlay_text = "waiting for QR..."

            # End-of-collection beep.
            if pending_beep_end and now_ms >= pending_beep_end:
                winsound.Beep(700, 150)
                pending_beep_end = 0

            if now_ms < cooldown_until:
                qr_history.clear()
                overlay_text = "cooldown..."
            else:
                qr = decode_frame(frame)
                if qr:
                    qr_history.append((now_ms, qr))
                while qr_history and now_ms - qr_history[0][0] > QR_CONFIRM_MS:
                    qr_history.popleft()

                stable_qr = get_stable_qr(now_ms)
                if stable_qr:
                    print(f"\n[QR] confirmed '{stable_qr}', notifying PC ANL...")
                    winsound.Beep(1800, 80)
                    notify_pc_anl(stable_qr)
                    last_qr_info = (stable_qr, now_ms)
                    qr_history.clear()
                    cooldown_until = now_ms + QR_COOLDOWN_MS
                    pending_beep_end = now_ms + QR_COLLECT_MS
                    overlay_text = f"sent: {stable_qr}"
                elif qr_history:
                    overlay_text = f"confirming: {qr_history[-1][1]}"

            if WEBCAM_PREVIEW:
                draw_overlay(frame, overlay_text)
                cv2.imshow("Webcam QR Scanner", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    running.clear()
                    break

    except KeyboardInterrupt:
        pass
    finally:
        running.clear()
        cap.release()
        cv2.destroyAllWindows()
        print("\n[WEBCAM] exiting")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
