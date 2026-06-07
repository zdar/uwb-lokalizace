#!/usr/bin/env python3
"""
OTA Flash All — Kryl branch
===========================
Builds the unified firmware once, discovers every node on the RTLS WiFi network,
opens a 2-minute OTA window on each, then flashes them all in parallel.

Usage
-----
    # 1. Connect your PC to the RTLS-NET-XXXX WiFi
    # 2. Run:
    python scripts/ota_flash_all.py

    # Or flash a specific node only:
    python scripts/ota_flash_all.py --ip 192.168.4.2

Dependencies
------------
    pip install platformio
    (PlatformIO Core must be in PATH)
"""

import argparse
import os
import socket
import subprocess
import sys
import time
import threading
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
UDP_PORT = 50000
OTA_PASSWORD = "rtlsota12"


def get_broadcast_address():
    """Auto-detect the broadcast address of the current network interface."""
    try:
        # Create a UDP socket and connect to a public address to determine
        # which interface/route would be used for outbound traffic.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        # Parse the local IP to compute the /24 broadcast address.
        # This assumes a typical home network is /24 (255.255.255.0).
        parts = local_ip.split(".")
        broadcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
        print(f"[NET] Local IP: {local_ip}  Broadcast: {broadcast}")
        return broadcast
    except Exception as e:
        print(f"[NET] Could not auto-detect broadcast ({e}), falling back to 192.168.4.255")
        return "192.168.4.255"


BROADCAST = get_broadcast_address()
OTA_WINDOW_S = 120  # must match OTA_TIMEOUT_MS in firmware
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
FIRMWARE_BIN = PROJECT_ROOT / ".pio" / "build" / "esp32s3-ota" / "firmware.bin"

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_nodes(timeout=3.0):
    """Send PING broadcast and collect PONG replies."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    sock.bind(("0.0.0.0", 0))

    nodes = {}
    start = time.time()
    sock.sendto(b"PING", (BROADCAST, UDP_PORT))

    while time.time() - start < timeout:
        try:
            data, addr = sock.recvfrom(256)
            text = data.decode("utf-8", errors="ignore").strip()
            # PONG,<uwb_index>,<current_role>,<network_id>,<millis>
            if text.startswith("PONG,"):
                parts = text.split(",")
                if len(parts) >= 4:
                    ip = addr[0]
                    idx = int(parts[1])
                    role = int(parts[2])
                    netid = int(parts[3])
                    nodes[ip] = {"id": idx, "role": role, "netid": netid}
                    print(f"  [DISC] {ip} -> ID={idx} role={role} net={netid}")
        except socket.timeout:
            break
        except Exception as e:
            print(f"  [DISC] recv error: {e}")

    sock.close()
    return nodes


def enable_ota(ip, password=OTA_PASSWORD, timeout=2.0):
    """Send UDP OTA command to open the 2-minute flash window."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    msg = f"OTA,{password}".encode()
    sock.sendto(msg, (ip, UDP_PORT))
    try:
        data, _ = sock.recvfrom(256)
        text = data.decode("utf-8", errors="ignore").strip()
        if text.startswith("ACK,OTA"):
            print(f"  [OTA] {ip} window OPEN")
            return True
        else:
            print(f"  [OTA] {ip} rejected: {text}")
            return False
    except socket.timeout:
        print(f"  [OTA] {ip} no ACK (timeout)")
        return False
    finally:
        sock.close()


def set_node_id(ip, new_id, timeout=2.0):
    """Remotely configure a node's UWB index via UDP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    msg = f"ID,{new_id}".encode()
    sock.sendto(msg, (ip, UDP_PORT))
    try:
        data, _ = sock.recvfrom(256)
        text = data.decode("utf-8", errors="ignore").strip()
        if text.startswith("ACK,ID"):
            print(f"  [ID] {ip} -> ID={new_id} (rebooting)")
            return True
        else:
            print(f"  [ID] {ip} rejected: {text}")
            return False
    except socket.timeout:
        print(f"  [ID] {ip} no ACK (timeout)")
        return False
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Flashing
# ---------------------------------------------------------------------------

def is_wsl():
    """Check if running inside Windows Subsystem for Linux."""
    try:
        return "microsoft" in os.uname().release.lower() or os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop")
    except AttributeError:
        return False


def get_windows_wifi_ip():
    """Get Windows host WiFi IP from inside WSL."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-Command",
             "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -like '*Wi-Fi*' -or $_.InterfaceAlias -like '*Wireless*' -or $_.InterfaceAlias -like '*WLAN*' }).IPAddress"],
            capture_output=True, text=True, timeout=5
        )
        ip = result.stdout.strip().split("\n")[0].strip()
        if ip:
            print(f"[WSL] Detected Windows WiFi IP: {ip}")
            return ip
    except Exception as e:
        print(f"[WSL] Could not auto-detect Windows WiFi IP: {e}")
    return None


def find_espota():
    """Find the espota.py script inside PlatformIO packages."""
    pio_packages = Path.home() / ".platformio" / "packages"
    for framework in pio_packages.glob("framework-arduinoespressif*"):
        candidate = framework / "tools" / "espota.py"
        if candidate.exists():
            return str(candidate)
    return None


def flash_node(ip, bin_path):
    """Run PlatformIO upload to a single IP via espota."""
    env = os.environ.copy()
    env["PLATFORMIO_BUILD_DIR"] = str(PROJECT_ROOT / ".pio")

    # WSL fix: espota binds to WSL's virtual IP, but the ESP32 is on the
    # Windows WiFi network and can't reach it. We must call espota.py
    # directly with --host_ip instead of going through 'pio run'.
    if is_wsl():
        host_ip = get_windows_wifi_ip()
        espota_path = find_espota()
        if host_ip and espota_path:
            cmd = [
                sys.executable, espota_path,
                "-i", ip,
                "-I", host_ip,
                "-a", OTA_PASSWORD,
                "-f", str(bin_path),
                "-r",  # show progress
                "-d",  # debug output
            ]
            print(f"  [FLASH] Starting {ip} via espota.py (WSL fix) ...")
        else:
            print("[WSL] WARNING: Could not detect Windows WiFi IP or find espota.py.")
            print("[WSL] OTA may fail. Try running from Windows PowerShell instead.")
            cmd = [
                sys.executable, "-m", "platformio", "run", "-e", "esp32s3-ota", "-t", "upload",
                f"--upload-port={ip}",
            ]
    else:
        # Native Windows / Linux — use espota.py directly to avoid parallel build
        # collisions in the shared .pio directory when flashing multiple nodes.
        espota_path = find_espota()
        if espota_path:
            cmd = [
                sys.executable, espota_path,
                "-i", ip,
                "-a", OTA_PASSWORD,
                "-f", str(bin_path),
                "-r",  # show progress
            ]
            print(f"  [FLASH] Starting {ip} via espota.py ...")
        else:
            print("[WARN] Could not find espota.py; falling back to 'pio run' (may collide in parallel)")
            cmd = [
                sys.executable, "-m", "platformio", "run", "-e", "esp32s3-ota", "-t", "upload",
                f"--upload-port={ip}",
            ]

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, env=env)
    if result.returncode == 0:
        print(f"  [FLASH] {ip} SUCCESS")
        return True
    else:
        print(f"  [FLASH] {ip} FAILED")
        print(result.stdout[-800:] if len(result.stdout) > 800 else result.stdout)
        print(result.stderr[-400:] if len(result.stderr) > 400 else result.stderr)
        return False


def build_firmware():
    """Build the esp32s3-ota environment to produce firmware.bin."""
    print("[BUILD] Building firmware ...")
    cmd = [sys.executable, "-m", "platformio", "run", "-e", "esp32s3-ota"]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print("[BUILD] FAILED")
        print(result.stdout[-1200:] if len(result.stdout) > 1200 else result.stdout)
        print(result.stderr[-600:] if len(result.stderr) > 600 else result.stderr)
        sys.exit(1)
    print("[BUILD] OK")
    if not FIRMWARE_BIN.exists():
        print(f"[BUILD] Binary not found at {FIRMWARE_BIN}")
        sys.exit(1)
    print(f"[BUILD] Binary: {FIRMWARE_BIN}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Flash all RTLS nodes over WiFi")
    parser.add_argument("--ip", action="append", help="Flash specific IP(s) only")
    parser.add_argument("--id", type=int, help="Set UWB index for --ip target")
    parser.add_argument("--skip-build", action="store_true", help="Skip PlatformIO build")
    parser.add_argument("--skip-discover", action="store_true", help="Skip discovery (use --ip)")
    parser.add_argument("--auto-id", action="store_true", help="Automatically assign IDs 0..N-1 (default: disabled to protect EEPROM)")
    args = parser.parse_args()

    if not args.skip_build:
        build_firmware()

    # --- Discovery ---
    if args.ip:
        nodes = {ip: {"id": 255, "role": 0, "netid": 0} for ip in args.ip}
    elif not args.skip_discover:
        print("[DISC] Scanning network ...")
        nodes = discover_nodes()
        if not nodes:
            print("[DISC] No nodes found. Are you on the RTLS-NET WiFi?")
            sys.exit(1)
        print(f"[DISC] Found {len(nodes)} node(s)")
    else:
        print("[ERR] Need --ip or allow discovery")
        sys.exit(1)

    # --- Optional ID configuration (manual single node) ---
    if args.id is not None and args.ip and len(args.ip) == 1:
        ip = args.ip[0]
        print(f"[ID] Setting {ip} to ID={args.id}")
        if set_node_id(ip, args.id):
            print("[ID] Node will reboot with new ID. Re-run without --id to flash.")
            sys.exit(0)
        else:
            sys.exit(1)

    # --- Automatic ID assignment (0 .. N-1) ---
    if args.auto_id and not args.id:
        sorted_ips = sorted(nodes.keys(), key=lambda ip: [int(x) for x in ip.split(".")])
        print(f"[AUTO-ID] Assigning IDs 0..{len(sorted_ips)-1} to {len(sorted_ips)} node(s) ...")
        for new_id, ip in enumerate(sorted_ips):
            set_node_id(ip, new_id)
            time.sleep(0.2)
        print("[AUTO-ID] Waiting 40s for nodes to reboot ...")
        time.sleep(40)
        print("[AUTO-ID] Rediscovering after reboot ...")
        nodes = discover_nodes()
        if len(nodes) < len(sorted_ips):
            print(f"[AUTO-ID] Only found {len(nodes)}/{len(sorted_ips)}. Retrying in 15s ...")
            time.sleep(15)
            nodes = discover_nodes()
        # If user explicitly passed --ip, rediscovery may have pulled in the
        # whole network via broadcast. Keep only the targeted IPs.
        if args.ip:
            nodes = {ip: info for ip, info in nodes.items() if ip in args.ip}
        if not nodes:
            print("[AUTO-ID] No nodes found after reboot. Abort.")
            sys.exit(1)
        print(f"[AUTO-ID] Found {len(nodes)} node(s) after reboot")

    # --- Enable OTA on all nodes ---
    print("[OTA] Opening windows ...")
    ota_ok = {}
    for ip in nodes:
        ota_ok[ip] = enable_ota(ip)
        time.sleep(0.1)

    ready = [ip for ip, ok in ota_ok.items() if ok]
    if not ready:
        print("[OTA] No nodes accepted OTA. Abort.")
        sys.exit(1)

    print(f"[OTA] {len(ready)} node(s) ready. Flashing now ...")
    deadline = time.time() + OTA_WINDOW_S - 15  # leave 15s buffer

    # --- Flash in parallel threads ---
    results = {}
    threads = []

    def worker(ip):
        results[ip] = flash_node(ip, FIRMWARE_BIN)

    for ip in ready:
        t = threading.Thread(target=worker, args=(ip,))
        t.start()
        threads.append(t)
        time.sleep(0.5)  # stagger starts slightly

    for t in threads:
        t.join(timeout=OTA_WINDOW_S)

    # --- Summary ---
    print("\n========== SUMMARY ==========")
    for ip in nodes:
        status = "OK" if results.get(ip) else "FAIL"
        info = nodes[ip]
        print(f"  {ip:15s}  ID={info['id']}  {status}")
    print("=============================")

    ok_count = sum(1 for v in results.values() if v)
    print(f"\nSuccess: {ok_count}/{len(ready)}")
    sys.exit(0 if ok_count == len(ready) else 1)


if __name__ == "__main__":
    main()
