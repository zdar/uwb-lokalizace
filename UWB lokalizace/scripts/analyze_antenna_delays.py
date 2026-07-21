import csv
import re
import os
import glob
import sys
import argparse
from statistics import median
from collections import defaultdict


def read_true_distances(path):
    """Read a symmetric distance matrix CSV (meters) and return dict of unordered pairs -> cm."""
    with open(path, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    header = [h.strip().replace('A', '') for h in rows[0]]
    ids = header[1:]
    true_cm = {}
    for row in rows[1:]:
        a = row[0].strip().replace('A', '')
        for i, v in enumerate(row[1:]):
            b = ids[i]
            if a == b:
                continue
            key = (min(a, b), max(a, b))
            true_cm[key] = float(v) * 100.0
    return true_cm


def find_latest_raw_csv(sessions_dir='sessions'):
    pattern = os.path.join(sessions_dir, '*_raw.csv')
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not files:
        raise FileNotFoundError(f'No *_raw.csv found in {sessions_dir}')
    return files[0]


def read_measured_ranges(raw_path):
    """Extract per-pair range measurements from RAW_PACKETS section of a raw CSV."""
    pattern = re.compile(r'AT\+RANGE=tid:(\d+),.*?range:\(([^)]+)\),ancid:\(([^)]+)\)')
    measurements = defaultdict(list)
    in_section = False
    with open(raw_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            first = row[0].strip()
            if first.startswith('# RAW_PACKETS'):
                in_section = True
                continue
            if first.startswith('#'):
                # Other section header -> leave raw section
                in_section = False
                continue
            if not in_section:
                continue
            # Expected columns: timestamp_ms, type, tag_id, source, raw_line, comment
            if len(row) < 6:
                continue
            raw = row[4]
            m = pattern.match(raw)
            if not m:
                continue
            tid = m.group(1)
            ranges = [float(x) for x in m.group(2).split(',')]
            ancids = [str(int(float(x))) for x in m.group(3).split(',')]
            for aid, r in zip(ancids, ranges):
                if aid == '-1' or r <= 0:
                    continue
                pair = (min(tid, aid), max(tid, aid))
                measurements[pair].append(r)
    return measurements


def solve_delays(pairs, offsets, n=10):
    """Solve least-squares delay_i + delay_j = offset for i,j in 0..n-1."""
    A = []
    b = []
    for (i, j), offset in zip(pairs, offsets):
        row = [0.0] * n
        row[int(i)] = 1.0
        row[int(j)] = 1.0
        A.append(row)
        b.append(offset)

    # Normal equations
    AtA = [[0.0] * n for _ in range(n)]
    Atb = [0.0] * n
    for row, bi in zip(A, b):
        for i in range(n):
            for j in range(n):
                AtA[i][j] += row[i] * row[j]
            Atb[i] += row[i] * bi

    # Gaussian elimination with partial pivoting
    M = [AtA[i] + [Atb[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-9:
            continue
        M[col], M[pivot] = M[pivot], M[col]
        piv = M[col][col]
        for k in range(col, n + 1):
            M[col][k] /= piv
        for row in range(n):
            if row == col:
                continue
            factor = M[row][col]
            if abs(factor) < 1e-12:
                continue
            for k in range(col, n + 1):
                M[row][k] -= factor * M[col][k]

    return [M[i][n] for i in range(n)]


def main():
    parser = argparse.ArgumentParser(description='Compare measured UWB ranges to true distances and estimate antenna delays.')
    parser.add_argument('--true', default='point_distances.csv', help='CSV with true pairwise distances in meters')
    parser.add_argument('--raw', help='Raw session CSV to analyze (default: newest sessions/*_raw.csv)')
    parser.add_argument('--sessions-dir', default='sessions', help='Directory to search for raw CSVs')
    parser.add_argument('--out', help='Optional output CSV for per-pair results')
    args = parser.parse_args()

    true_cm = read_true_distances(args.true)

    raw_path = args.raw or find_latest_raw_csv(args.sessions_dir)
    print('Using raw file:', os.path.abspath(raw_path))

    measurements = read_measured_ranges(raw_path)
    if not measurements:
        print('No valid AT+RANGE measurements found in RAW_PACKETS section.')
        sys.exit(1)

    print('\nPer-pair median measured range (cm) vs true (cm):')
    print('%8s %10s %10s %10s %8s' % ('Pair', 'Measured', 'True', 'Offset', 'Count'))
    pairs = []
    offsets = []
    out_rows = []
    for pair in sorted(measurements.keys()):
        if pair not in true_cm:
            continue
        med = median(measurements[pair])
        tr = true_cm[pair]
        offset = med - tr
        pairs.append(pair)
        offsets.append(offset)
        print('%4s-%2s %10.2f %10.2f %10.2f %8d' % (pair[0], pair[1], med, tr, offset, len(measurements[pair])))
        out_rows.append({
            'pair': f"A{pair[0]}-A{pair[1]}",
            'measured_cm': round(med, 2),
            'true_cm': round(tr, 2),
            'offset_cm': round(offset, 2),
            'samples': len(measurements[pair]),
        })

    if not pairs:
        print('\nNo measured pairs matched true distances. Check IDs and file formats.')
        sys.exit(1)

    # Estimate per-device delays
    delays = solve_delays(pairs, offsets)
    print('\nEstimated antenna delay per device (cm):')
    for i, d in enumerate(delays):
        print('  A%d: %.2f cm' % (i, d))
    print('\nTypical pair delay sum: %.2f cm' % (sum(delays) / len(delays) * 2))

    # Residuals after removing estimated delays
    print('\nResiduals after delay removal (cm):')
    print('%8s %10s' % ('Pair', 'Residual'))
    for pair, offset in zip(pairs, offsets):
        residual = offset - delays[int(pair[0])] - delays[int(pair[1])]
        print('%4s-%2s %10.2f' % (pair[0], pair[1], residual))

    if args.out:
        with open(args.out, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['pair', 'measured_cm', 'true_cm', 'offset_cm', 'samples'])
            writer.writeheader()
            writer.writerows(out_rows)
        print('\nWrote per-pair results to', args.out)


if __name__ == '__main__':
    main()
