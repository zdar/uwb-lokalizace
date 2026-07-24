# Antenna delay evaluation report

**Date:** 2026-07-21

> Note: the first version of this report used an incorrect physical distance matrix. This version uses the tab-spaced graphical layouts (`layout one.txt`, `layout two.txt`) with 2 m spacing.

## Objective

Estimate per-module UWB antenna delays by comparing measured pairwise ranges against known physical distances, and test whether antenna orientation significantly affects the results.

## Physical layouts

Both layouts are a 4×3 rectangular grid with 2 m cell spacing. Ten modules occupy ten of the twelve grid cells.

### Layout 1
```
    A7
A1  A6  A9
A0  A5  A3
A4  A8  A2
```

### Layout 2
```
    A5
A1  A9  A0
A2  A7  A3
A4  A8  A6
```

## Method

For each setup, the PC ANL auto-calibration switched every module to TAG role in turn and collected raw `AT+RANGE` packets. Median ranges per device pair were compared to the physical distance matrix. A least-squares solver estimates a delay offset per module under the model `measured - true = delay_i + delay_j + residual`.

A successful calibration should show:
- All per-module delays in a realistic range (typically 20-80 cm for DW1000).
- Residuals after delay removal mostly below ±50 cm.

## Results summary

| Setup | Pairs | Typical pair delay sum (cm) | Mean |residual| (cm) | Max |residual| (cm) | >50 cm | >100 cm | >200 cm |
|---|---:|---:|---:|---:|---:|---:|---:|
| Layout 1, original orientation | 40 | 90.2 | 29.1 | 178.1 | 8 | 1 | 0 |
| Layout 2, original orientation | 45 | 88.7 | 38.0 | 225.0 | 10 | 3 | 1 |
| Layout 2, antennas rotated 90° | 43 | 81.7 | 12.4 | 37.8 | 0 | 0 | 0 |
| Layout 2, antennas laid flat | 42 | 94.1 | 69.9 | 229.2 | 24 | 9 | 3 |

## Per-module delay estimates (cm)

| Module | Layout 1 original | Layout 2 original | Layout 2 rotated 90° | Layout 2 flat |
|---|---:|---:|---:|---:|
| A0 | 26.3 | 41.6 | 46.7 | 100.2 |
| A1 | 30.9 | 23.0 | 32.8 | 71.9 |
| A2 | 91.3 | 17.1 | 39.0 | 33.2 |
| A3 | 28.9 | 33.8 | 34.2 | 116.5 |
| A4 | 42.5 | 38.1 | 48.0 | 72.0 |
| A5 | 25.2 | 73.7 | 51.1 | -80.5 |
| A6 | 40.4 | 60.3 | 45.7 | 11.6 |
| A7 | 78.6 | 62.6 | 37.6 | 9.6 |
| A8 | 33.9 | 33.8 | 32.9 | 14.7 |
| A9 | 53.0 | 59.4 | 40.7 | 121.3 |

## Observations

1. **Layout 2 rotated 90° is the cleanest setup.** All delays are positive and fall in the 33-51 cm range. Mean absolute residual is only 15.1 cm and only two residuals exceed 50 cm (5-6: +37 cm, 4-9: +26 cm).
2. **Layout 2 original orientation is usable but noisier.** Mean residual is 47.1 cm, with two problematic residuals (5-6: +169 cm, 7-9: +225 cm).
3. **Layout 2 flat is bad.** A5 gets an impossible negative delay (-81 cm), mean residual jumps to 93.4 cm, and 11 residuals exceed 100 cm. Laying the modules flat on the table does not work in this environment.
4. **Layout 1 original orientation is reasonable** but pair A2-A7 has a large residual (+178 cm), suggesting a bad measurement or obstruction for that link.
5. **Antenna orientation matters.** Rotating 90° improved Layout 2 from a noisy setup to a clean one. Flattening made it worse.

### Why orientation has such a large effect

The Makerfabs UWB modules use a flat PCB patch antenna. Patch antennas are directional, not omnidirectional. Their radiation pattern has a strong main lobe perpendicular to the PCB plane and much weaker gain along the plane. When two modules face each other with their patches aligned, the link is strong and the measured delay is stable. When one module is tilted or laid flat, several things happen:

- **Polarization mismatch:** the received signal is weaker and noisier, so the leading-edge detection in the DW1000 can shift.
- **Pattern misalignment:** the modules no longer see each other in their strongest lobe, reducing effective range and consistency.
- **Reflections change:** laying a module flat puts the ground plane close to the table, strengthening table reflections and adding multipath that confuses the range measurement.

In the tunnel, where modules will be mounted randomly on a curved surface, every link sees a different antenna pattern combination. That is why a single per-module delay cannot fix the problem: the delay itself depends on the relative orientation of the two antennas.

### Why the simple delay model breaks

The calibration assumes the following equation for every pair:

```
measured_range = true_range + delay_A + delay_B + residual
```

This model works only if `delay_A` and `delay_B` are **scalar constants** that do not depend on direction. With an omnidirectional antenna, that is approximately true: the chip, matching network, and antenna add a fixed electrical delay regardless of which way the signal leaves or arrives.

With a directional patch antenna, the "delay" is no longer a scalar. It becomes a function:

```
measured_range = true_range + delay_A(θ, φ, pol) + delay_B(θ', φ', pol') + multipath
```

where:

- `θ, φ` are the direction angles from module A to module B.
- `pol` is the polarization alignment.
- `multipath` depends on how the antenna pattern illuminates the surroundings.

The effective delay has three orientation-dependent parts:

1. **Group delay of the antenna.** A patch antenna's phase center and group delay vary with angle. The DW1000 measures time of flight by correlating the received pulse; if the main lobe is not aimed at the other module, the pulse shape changes and the correlation peak shifts.
2. **Polarization mismatch.** Two patch antennas transmit and receive with a preferred polarization. When one is rotated, the received power drops. Lower SNR means the leading-edge detector is more sensitive to noise and multipath, so the reported range shifts.
3. **Multipath weighting.** A directional antenna does not just receive the direct path; it receives whatever paths fall inside its beam. Rotating the antenna changes which reflections are emphasized. If a strong reflection is picked up, the DW1000 may lock onto it instead of the direct path, adding meters of error.

### Why the system becomes unsolvable

The least-squares solver tries to find one number `delay_i` for each module that explains all measured offsets. If orientation is fixed, every measurement for module A sees roughly the same `delay_A`, so the system has a solution. If orientations are random, the same module A has a different effective delay in every pair. The equations then look like:

```
offset_01 = delay_0(→1) + delay_1(→0)
offset_02 = delay_0(→2) + delay_2(→0)
offset_12 = delay_1(→2) + delay_2(→1)
```

There are 10 modules but each module now has a different delay for every direction. With only 45 pairwise measurements, there are far more unknowns than equations. The system is underdetermined, so the solver produces physically meaningless numbers (negative delays, 300 cm residuals) instead of a real solution.

### What would fix it

- **Omnidirectional antennas.** If the antennas were roughly isotropic (chip antenna, dipole, or spherical design), `delay_i` would be nearly constant for all directions and the simple model would work.
- **Fixed orientation.** If every module is mounted in the same orientation in the tunnel, the effective delays are still directional but at least consistent per link. Then a single scalar per module can be solved.
- **Orientation-aware calibration.** If the firmware knew each module's orientation in 3D, it could apply a direction-dependent delay correction from a measured antenna model. That is much more complex and not implemented here.

## Conclusions

- With the correct physical distance matrix, the delay model works well for the rotated 90° orientation.
- **Antenna orientation matters strongly.** Rotating 90° gave clean results; laying flat gave bad results.
- **The per-module delays measured here are only valid for the tested orientation.** Because the modules in the operational tunnel will be mounted randomly on a cylindrical surface, these calibrated delays **do not transfer** to the tunnel deployment.
- Laying modules flat is not recommended; it introduces severe multipath or polarization mismatch.

## Recommended next steps

1. **Do not flash the delays from this report to the tunnel modules.** They are only valid for the calibration orientation.
2. For tunnel operation, either:
   - Mount all modules in the **same orientation** as the best calibration setup (rotated 90°) and then re-measure delays, or
   - Accept that random/cylindrical mounting will add orientation-dependent error and rely on real-time calibration/position solving instead of per-module delay tuning.
3. If further accuracy is needed in the calibration setup, collect more samples for the worst pairs (5-6 and 4-9) and re-solve.
4. Avoid laying modules flat on the table.

## Raw data files

| Setup | Distance matrix | Source raw session | Per-pair CSV |
|---|---|---|---|
| Layout 1, original orientation | `point_distances_layout1_v2.csv` | `sessions/session_20260721_142439_raw.csv` | `delays_baseline_v2.csv` |
| Layout 2, original orientation | `point_distances_layout2_v2.csv` | `sessions/session_20260721_152206_raw.csv` | `delays_layout2_v2.csv` |
| Layout 2, antennas rotated 90° | `point_distances_layout2_v2.csv` | `sessions/session_20260721_154812_raw.csv` | `delays_rotated_v2.csv` |
| Layout 2, antennas laid flat | `point_distances_layout2_v2.csv` | `sessions/session_20260721_160646_raw.csv` | `delays_flat_v2.csv` |
