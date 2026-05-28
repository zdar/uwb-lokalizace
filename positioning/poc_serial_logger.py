"""
poc_serial_logger.py
====================
Collect UWB SNAP data from the ANL via USB serial — no WiFi needed on the PC.

The ANL (A9) echoes every received SNAP packet to its USB serial port.
This script reads those lines, parses them, and writes to a CSV file.

Usage:
    python poc_serial_logger.py
    python poc_serial_logger.py COM3
    python poc_serial_logger.py /dev/ttyUSB0

Requirements:
    pip install pyserial
"""

import csv
import os
import sys
import time
from datetime import datetime

import serial
import serial.tools.list_ports

SERIAL_BAUD = 115200
SERIAL_TIMEOUT = 0.1

CSV_COLUMNS = [
    "timestamp_ms",
    "type",
    "tag_id",
    "source",
    "raw_line",
    "comment",
]


def list_ports() -> list[str]:
    """Return a list of available serial port names."""
    return [p.device for p in serial.tools.list_ports.comports()]


def choose_port(preferred: str | None = None) -> str:
    """Ask the user to pick a serial port."""
    ports = list_ports()
    if not ports:
        print("No serial ports found. Is the ANL connected via USB?")
        sys.exit(1)

    if preferred:
        if preferred in ports:
            return preferred
        print(f"Port {preferred} not found.")

    print("\nAvailable serial ports:")
    for i, p in enumerate(ports, 1):
        print(f"  {i}. {p}")
    print()

    while True:
        choice = input("Select port number (or type the name directly): ").strip()
        # Direct name
        if choice in ports:
            return choice
        # Number
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(ports):
                return ports[idx]
        except ValueError:
            pass
        print("Invalid choice. Try again.")


def parse_snap_line(line: str) -> dict | None:
    """Parse a SNAP line from serial into a CSV row dict."""
    line = line.strip()
    if not line.startswith("SNAP,"):
        return None

    parts = line.split(",")
    if len(parts) < 5:
        return None

    ts = parts[-1] if parts[-1].isdigit() else ""
    return {
        "timestamp_ms": ts,
        "type": "SNAP",
        "tag_id": parts[1],
        "source": parts[2],
        "raw_line": ",".join(parts[3:-1]),
        "comment": "",
    }


def main():
    preferred_port = sys.argv[1] if len(sys.argv) >= 2 else None
    port_name = choose_port(preferred_port)

    comment = input("Comment for this log (press Enter to skip): ").strip()

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(os.path.dirname(__file__), f"uwb_log_{now}.csv")

    print(f"\nOpening {port_name} at {SERIAL_BAUD} baud...")
    try:
        ser = serial.Serial(port_name, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
    except serial.SerialException as e:
        print(f"Failed to open {port_name}: {e}")
        sys.exit(1)

    # Flush any buffered data
    ser.reset_input_buffer()

    print(f"Logging to: {csv_path}")
    print("Press Ctrl+C to stop.\n")

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

        snap_count = 0
        try:
            while True:
                try:
                    raw = ser.readline()
                except serial.SerialException as e:
                    print(f"[SERIAL ERROR] {e}")
                    break

                if not raw:
                    continue

                try:
                    text = raw.decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue

                if not text:
                    continue

                # Print everything for visibility, but only parse SNAP lines
                print(f"[SERIAL] {text[:120]}")

                row = parse_snap_line(text)
                if row:
                    writer.writerow(row)
                    f.flush()
                    snap_count += 1
                    print(f"  -> SNAP logged (total: {snap_count})")

        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            ser.close()
            print(f"\n{snap_count} SNAP rows saved to {csv_path}")


if __name__ == "__main__":
    main()
