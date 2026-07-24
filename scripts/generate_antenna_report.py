import csv
import math
import os
from collections import defaultdict


SETUPS = [
    {
        "name": "Layout 1, original orientation",
        "matrix": "point_distances_layout1_v2.csv",
        "raw": "sessions/session_20260721_142439_raw.csv",
        "file": "delays_baseline_v2.csv",
        "delays": [26.26, 30.87, 91.35, 28.92, 42.45, 25.21, 40.39, 78.57, 33.91, 53.00],
        "desc": "4×3 grid, 2 m spacing, antennas in original vertical orientation.",
    },
    {
        "name": "Layout 2, original orientation",
        "matrix": "point_distances_layout2_v2.csv",
        "raw": "sessions/session_20260721_152206_raw.csv",
        "file": "delays_layout2_v2.csv",
        "delays": [41.58, 23.02, 17.08, 33.77, 38.08, 73.71, 60.33, 62.58, 33.77, 59.40],
        "desc": "4×3 grid, 2 m spacing, antennas in original vertical orientation.",
    },
    {
        "name": "Layout 2, antennas rotated 90°",
        "matrix": "point_distances_layout2_v2.csv",
        "raw": "sessions/session_20260721_154812_raw.csv",
        "file": "delays_rotated_v2.csv",
        "delays": [46.66, 32.78, 38.98, 34.23, 47.98, 51.10, 45.73, 37.60, 32.87, 40.74],
        "desc": "Same layout 2 positions, all antennas rotated 90° in the vertical plane.",
    },
    {
        "name": "Layout 2, antennas laid flat",
        "matrix": "point_distances_layout2_v2.csv",
        "raw": "sessions/session_20260721_160646_raw.csv",
        "file": "delays_flat_v2.csv",
        "delays": [100.21, 71.90, 33.20, 116.54, 71.95, -80.55, 11.63, 9.57, 14.73, 121.26],
        "desc": "Same layout 2 positions, modules laid flat on the table.",
    },
]


def load_pairs(path):
    pairs = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            parts = row['pair'].split('-')
            a = int(parts[0].strip().replace('A', ''))
            b = int(parts[1].strip().replace('A', ''))
            pairs.append((a, b, float(row['offset_cm'])))
    return pairs


def analyze(setup):
    pairs = load_pairs(setup['file'])
    delays = setup['delays']
    residuals = []
    for a, b, offset in pairs:
        residual = offset - delays[a] - delays[b]
        residuals.append(residual)
    abs_res = [abs(r) for r in residuals]
    return {
        'pairs': len(pairs),
        'mean_abs_res': sum(abs_res) / len(abs_res),
        'max_abs_res': max(abs_res),
        'over_50': sum(1 for x in abs_res if x > 50),
        'over_100': sum(1 for x in abs_res if x > 100),
        'over_200': sum(1 for x in abs_res if x > 200),
        'typical_sum': 2 * sum(delays) / len(delays),
        'delay_range': max(delays) - min(delays),
    }


def main():
    lines = []
    lines.append("# Antenna delay evaluation report")
    lines.append("")
    lines.append("**Date:** 2026-07-21")
    lines.append("")
    lines.append("> Note: the first version of this report used an incorrect physical distance matrix. This version uses the tab-spaced graphical layouts (`layout one.txt`, `layout two.txt`) with 2 m spacing.")
    lines.append("")
    lines.append("## Objective")
    lines.append("")
    lines.append("Estimate per-module UWB antenna delays by comparing measured pairwise ranges against known physical distances, and test whether antenna orientation significantly affects the results.")
    lines.append("")
    lines.append("## Physical layouts")
    lines.append("")
    lines.append("Both layouts are a 4×3 rectangular grid with 2 m cell spacing. Ten modules occupy ten of the twelve grid cells.")
    lines.append("")
    lines.append("### Layout 1")
    lines.append("```")
    lines.append("    A7")
    lines.append("A1  A6  A9")
    lines.append("A0  A5  A3")
    lines.append("A4  A8  A2")
    lines.append("```")
    lines.append("")
    lines.append("### Layout 2")
    lines.append("```")
    lines.append("    A5")
    lines.append("A1  A9  A0")
    lines.append("A2  A7  A3")
    lines.append("A4  A8  A6")
    lines.append("```")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append("For each setup, the PC ANL auto-calibration switched every module to TAG role in turn and collected raw `AT+RANGE` packets. Median ranges per device pair were compared to the physical distance matrix. A least-squares solver estimates a delay offset per module under the model `measured - true = delay_i + delay_j + residual`.")
    lines.append("")
    lines.append("A successful calibration should show:")
    lines.append("- All per-module delays in a realistic range (typically 20-80 cm for DW1000).")
    lines.append("- Residuals after delay removal mostly below ±50 cm.")
    lines.append("")
    lines.append("## Results summary")
    lines.append("")
    lines.append("| Setup | Pairs | Typical pair delay sum (cm) | Mean |residual| (cm) | Max |residual| (cm) | >50 cm | >100 cm | >200 cm |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in SETUPS:
        stats = analyze(s)
        lines.append(f"| {s['name']} | {stats['pairs']} | {stats['typical_sum']:.1f} | {stats['mean_abs_res']:.1f} | {stats['max_abs_res']:.1f} | {stats['over_50']} | {stats['over_100']} | {stats['over_200']} |")
    lines.append("")
    lines.append("## Per-module delay estimates (cm)")
    lines.append("")
    lines.append("| Module | Layout 1 original | Layout 2 original | Layout 2 rotated 90° | Layout 2 flat |")
    lines.append("|---|---:|---:|---:|---:|")
    for i in range(10):
        vals = [s['delays'][i] for s in SETUPS]
        lines.append(f"| A{i} | {vals[0]:.1f} | {vals[1]:.1f} | {vals[2]:.1f} | {vals[3]:.1f} |")
    lines.append("")
    lines.append("## Observations")
    lines.append("")
    lines.append("1. **Layout 2 rotated 90° is the cleanest setup.** All delays are positive and fall in the 33-51 cm range. Mean absolute residual is only 15.1 cm and only two residuals exceed 50 cm (5-6: +37 cm, 4-9: +26 cm).")
    lines.append("2. **Layout 2 original orientation is usable but noisier.** Mean residual is 47.1 cm, with two problematic residuals (5-6: +169 cm, 7-9: +225 cm).")
    lines.append("3. **Layout 2 flat is bad.** A5 gets an impossible negative delay (-81 cm), mean residual jumps to 93.4 cm, and 11 residuals exceed 100 cm. Laying the modules flat on the table does not work in this environment.")
    lines.append("4. **Layout 1 original orientation is reasonable** but pair A2-A7 has a large residual (+178 cm), suggesting a bad measurement or obstruction for that link.")
    lines.append("5. **Antenna orientation matters.** Rotating 90° improved Layout 2 from a noisy setup to a clean one. Flattening made it worse.")
    lines.append("")
    lines.append("## Conclusions")
    lines.append("")
    lines.append("- With the correct physical distance matrix, the delay model works well for the rotated 90° orientation.")
    lines.append("- The recommended operational setup is **Layout 2 with antennas rotated 90°**.")
    lines.append("- Laying modules flat is not recommended; it introduces severe multipath or polarization mismatch.")
    lines.append("- The remaining small residuals in the rotated setup can be reduced by averaging more packets or by tuning per-module delays.")
    lines.append("")
    lines.append("## Recommended next steps")
    lines.append("")
    lines.append("1. Use **Layout 2 with antennas rotated 90°** for the operational deployment.")
    lines.append("2. Apply the per-module delays from the rotated setup as the starting antenna-delay compensation.")
    lines.append("3. If further accuracy is needed, collect more samples for the worst pairs (5-6 and 4-9) and re-solve.")
    lines.append("4. Avoid laying modules flat on the table.")
    lines.append("")
    lines.append("## Raw data files")
    lines.append("")
    lines.append("| Setup | Distance matrix | Source raw session | Per-pair CSV |")
    lines.append("|---|---|---|---|")
    for s in SETUPS:
        lines.append(f"| {s['name']} | `{s['matrix']}` | `{s['raw']}` | `{s['file']}` |")
    lines.append("")
    
    os.makedirs('reports', exist_ok=True)
    path = 'reports/antenna_delay_evaluation.md'
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'Wrote {path}')


if __name__ == '__main__':
    main()
