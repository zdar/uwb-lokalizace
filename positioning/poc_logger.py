"""
poc_logger.py
=============
Main data collector for the UWB PoC.

Listens on UDP port 50000 for structured log packets from the ANL,
parses them, and writes to a timestamped CSV file.

Packet types handled:
  SNAP,<tag_id>,<source>,<raw_at_range_line>,<ts>

Usage:
  python poc_logger.py
"""

import socket
import csv
import sys
import os
from datetime import datetime

UDP_PORT = 50000

# Minimal CSV columns — no empty cells
CSV_COLUMNS = [
    "timestamp_ms",
    "type",
    "tag_id",
    "source",
    "raw_line",
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

    if typ == "SNAP" and len(parts) >= 5:
        # SNAP,tag_id,source,<raw AT+RANGE line>,ts
        row["tag_id"] = parts[1]
        row["source"] = parts[2]
        # Everything between source and ts is the raw line
        row["raw_line"] = ",".join(parts[3:-1])

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
                print(f"[RAW from {addr[0]}] {text[:120]}")

                row = parse_line(text)
                if row:
                    writer.writerow(row)
                    f.flush()
                    print(f"  -> [{row['type']}] src={row['source']} logged")
                else:
                    print(f"  -> UNKNOWN (not parsed)")

        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            sock.close()
            print(f"Log saved to {csv_path}")


if __name__ == "__main__":
    main()
