"""
poc_measure.py
Build an anchor-to-anchor distance matrix from a poc_logger.py CSV file.

Usage:
    python poc_measure.py <csv_file>
    python poc_measure.py                  # uses most recent uwb_log_*.csv

For each SNAP row, parses the AT+RANGE line to extract distances from the
temporary tag to each anchor. After collecting all SNAP data, prints a
median distance matrix and saves it to a CSV file.
"""

import csv
import sys
import os
import glob
from collections import defaultdict


def parse_at_range(line: str) -> tuple[list[int], list[float]] | None:
    """Parse AT+RANGE line: AT+RANGE:0,ancid:(0,1,2),range:(123,456,789),..."""
    # Find ancid:(...)
    anc_start = line.find("ancid:(")
    if anc_start < 0:
        return None
    anc_start += 7
    anc_end = line.find(")", anc_start)
    if anc_end < 0:
        return None
    ancids_str = line[anc_start:anc_end]
    ancids = [int(x.strip()) for x in ancids_str.split(",") if x.strip().lstrip("-").isdigit()]

    # Find range:(...)
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


def main():
    if len(sys.argv) >= 2:
        csv_path = sys.argv[1]
    else:
        # Find most recent uwb_log_*.csv
        files = glob.glob(os.path.join(os.path.dirname(__file__), "uwb_log_*.csv"))
        if not files:
            print("No uwb_log_*.csv found. Usage: python poc_measure.py <csv_file>")
            sys.exit(1)
        csv_path = max(files, key=os.path.getmtime)

    print(f"Reading {csv_path}")

    # Ask for an optional comment
    comment = input("Comment for this measurement (press Enter to skip): ").strip()

    # Collect all (tag_id, anchor_id) -> [range_cm samples]
    samples = defaultdict(list)
    sources = defaultdict(set)  # (tag_id, anchor_id) -> {BTN, UDP, ...}

    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("type") != "SNAP":
                continue
            tag_id_str = row.get("tag_id", "").strip()
            if not tag_id_str:
                continue
            try:
                tag_id = int(tag_id_str)
            except ValueError:
                continue

            raw_line = row.get("raw_line", "")
            if not raw_line:
                continue

            source = row.get("source", "BTN").strip()

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

    if not samples:
        print("No SNAP data found in CSV.")
        sys.exit(1)

    # Build median matrix
    ids = sorted(set(k[0] for k in samples.keys()) | set(k[1] for k in samples.keys()))

    print(f"\nCollected {sum(len(v) for v in samples.values())} range samples")
    print(f"Nodes involved: {ids}\n")

    # Print matrix
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

    # Save as simple CSV matrix
    out_path = csv_path.replace("uwb_log_", "uwb_matrix_")
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
