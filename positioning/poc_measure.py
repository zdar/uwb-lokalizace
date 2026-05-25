"""
poc_measure.py
Trigger anchor-to-anchor distance matrix measurement and collect DIST output.
Run from Windows PowerShell (not WSL) so UDP broadcast works.

Usage:
    python poc_measure.py

Sends "MEASURE" UDP packet to ANL (192.168.4.1:50000), then listens for
DIST lines and prints a matrix at the end.
"""

import socket
import csv
import os
from datetime import datetime

ANL_IP = "192.168.4.1"
WIFI_PORT = 50000
LISTEN_PORT = 50000


def get_rtls_ip() -> str:
    import subprocess
    try:
        result = subprocess.run(["ipconfig"], capture_output=True, text=True)
        lines = result.stdout.split("\n")
        for i, line in enumerate(lines):
            if "192.168.4." in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    ip = parts[1].strip().split()[0]
                    return ip
        for i, line in enumerate(lines):
            if "192.168.4." in line:
                for j in range(i, min(i + 5, len(lines))):
                    if "192.168.4." in lines[j]:
                        parts = lines[j].split(":")
                        if len(parts) >= 2:
                            ip = parts[1].strip().split()[0]
                            return ip
    except Exception:
        pass
    return "0.0.0.0"


def main():
    listen_ip = get_rtls_ip()
    print(f"Listening on {listen_ip}:{LISTEN_PORT}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((listen_ip, LISTEN_PORT))
    sock.settimeout(1.0)

    # Send MEASURE command to ANL
    print(f"Sending MEASURE to {ANL_IP}:{WIFI_PORT} ...")
    sock.sendto(b"MEASURE", (ANL_IP, WIFI_PORT))

    dist_rows = []
    print("Waiting for DIST output (this takes ~2 minutes for 4 anchors) ...")
    print("Press Ctrl+C to stop early.\n")

    done = False
    try:
        while not done:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            line = data.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            print(line)
            if line.startswith("DIST,"):
                parts = line.split(",")
                if len(parts) >= 6 and parts[1] == "DONE":
                    done = True
                else:
                    dist_rows.append(parts)
    except KeyboardInterrupt:
        print("\nStopped by user.")

    sock.close()

    # Save to CSV
    if dist_rows:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(os.path.dirname(__file__), f"uwb_dist_{ts}.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["from_id", "to_id", "median_cm", "ts"])
            for row in dist_rows:
                # DIST,from_id,to_id,raw_cm,median_cm,ts
                if len(row) >= 6:
                    writer.writerow([row[1], row[2], row[4], row[5]])
        print(f"\nSaved {len(dist_rows)} DIST rows to {csv_path}")

        # Print matrix
        ids = sorted(set(int(r[1]) for r in dist_rows if r[1].isdigit()) |
                     set(int(r[2]) for r in dist_rows if r[2].isdigit()))
        print("\nDistance matrix (cm):")
        header = "    " + " ".join(f"{i:>6}" for i in ids)
        print(header)
        for i in ids:
            row_str = f"{i:>3} "
            for j in ids:
                val = ""
                for r in dist_rows:
                    if int(r[1]) == i and int(r[2]) == j:
                        val = r[4]
                        break
                row_str += f"{val:>6} "
            print(row_str)
    else:
        print("\nNo DIST rows captured.")


if __name__ == "__main__":
    main()
