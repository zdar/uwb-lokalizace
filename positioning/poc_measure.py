"""
poc_measure.py
Trigger a SNAP over WiFi, collect the 5-second stream, build a distance matrix,
and save it with a user comment.

Usage:
    python poc_measure.py
    python poc_measure.py 192.168.4.5   # send directly to known tag IP

The script:
  1. Asks for an optional comment
  2. Sends UDP "SNAP" to broadcast + subnet scan
  3. Listens for 6 seconds
  4. Builds a median distance matrix
  5. Saves to uwb_matrix_*.csv
"""

import socket
import csv
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

UDP_PORT = 50000
LISTEN_SECONDS = 6


def parse_at_range(line: str) -> tuple[list[int], list[float]] | None:
    """Parse AT+RANGE line: AT+RANGE:0,ancid:(0,1,2),range:(123,456,789),..."""
    anc_start = line.find("ancid:(")
    if anc_start < 0:
        return None
    anc_start += 7
    anc_end = line.find(")", anc_start)
    if anc_end < 0:
        return None
    ancids_str = line[anc_start:anc_end]
    ancids = [int(x.strip()) for x in ancids_str.split(",") if x.strip().lstrip("-").isdigit()]

    rng_start = line.find("range:(")
    if rng_start < 0:
        return None
    rng_start += 7
    rng_end = line.find(")", rng_start)
    if rng_end < 0:
        return None
    rngs_str = line[rng_start:rng_end]
    ranges = []
    for x in rngs_str.split(","):
        x = x.strip()
        if not x:
            continue
        try:
            ranges.append(float(x))
        except ValueError:
            pass

    return ancids, ranges


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def send_snap_trigger(sock: socket.socket, direct_ip: str | None) -> list[str]:
    """Send SNAP trigger via broadcast, direct IP, and subnet scan."""
    tried = []

    # Enable broadcast
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except Exception as e:
        print(f"  -> Could not enable SO_BROADCAST: {e}")

    # 1) Broadcast
    try:
        sock.sendto(b"SNAP", ("192.168.4.255", UDP_PORT))
        tried.append("192.168.4.255")
        print("  -> Sent SNAP to 192.168.4.255 (broadcast)")
    except Exception as e:
        print(f"  -> Broadcast failed: {e}")

    # 2) Direct IP if provided
    if direct_ip:
        try:
            sock.sendto(b"SNAP", (direct_ip, UDP_PORT))
            tried.append(direct_ip)
            print(f"  -> Sent SNAP to {direct_ip} (direct)")
        except Exception as e:
            print(f"  -> Direct send to {direct_ip} failed: {e}")

    # 3) Subnet scan fallback
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

    print("\nSending SNAP trigger...")

    # Open UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", UDP_PORT))
    except OSError as e:
        print(f"Failed to bind to port {UDP_PORT}: {e}")
        sys.exit(1)
    sock.settimeout(1.0)

    # Send trigger
    tried = send_snap_trigger(sock, direct_ip)
    print(f"Listening for {LISTEN_SECONDS}s...")

    samples = defaultdict(list)
    sources = defaultdict(set)
    start_time = time.time()
    packets_received = 0

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

        try:
            tag_id = int(tag_id_str)
        except ValueError:
            continue

        parsed = parse_at_range(raw_line)
        if parsed is None:
            continue

        ancids, ranges = parsed
        pairs = min(len(ancids), len(ranges))
        for i in range(pairs):
            if ranges[i] > 0:
                key = (tag_id, ancids[i])
                samples[key].append(ranges[i])
                sources[key].add(source)

    sock.close()

    print(f"\nReceived {packets_received} total UDP packets")

    if not samples:
        print("\nNo SNAP data received. Make sure:")
        print("  - The tag is powered on and connected to WiFi")
        print("  - You are connected to the RTLS-NET-XXXX AP")
        print("  - The tag has the latest firmware flashed")
        print(f"  - Tried: {', '.join(tried)}")
        sys.exit(1)

    # Build matrix
    ids = sorted(set(k[0] for k in samples.keys()) | set(k[1] for k in samples.keys()))

    print(f"\nCollected {sum(len(v) for v in samples.values())} range samples")
    print(f"Nodes involved: {ids}\n")

    header = "    " + " ".join(f"{i:>8}" for i in ids)
    print(header)
    for i in ids:
        row_str = f"{i:>3} "
        for j in ids:
            key = (i, j)
            if key in samples and samples[key]:
                med = median(samples[key])
                row_str += f"{med:>8.1f} "
            else:
                row_str += f"{'—':>8} "
        print(row_str)

    # Save
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(os.path.dirname(__file__), f"uwb_matrix_{now}.csv")
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["comment", comment])
        writer.writerow(["from_id", "to_id", "median_cm", "samples", "sources"])
        for (frm, to), vals in sorted(samples.items()):
            src_str = "|".join(sorted(sources.get((frm, to), {"?"})))
            writer.writerow([frm, to, f"{median(vals):.1f}", len(vals), src_str])
    print(f"\nSaved matrix to {out_path}")


if __name__ == "__main__":
    main()
