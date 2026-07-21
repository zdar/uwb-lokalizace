import csv
import sys


def build_layout_matrix(layout_ids, original_path='point_distances.csv', out_path=None):
    """Build a distance matrix indexed by module ID for a given physical layout.

    layout_ids: list of 10 module IDs, where layout_ids[i] is the module at physical point Ai.
    """
    with open(original_path, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    header = [h.strip() for h in rows[0]]
    # Original matrix is symmetric; index by physical point label.
    idx = {label: i for i, label in enumerate(header)}
    n = 10
    # point_dist[i][j] = distance in meters between physical point Ai and Aj
    point_dist = [[0.0] * n for _ in range(n)]
    for i, row in enumerate(rows[1:]):
        for j, val in enumerate(row[1:]):
            point_dist[i][j] = float(val)

    # Create reverse map: module_id -> physical point index
    module_to_point = {}
    for point_idx, module_id in enumerate(layout_ids):
        module_to_point[int(module_id)] = point_idx

    # Build module-to-module distance matrix
    module_labels = [str(i) for i in range(n)]
    out_rows = [['Point'] + [f'A{i}' for i in range(n)]]
    for mi in range(n):
        pi = module_to_point[mi]
        row = [f'A{mi}']
        for mj in range(n):
            pj = module_to_point[mj]
            row.append(str(point_dist[pi][pj]))
        out_rows.append(row)

    if out_path:
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerows(out_rows)
        print(f'Wrote {out_path}')
    return out_rows


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python tmp_build_layout_matrix.py "4,8,6,2,7,3,1,9,0,5" output.csv')
        sys.exit(1)
    layout = [int(x.strip()) for x in sys.argv[1].split(',')]
    out = sys.argv[2]
    build_layout_matrix(layout, out_path=out)
