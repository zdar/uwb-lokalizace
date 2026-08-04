"""Laptop webcam QR scanner for the PC ANL GUI.

This is an alternative to the ESP32-CAM QR scanner (esp-cam/qr_scanner.py).
It captures frames from the local webcam, decodes QR codes with pyzbar, and
reports detected codes to pc_anl.py so the user can start sampling manually
from the Měření page.

The scanner only *detects* QR codes. It does NOT start UWB collections on its
own. The GUI shows the detected code and the user clicks a button to start
sampling, just like the manual QR trigger.

Configuration is done through environment variables:
  WEBCAM_INDEX      camera index to try first (default 0)
  WEBCAM_WIDTH      requested frame width (default 640)
  WEBCAM_HEIGHT     requested frame height (default 480)
  WEBCAM_FPS        requested FPS (default 30)
  WEBCAM_PREVIEW    "1" to show the OpenCV preview window (default 1)
  QR_EVENT_HOST     pc_anl.py host for QR events (default 127.0.0.1)
  QR_EVENT_PORT     pc_anl.py port for QR events (default 50002)
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

QR_CONFIRM_MS = int(os.environ.get("QR_CONFIRM_MS", 200))
QR_CONFIRM_MIN = int(os.environ.get("QR_CONFIRM_MIN", 2))
QR_AGGRESSIVE_DECODE = os.environ.get("QR_AGGRESSIVE_DECODE", "0") == "1"

# How often to re-report the same QR code if it stays in front of the camera.
QR_REPEAT_MS = int(os.environ.get("QR_REPEAT_MS", 2000))

WEBCAM_INDEX = int(os.environ.get("WEBCAM_INDEX", 0))
WEBCAM_WIDTH = int(os.environ.get("WEBCAM_WIDTH", 640))
WEBCAM_HEIGHT = int(os.environ.get("WEBCAM_HEIGHT", 480))
WEBCAM_FPS = int(os.environ.get("WEBCAM_FPS", 30))
WEBCAM_PREVIEW = os.environ.get("WEBCAM_PREVIEW", "1") == "1"

HEARTBEAT_INTERVAL_S = 5.0


def send_event(payload):
    """Send a UDP payload to pc_anl.py."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload.encode("utf-8"), (QR_EVENT_HOST, QR_EVENT_PORT))
    except Exception as e:
        print(f"\n[WEBCAM] failed to send event: {e}")


def notify_detected(qr_code):
    """Report a detected QR code to pc_anl.py without starting a collection."""
    send_event(f"QR_DETECT,{qr_code}")


def send_heartbeat():
    """Send an empty QR heartbeat so pc_anl.py keeps qr_connected true."""
    send_event("QR,")


def decode_all(frame):
    """Return a list of (code, rect) tuples decoded from a BGR frame.

    The default path is fast: try the color frame first, then grayscale.
    Aggressive preprocessing (CLAHE + Otsu) is optional because it can
    increase false detections on noisy webcam images.
    """
    if frame is None:
        return []

    candidates = []

    def add_results(img):
        for code in decode(img):
            try:
                text = code.data.decode("utf-8")
                rect = code.rect
                candidates.append((text, rect))
            except Exception:
                pass

    add_results(frame)

    if not candidates:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        add_results(gray)

    if not candidates and QR_AGGRESSIVE_DECODE:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        add_results(enhanced)
        if not candidates:
            _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            add_results(binary)

    # Deduplicate by code text, keeping the first rect.
    seen = set()
    unique = []
    for text, rect in candidates:
        if text not in seen:
            seen.add(text)
            unique.append((text, rect))
    return unique


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


def draw_hud(frame, detected_qr, previous_qr, fps):
    """Draw the on-camera HUD inspired by blueprint_webcam.py."""
    if frame is None:
        return frame

    h, w, _ = frame.shape

    # Top bar with current status.
    if detected_qr:
        status_text = f"DETEKOVANO: {detected_qr}"
        status_color = (0, 255, 0)
    else:
        status_text = "NASKENUJTE QR KOD"
        status_color = (0, 255, 255)

    cv2.rectangle(frame, (0, 0), (w, 34), (0, 0, 0), -1)
    cv2.putText(frame, status_text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, status_color, 2, cv2.LINE_AA)

    # Previous QR below the status bar.
    prev_text = f"Predchozi: {previous_qr}" if previous_qr else "Predchozi: -"
    cv2.rectangle(frame, (0, 36), (w, 66), (0, 0, 0), -1)
    cv2.putText(frame, prev_text, (10, 58), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (200, 200, 200), 1, cv2.LINE_AA)

    # FPS counter in the bottom-right corner.
    fps_text = f"FPS: {fps:.1f}"
    (tw, th), _ = cv2.getTextSize(fps_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(frame, (w - tw - 15, h - th - 15), (w, h), (0, 0, 0), -1)
    cv2.putText(frame, fps_text, (w - tw - 10, h - 5), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (0, 255, 0), 1, cv2.LINE_AA)

    return frame


def draw_qr_rectangle(frame, qr_rect, label):
    """Draw a rectangle around the detected QR code and a label above it."""
    if frame is None or qr_rect is None:
        return frame
    x, y, w, h = qr_rect
    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 3)
    cv2.putText(frame, label, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (0, 255, 0), 2, cv2.LINE_AA)
    return frame


def heartbeat_loop(running):
    """Send empty QR heartbeats so pc_anl.py keeps qr_connected true."""
    while running.is_set():
        send_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL_S)


def main():
    print("--- Webcam QR Scanner (detect-only) ---")
    print(f"Target PC ANL: {QR_EVENT_HOST}:{QR_EVENT_PORT}")
    print("Detected QR codes are shown in the GUI; sampling is started manually.")
    print("Press 'q' in the preview window or Ctrl+C to exit.\n")

    cap = open_webcam()
    if cap is None:
        print("[WEBCAM] ERROR: no webcam found")
        return 1

    running = threading.Event()
    running.set()
    threading.Thread(target=heartbeat_loop, args=(running,), daemon=True).start()

    qr_history = deque()
    frame_count = 0
    last_fps_time = time.time()
    fps = 0.0

    detected_qr = None
    previous_qr = None
    last_reported_qr = None
    last_reported_ms = 0

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

            codes = decode_all(frame)

            # Track the first detected code.
            current_code = None
            current_rect = None
            if codes:
                current_code, current_rect = codes[0]
                qr_history.append((now_ms, current_code))

            # Drop old detections outside the confirmation window.
            while qr_history and now_ms - qr_history[0][0] > QR_CONFIRM_MS:
                qr_history.popleft()

            stable_qr = get_stable_qr(now_ms)

            # When a stable QR is confirmed, update detected/previous and notify GUI.
            if stable_qr:
                if detected_qr and detected_qr != stable_qr:
                    previous_qr = detected_qr
                detected_qr = stable_qr

                # Notify the GUI, but throttle repeats of the same code.
                if stable_qr != last_reported_qr or now_ms - last_reported_ms >= QR_REPEAT_MS:
                    print(f"\n[QR] detected '{stable_qr}', reporting to PC ANL...")
                    winsound.Beep(1500, 150)
                    notify_detected(stable_qr)
                    last_reported_qr = stable_qr
                    last_reported_ms = now_ms

                qr_history.clear()

            # If no code is currently visible, clear the live detection but keep previous.
            if not current_code:
                detected_qr = None

            # Draw the HUD and QR rectangle.
            display = frame.copy()
            display = draw_hud(display, detected_qr, previous_qr, fps)
            if current_rect and detected_qr:
                display = draw_qr_rectangle(display, current_rect, detected_qr)

            if WEBCAM_PREVIEW:
                cv2.imshow("Webcam QR Scanner", display)
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
