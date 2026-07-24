import csv
import sys
import math
import os


def parse_layout_text(path, spacing_m=2.0):
    """Parse a tab-spaced graphical layout file into a dict of module_id -> (x, y, z).

    Each cell is one tab column. Rows are spaced by spacing_m in Y,
    columns by spacing_m in X. Top line of the file is highest Y.
    """
    with open(path, 'r', encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f]
    # Determine grid dimensions
    num_rows = len(lines)
    num_cols = max(len(line.split('\t')) for line in lines)
    # Y coordinates: top line -> highest Y
    y_coords = [spacing_m * (num_rows - 1 - r) for r in range(num_rows)]
    x_coords = [spacing_m * c for c in range(num_cols)]
    positions = {}
    for r, line in enumerate(lines):
        cells = line.split('\t')
        for c, cell in enumerate(cells):
            label = cell.strip()
            if not label:
                continue
            if label.upper().startswith('A'):
                module_id = int(label[1:])
            else:
                module_id = int(label)
            x = x_coords[c]
            y = y_coords[r]
            z = 0.0
            positions[module_id] = (x, y, z)
    return positions


def build_distance_matrix(positions, out_path=None):
    """Build a symmetric distance matrix (meters) from positions and optionally save CSV."""
    ids = sorted(positions.keys())
    n = len(ids)
    matrix = {}
    for i in ids:
        matrix[i] = {}
        for j in ids:
            if i == j:
                matrix[i][j] = 0.0
            else:
                p1 = positions[i]
                p2 = positions[j]
                d = math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)
                matrix[i][j] = d
    if out_path:
        os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else '.', exist_ok=True)
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            header = ['Point'] + [f'A{i}' for i in ids]
            writer.writerow(header)
            for i in ids:
                row = [f'A{i}'] + [f'{matrix[i][j]:.2f}' for j in ids]
                writer.writerow(row)
        print(f'Wrote {out_path}')
    return matrix


def main():
    if len(sys.argv) < 3:
        print('Usage: python build_layout_matrix.py <layout_text.txt> <output.csv> [spacing_m]')
        print('')
        print('Example:')
        print('  python build_layout_matrix.py "layout one.txt" point_distances_layout1.csv')
        sys.exit(1)
    layout_path = sys.argv[1]
    out_path = sys.argv[2]
    spacing = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    positions = parse_layout_text(layout_path, spacing)
    print(f'Parsed {len(positions)} modules from {layout_path}:')
    for mid in sorted(positions):
        x, y, z = positions[mid]
        print(f'  A{mid}: ({x:.1f}, {y:.1f}, {z:.1f})')
    build_distance_matrix(positions, out_path)


if __name__ == '__main__':
    main()
