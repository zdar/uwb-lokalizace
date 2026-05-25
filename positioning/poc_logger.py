"""
poc_logger.py
=============
Main data collector for the UWB PoC.

Listens on UDP port 50000 for structured log packets from the ANL,
parses them, and writes to a timestamped CSV file.

Packet types handled:
  RPT,<tag_id>,<anchor_id>,<range_cm>,<rssi>,<ts>
  SNAP,<tag_id>,<raw_at_range_line>,<ts>
  DIST,<from_id>,<to_id>,<raw_cm>,<median_cm>,<ts>
  CAL_POINT,<anchor_id>,<known_cm>,<measured_cm>,<ts>
  CAL_DONE,<anchor_id>,<delay>,<ts>

Usage:
  python poc_logger.py
"""

import socket
import csv
import sys
import os
from datetime import datetime

UDP_PORT = 50000

# CSV columns (wide format — empty cells for irrelevant fields)
CSV_COLUMNS = [
    "timestamp_ms",
    "type",
    "tag_id",
    "anchor_id",
    "range_cm",
    "rssi_dbm",
    "from_id",
    "to_id",
    "median_cm",
    "known_cm",
    "measured_cm",
    "delay",
    "snap_flag",
]


def make_csv_path() -> str:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"uwb_log_{now}.csv"


def parse_line(line: str) -> dict | None:
    """Parse a structured log line into a CSV row dict."""
    line = line.strip()
    if not line:
        return None

    parts = line.split(",")
    if len(parts) < 2:
        return None

    typ = parts[0]
    ts = parts[-1] if parts[-1].isdigit() else ""

    row = {c: "" for c in CSV_COLUMNS}
    row["type"] = typ
    row["timestamp_ms"] = ts

    if typ == "RPT" and len(parts) >= 5:
        # RPT,tag_id,anchor_id,range_cm,rssi,ts
        row["tag_id"] = parts[1]
        row["anchor_id"] = parts[2]
        row["range_cm"] = parts[3]
        row["rssi_dbm"] = parts[4]

    elif typ == "SNAP" and len(parts) >= 4:
        # SNAP,tag_id,<raw AT+RANGE line>,ts
        row["tag_id"] = parts[1]
        row["snap_flag"] = "1"
        row["range_cm"] = ",".join(parts[2:-1])
        row["rssi_dbm"] = ""

    elif typ == "DIST" and len(parts) >= 6:
        # DIST,from_id,to_id,raw_cm,median_cm,ts
        row["from_id"] = parts[1]
        row["to_id"] = parts[2]
        row["range_cm"] = parts[3]
        row["median_cm"] = parts[4]

    elif typ == "CAL_POINT" and len(parts) >= 5:
        # CAL_POINT,anchor_id,known_cm,measured_cm,ts
        row["anchor_id"] = parts[1]
        row["known_cm"] = parts[2]
        row["measured_cm"] = parts[3]

    elif typ == "CAL_DONE" and len(parts) >= 4:
        # CAL_DONE,anchor_id,delay,ts
        row["anchor_id"] = parts[1]
        row["delay"] = parts[2]

    else:
        return None

    return row


def get_rtls_ip() -> str:
    """Find the IP address on the 192.168.4.x network."""
    import subprocess
    try:
        result = subprocess.run(["ipconfig"], capture_output=True, text=True)
        lines = result.stdout.split("\n")
        for i, line in enumerate(lines):
            if "192.168.4." in line:
                # Extract IP from line like "   IPv4 Address. . . . . . . . . . . : 192.168.4.9"
                parts = line.split(":")
                if len(parts) >= 2:
                    ip = parts[1].strip()
                    if ip.startswith("192.168.4."):
                        return ip
    except Exception:
        pass
    return "0.0.0.0"


def main():
    csv_path = make_csv_path()
    bind_ip = get_rtls_ip()
    print(f"Logging to: {csv_path}")
    print(f"Listening on UDP {bind_ip}:{UDP_PORT}")
    print("Press Ctrl+C to stop.\n")

    # Open CSV for writing
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        # Open UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind_ip, UDP_PORT))
        except OSError as e:
            print(f"Failed to bind to {bind_ip}:{UDP_PORT} — {e}")
            print("Trying 0.0.0.0 instead...")
            sock.bind(("0.0.0.0", UDP_PORT))
        sock.settimeout(1.0)

        try:
            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                except socket.timeout:
                    continue
                except OSError as e:
                    print(f"[SOCKET ERROR] {e}")
                    continue

                text = data.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue

                # Debug: print every raw packet
                print(f"[RAW from {addr[0]}] {text[:100]}")

                # Skip raw relay packets that contain the full AT+RANGE string
                if text.startswith("RPT,") and "AT+RANGE" in text:
                    print("  -> skipped (raw relay)")
                    continue

                row = parse_line(text)
                if row:
                    writer.writerow(row)
                    f.flush()
                    print(f"  -> [{row['type']}] logged")
                else:
                    print(f"  -> UNKNOWN (not parsed)")

        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            sock.close()
            print(f"Log saved to {csv_path}")


if __name__ == "__main__":
    main()
