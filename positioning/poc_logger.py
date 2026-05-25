"""
poc_logger.py
=============
Main data collector for the UWB PoC.

Listens on UDP port 50000 for structured log packets from the ANL,
parses them, and writes to a timestamped CSV file.

Packet types handled:
  RPT,<tag_id>,<anchor_id>,<range_cm>,<rssi>,<ts>
  SNAP,<tag_id>,<range_csv>,<ancid_csv>,<ts>
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
UDP_BIND = "0.0.0.0"

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
        # The raw AT+RANGE line may contain commas, so join everything
        # between tag_id and the last element (timestamp).
        row["tag_id"] = parts[1]
        row["snap_flag"] = "1"
        row["range_cm"] = ",".join(parts[2:-1])  # raw AT+RANGE payload
        row["rssi_dbm"] = ""  # not parsed here

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


def main():
    csv_path = make_csv_path()
    print(f"Logging to: {csv_path}")
    print(f"Listening on UDP {UDP_BIND}:{UDP_PORT}")
    print("Press Ctrl+C to stop.\n")

    # Open CSV for writing
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        # Open UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((UDP_BIND, UDP_PORT))
        sock.setblocking(False)

        try:
            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                except BlockingIOError:
                    continue

                text = data.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue

                # Some packets may be prefixed with RPT, from relayUwbLine
                if text.startswith("RPT,") and "AT+RANGE" in text:
                    # This is a raw relay packet — skip, we already parse structured lines
                    continue

                row = parse_line(text)
                if row:
                    writer.writerow(row)
                    f.flush()
                    print(f"[{row['type']}] {text}")
                else:
                    # Print unknown lines for debugging
                    print(f"[UNK] {text}")

        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            sock.close()
            print(f"Log saved to {csv_path}")


if __name__ == "__main__":
    main()
