"""
poc_measure.py
Trigger a SNAP over WiFi and save the raw stream exactly like a button SNAP.

Usage:
    python poc_measure.py
    python poc_measure.py 192.168.4.5   # send directly to known tag IP

The script:
  1. Asks for an optional comment
  2. Sends UDP "SNAP" trigger
  3. Listens for 6 seconds
  4. Saves raw SNAP packets to uwb_log_*.csv (same format as poc_logger.py)
"""

import socket
import csv
import os
import sys
import time
from datetime import datetime

UDP_PORT = 50000
LISTEN_SECONDS = 6

CSV_COLUMNS = [
    "timestamp_ms",
    "type",
    "tag_id",
    "source",
    "raw_line",
    "comment",
]


def send_snap_trigger(sock: socket.socket, direct_ip: str | None) -> list[str]:
    """Send SNAP trigger via broadcast, direct IP, and subnet scan."""
    tried = []

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except Exception as e:
        print(f"  -> Could not enable SO_BROADCAST: {e}")

    try:
        sock.sendto(b"SNAP", ("192.168.4.255", UDP_PORT))
        tried.append("192.168.4.255")
        print("  -> Sent SNAP to 192.168.4.255 (broadcast)")
    except Exception as e:
        print(f"  -> Broadcast failed: {e}")

    if direct_ip:
        try:
            sock.sendto(b"SNAP", (direct_ip, UDP_PORT))
            tried.append(direct_ip)
            print(f"  -> Sent SNAP to {direct_ip} (direct)")
        except Exception as e:
            print(f"  -> Direct send to {direct_ip} failed: {e}")

    print("  -> Scanning subnet 192.168.4.2-10...")
    for i in range(2, 11):
        ip = f"192.168.4.{i}"
        if ip == direct_ip:
            continue
        try:
            sock.sendto(b"SNAP", (ip, UDP_PORT))
        except Exception:
            pass
    tried.append("192.168.4.2-10")
    print("  -> Sent SNAP to 192.168.4.2-10 (subnet scan)")

    return tried


def main():
    direct_ip = sys.argv[1] if len(sys.argv) >= 2 else None

    comment = input("Comment for this measurement (press Enter to skip): ").strip()

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(os.path.dirname(__file__), f"uwb_log_{now}.csv")

    print(f"\nLogging to: {csv_path}")
    print("Sending SNAP trigger...")

    # Open UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", UDP_PORT))
    except OSError as e:
        print(f"Failed to bind to port {UDP_PORT}: {e}")
        sys.exit(1)
    sock.settimeout(1.0)

    # Open CSV
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        if comment:
            writer.writerow({
                "timestamp_ms": "",
                "type": "COMMENT",
                "tag_id": "",
                "source": "",
                "raw_line": "",
                "comment": comment,
            })

        # Send trigger
        tried = send_snap_trigger(sock, direct_ip)
        print(f"Listening for {LISTEN_SECONDS}s...")

        start_time = time.time()
        packets_received = 0
        snap_count = 0

        # Deduplication buffer: store dedup_key -> arrival_time.
        # Window = 2 seconds.
        seen_packets = {}
        dedup_window = 2.0

        while time.time() - start_time < LISTEN_SECONDS:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue

            text = data.decode("utf-8", errors="ignore").strip()
            packets_received += 1
            print(f"  [{addr[0]}] {text[:100]}")

            if not text.startswith("SNAP,"):
                continue

            parts = text.split(",")
            if len(parts) < 5:
                continue

            # SNAP,tag_id,source,<raw_line>,ts
            tag_id_str = parts[1]
            source = parts[2]
            raw_line = ",".join(parts[3:-1])
            ts = parts[-1]

            # Deduplication key
            dedup_key = (tag_id_str, source, raw_line, ts)
            now_mono = time.time()
            # Clean old entries
            seen_packets = {
                k: v for k, v in seen_packets.items()
                if now_mono - v < dedup_window
            }
            if dedup_key in seen_packets:
                print(f"  -> DUPLICATE suppressed")
                continue
            seen_packets[dedup_key] = now_mono

            writer.writerow({
                "timestamp_ms": ts,
                "type": "SNAP",
                "tag_id": tag_id_str,
                "source": source,
                "raw_line": raw_line,
                "comment": "",
            })
            f.flush()
            snap_count += 1

    sock.close()

    print(f"\nReceived {packets_received} total UDP packets, {snap_count} SNAP rows")
    print(f"Log saved to {csv_path}")

    if snap_count == 0:
        print("\nWARNING: No SNAP data received. Make sure:")
        print("  - The tag is powered on and connected to WiFi")
        print("  - You are connected to the RTLS-NET-XXXX AP")
        print("  - The tag has the latest firmware flashed")
        print(f"  - Tried: {', '.join(tried)}")


if __name__ == "__main__":
    main()
