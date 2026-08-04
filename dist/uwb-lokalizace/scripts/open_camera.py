#!/usr/bin/env python3
"""Poll PC ANL /state for the discovered ESP32-CAM IP and open it in browser."""
import os
import sys
import time
import webbrowser

import requests

PC_ANL_URL = os.environ.get("PC_ANL_URL", "http://localhost:5000/state")
POLL_INTERVAL_S = 2
TIMEOUT_S = 60


def main():
    print("Waiting for ESP32-CAM heartbeat in PC ANL...")
    deadline = time.time() + TIMEOUT_S
    cam_ip = None
    while time.time() < deadline:
        try:
            r = requests.get(PC_ANL_URL, timeout=2)
            data = r.json()
            ip = data.get("esp32_cam_ip")
            age = data.get("esp32_cam_age_ms")
            if ip and age is not None and age < 10000:
                cam_ip = ip
                break
        except Exception as e:
            print(f"  PC ANL not ready yet: {e}")
        time.sleep(POLL_INTERVAL_S)

    if not cam_ip:
        print("ERROR: ESP32-CAM not discovered by PC ANL.")
        print("Make sure the camera is powered on and flashed with the heartbeat firmware.")
        input("Press Enter to close...")
        sys.exit(1)

    url = f"http://{cam_ip}/"
    print(f"Opening camera page: {url}")
    webbrowser.open(url)


if __name__ == "__main__":
    main()
