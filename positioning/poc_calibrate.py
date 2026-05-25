"""
poc_calibrate.py
Interactive antenna delay calibration from a poc_logger.py CSV file.

Usage:
    python poc_calibrate.py <csv_file>
    python poc_calibrate.py                  # uses most recent uwb_log_*.csv

Workflow:
1. Place a tag at a known distance from all anchors (e.g. 100 cm from each).
2. Press the SNAP button on the tag.
3. Run this script. It reads the CSV and asks you for the known distance
   to each anchor that appeared in the data.
4. It computes median measured distance, delay = measured - known, and
   prints the AT commands you need to send to each anchor.
5. Send AT+SETANT=<delay> and AT+SAVE to each anchor (via serial).
"""

import csv
import sys
import os
import glob
from collections import defaultdict


def parse_at_range(line: str) -> tuple[list[int], list[float]] | None:
    """Parse AT+RANGE line: AT+RANGE:0,ancid:(0,1,2),range:(123,456,789),..."""
    anc_start = line.find("ancid:(")
    if anc_start < 0:
        return None
    anc_start += 7
    anc_end = line.find(")", anc_start)
    if anc_end < 0:
        return None
    ancids = [int(x.strip()) for x in line[anc_start:anc_end].split(",") if x.strip().lstrip("-").isdigit()]

    rng_start = line.find("range:(")
    if rng_start < 0:
        return None
    rng_start += 7
    rng_end = line.find(")", rng_start)
    if rng_end < 0:
        return None
    ranges = []
    for x in line[rng_start:rng_end].split(","):
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


def main():
    if len(sys.argv) >= 2:
        csv_path = sys.argv[1]
    else:
        files = glob.glob(os.path.join(os.path.dirname(__file__), "uwb_log_*.csv"))
        if not files:
            print("No uwb_log_*.csv found. Usage: python poc_calibrate.py <csv_file>")
            sys.exit(1)
        csv_path = max(files, key=os.path.getmtime)

    print(f"Reading {csv_path}\n")

    # Collect SNAP samples per anchor
    samples = defaultdict(list)

    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("type") != "SNAP":
                continue
            raw_line = row.get("range_cm", "")
            if not raw_line:
                continue
            parsed = parse_at_range(raw_line)
            if parsed is None:
                continue
            ancids, ranges = parsed
            pairs = min(len(ancids), len(ranges))
            for i in range(pairs):
                if ranges[i] > 0:
                    samples[ancids[i]].append(ranges[i])

    if not samples:
        print("No SNAP data found in CSV.")
        sys.exit(1)

    anchor_ids = sorted(samples.keys())
    print(f"Anchors seen in SNAP data: {anchor_ids}\n")
    print("=" * 60)
    print("CALIBRATION INPUT")
    print("=" * 60)
    print("Enter the KNOWN distance (in cm) from the tag to each anchor.")
    print("(e.g. if you placed the tag exactly 100 cm from anchor 1, enter 100)")
    print()

    known = {}
    for aid in anchor_ids:
        med = median(samples[aid])
        print(f"Anchor {aid}: median measured = {med:.1f} cm from {len(samples[aid])} samples")
        while True:
            try:
                val = input(f"  Known distance to anchor {aid} (cm): ").strip()
                known[aid] = float(val)
                break
            except ValueError:
                print("    Please enter a number.")

    print()
    print("=" * 60)
    print("CALIBRATION RESULTS")
    print("=" * 60)

    for aid in anchor_ids:
        med = median(samples[aid])
        delay = med - known[aid]
        print(f"\nAnchor {aid}:")
        print(f"  Median measured: {med:.1f} cm")
        print(f"  Known distance:  {known[aid]:.1f} cm")
        print(f"  Delay offset:    {delay:+.1f} cm")
        print(f"  AT command:      AT+SETANT={int(delay + 0.5)}")

    print()
    print("=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print("1. Connect to each anchor via USB serial (115200 baud).")
    print("2. Send the AT+SETANT=<delay> command shown above.")
    print("3. Send AT+SAVE to persist the setting.")
    print("4. Repeat for all anchors.")
    print()
    print("Tip: You can also send AT+SETANT via the node's UDP interface")
    print("     if you know its IP address.")


if __name__ == "__main__":
    main()
