#!/usr/bin/env python3
"""
pc_anl.py
=========

Prototype "ANL on the PC".

Run this on a PC that is on the same home WiFi as all UWB modules.
It discovers nodes, lets you switch their roles from a browser, collects
ranges for calibration, solves anchor positions, and displays live tag
positions.

    pip install flask
    python scripts/pc_anl.py

Then open the displayed URL in your browser.
"""

import os
import sys
import csv
import json
import socket
import time
import math
import threading
import webbrowser
from datetime import datetime
from collections import defaultdict

# Add project root so we can import positioning math.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, render_template_string, jsonify, request
from positioning.position import (
    parse_at_range_line,
    trilaterate,
    trilaterate_3d,
    _solve_least_squares_3d,
)

UDP_PORT = 50000
RAW_RPT_FORWARD_PORT = 50001   # forward raw RPT packets for qr_scanner.py
QR_EVENT_PORT = 50002          # receive QR scan events from ESP32-CAM
HEARTBEAT_TIMEOUT_MS = 15000
CAL3D_COLLECT_MS = 15000
QR_COLLECT_MS = 5000

# Auto-calibration (Mode A) timing.
AUTO_CAL_ROLE_SWITCH_WAIT_S = 40   # time for the UWB module to reconfigure after ROLE change
AUTO_CAL_COLLECT_S = 20            # how long to gather ranges per anchor

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
registry = {}           # ip -> {"id", "role", "last_seen_ms", "has_pos"}
anchors = {}            # id -> (x, y, z)    # positions set by user/calibration
tags = {}               # id -> {"ranges": {aid: distance}, "last_seen_ms", "pos": (x,y,z)}
discovery_running = False
log_lines = []

# 3D calibration state (mirror of firmware CAL3D)
cal3d = {
    "active": False,
    "tag_id": None,
    "point_idx": 0,
    "points": [],      # list of {"x", "y", "z", "samples": {aid: [distances]}}
    "timer_deadline": 0,
}

# Automatic sequential anchor calibration state (Mode A)
auto_cal = {
    "running": False,
    "origin_id": None,
    "fixed": {},              # id -> (x, y, z)
    "pending": [],            # list of ids still to calibrate
    "current_id": None,       # id currently acting as temporary tag
    "phase": "idle",          # idle, wait_tag, collecting, wait_anchor, wait_next, done, error
    "deadline_ms": 0,         # fallback safety timeout
    "samples": defaultdict(list),  # fixed_anchor_id -> [distances]
    "packet_count": 0,        # RPT packets received in current window
    "packets_needed": 15,     # stop collecting after this many packets
    "message": "",
    "succeeded": set(),       # ids calibrated successfully in this run
    "failed": set(),          # ids that could not be calibrated
    "auto_retried": False,    # whether an automatic retry of failed anchors already ran
}
auto_cal_lock = threading.Lock()

# QR-triggered measurement state.
# List of active collections, each a dict with scan metadata.
qr_active = []
qr_collect_lock = threading.Lock()

# UWB-local to real-world coordinate transform.
transform = {
    "active": False,
    "scale": 1.0,
    "theta": 0.0,
    "cos": 1.0,
    "sin": 0.0,
    "tx": 0.0,
    "ty": 0.0,
    "tz": 0.0,
    "pairs": [],  # list of {"point_id", "uwb": (x,y,z), "global": (x,y,z)}
}
transform_lock = threading.Lock()

# File used to persist anchor coordinates between sessions.
ANCHORS_FILE = os.path.join(PROJECT_ROOT, "anchors.json")

# Known reference points (trny) with global coordinates and QR codes.
TRNY_FILE = os.path.join(PROJECT_ROOT, "trny.json")

# Directory for session CSV output.
SESSIONS_DIR = os.path.join(PROJECT_ROOT, "sessions")


class SessionCsvWriter:
    """Append-only writer for one calibration/session CSV.

    Each section is written as a CSV block with its own header, preceded by
    a '# SECTION' marker line. Sections can be appended incrementally.
    """

    def __init__(self):
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath = os.path.join(SESSIONS_DIR, f"session_{timestamp}.csv")
        self.sections = set()
        # Start with an empty file.
        open(self.filepath, "w", encoding="utf-8").close()

    def _ensure_section(self, section, header):
        if section in self.sections:
            return
        with open(self.filepath, "a", newline="", encoding="utf-8") as f:
            f.write(f"\n# {section}\n")
            csv.writer(f).writerow(header)
        self.sections.add(section)

    def append_rows(self, section, header, rows):
        """Append multiple rows to a section, creating the header if needed."""
        if not rows:
            return
        self._ensure_section(section, header)
        with open(self.filepath, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)

    def write_session_info(self, origin_id):
        self.append_rows("SESSION", ["key", "value"], [
            ["session_start", datetime.now().isoformat()],
            ["origin_anchor_id", origin_id],
        ])

    def write_trny(self, points):
        rows = [[pid, p.get("x", 0), p.get("y", 0), p.get("z", 0), p.get("qr", "")]
                for pid, p in points.items()]
        self.append_rows("TRNY", ["id", "x", "y", "z", "qr_code"], rows)

    def append_anchor_raw(self, timestamp, anchor_id, fixed_anchor_id, distance):
        self.append_rows("ANCHOR_RAW", ["timestamp", "anchor_id", "fixed_anchor_id", "range"],
                         [[timestamp, anchor_id, fixed_anchor_id, distance]])

    def append_anchors_resolved(self, timestamp, anchors_dict):
        rows = [[aid, p[0], p[1], p[2]] for aid, p in anchors_dict.items()]
        self.append_rows("ANCHORS_RESOLVED", ["timestamp", "id", "x", "y", "z"], rows)

    def append_anchors_global(self, timestamp, anchors_dict):
        rows = [[aid, p[0], p[1], p[2]] for aid, p in anchors_dict.items()]
        self.append_rows("ANCHORS_GLOBAL", ["timestamp", "id", "x", "y", "z"], rows)

    def append_qr_computed(self, scan_id, timestamp, qr_code, point_id, point_xyz,
                           tag_id, sample_count, computed_xyz, source, global_xyz=None):
        x, y, z = point_xyz
        if computed_xyz and len(computed_xyz) >= 2:
            cx, cy = computed_xyz[0], computed_xyz[1]
            cz = computed_xyz[2] if len(computed_xyz) > 2 else 0.0
        else:
            cx = cy = cz = None
        if global_xyz and len(global_xyz) >= 2:
            gx, gy = global_xyz[0], global_xyz[1]
            gz = global_xyz[2] if len(global_xyz) > 2 else 0.0
        else:
            gx = gy = gz = None
        self.append_rows("QR_COMPUTED", [
            "scan_id", "timestamp", "qr_code", "point_id", "point_x", "point_y", "point_z",
            "tag_id", "sample_count", "computed_x", "computed_y", "computed_z", "source",
            "global_x", "global_y", "global_z"
        ], [[scan_id, timestamp, qr_code, point_id, x, y, z,
             tag_id, sample_count, cx, cy, cz, source, gx, gy, gz]])


session_csv = None
trny = {}  # id -> {"x", "y", "z", "qr"}


def load_trny():
    """Load known reference points (trny) from trny.json if it exists."""
    global trny
    if not os.path.exists(TRNY_FILE):
        trny = {}
        return
    try:
        with open(TRNY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        trny = {}
        for pid, p in data.items():
            try:
                trny[pid] = {
                    "x": float(p["x"]),
                    "y": float(p["y"]),
                    "z": float(p["z"]),
                    "qr": str(p.get("qr", "")),
                }
            except Exception:
                continue
        log(f"Loaded {len(trny)} reference point(s) from {TRNY_FILE}")
    except Exception as e:
        log(f"Failed to load trny: {e}")
        trny = {}


def load_anchors():
    """Load anchor coordinates from anchors.json if it exists."""
    if not os.path.exists(ANCHORS_FILE):
        return
    try:
        with open(ANCHORS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for aid, pos in data.items():
            try:
                anchors[int(aid)] = (float(pos[0]), float(pos[1]), float(pos[2]))
            except Exception:
                continue
        log(f"Loaded {len(anchors)} anchor(s) from {ANCHORS_FILE}")
    except Exception as e:
        log(f"Failed to load anchors: {e}")


def save_anchors():
    """Save current anchor coordinates to anchors.json and the session CSV."""
    try:
        data = {str(aid): [float(p[0]), float(p[1]), float(p[2])] for aid, p in anchors.items()}
        with open(ANCHORS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        if session_csv:
            session_csv.append_anchors_resolved(datetime.now().isoformat(), anchors)
            if transform["active"]:
                session_csv.append_anchors_global(datetime.now().isoformat(), {
                    aid: apply_transform(p) for aid, p in anchors.items()
                })
        log(f"Saved {len(anchors)} anchor(s) to {ANCHORS_FILE}")
    except Exception as e:
        log(f"Failed to save anchors: {e}")


def compute_similarity_transform(uwb_points, global_points):
    """Compute 2D similarity transform (rotation, scale, translation) plus z offset."""
    n = len(uwb_points)
    if n < 3:
        return None

    def _z(p):
        return p[2] if len(p) > 2 else 0.0

    cx_u = sum(p[0] for p in uwb_points) / n
    cy_u = sum(p[1] for p in uwb_points) / n
    cx_g = sum(p[0] for p in global_points) / n
    cy_g = sum(p[1] for p in global_points) / n
    cz_u = sum(_z(p) for p in uwb_points) / n
    cz_g = sum(_z(p) for p in global_points) / n

    sum_xu2 = sum_yu2 = sum_xuyu = sum_xuxg = sum_yuxg = 0.0
    sum_xuyg = sum_yuyg = 0.0
    for (xu, yu, _), (xg, yg, _) in zip(uwb_points, global_points):
        dxu = xu - cx_u
        dyu = yu - cy_u
        dxg = xg - cx_g
        dyg = yg - cy_g
        sum_xu2 += dxu * dxu
        sum_yu2 += dyu * dyu
        sum_xuyu += dxu * dyu
        sum_xuxg += dxu * dxg
        sum_yuxg += dyu * dxg
        sum_xuyg += dxu * dyg
        sum_yuyg += dyu * dyg

    det = sum_xu2 * sum_yu2 - sum_xuyu * sum_xuyu
    if abs(det) < 1e-9:
        return None

    a = (sum_xuxg * sum_yu2 - sum_xuyu * sum_yuxg) / det
    b = (sum_xu2 * sum_yuxg - sum_xuxg * sum_xuyu) / det

    scale = math.sqrt(a * a + b * b)
    if scale < 1e-9:
        return None

    theta = math.atan2(b, a)
    cos_t, sin_t = a / scale, b / scale
    tx = cx_g - scale * (cos_t * cx_u - sin_t * cy_u)
    ty = cy_g - scale * (sin_t * cx_u + cos_t * cy_u)
    tz = cz_g - cz_u

    return {
        "scale": scale,
        "theta": theta,
        "cos": cos_t,
        "sin": sin_t,
        "tx": tx,
        "ty": ty,
        "tz": tz,
    }


def apply_transform(p):
    """Apply the active UWB-local to global transform to a point (x, y, z)."""
    if not transform["active"]:
        return p
    x, y = p[0], p[1]
    z = p[2] if len(p) > 2 else 0.0
    s = transform["scale"]
    c = transform["cos"]
    s_ = transform["sin"]
    xg = s * (c * x - s_ * y) + transform["tx"]
    yg = s * (s_ * x + c * y) + transform["ty"]
    zg = z + transform["tz"]
    return (xg, yg, zg)


def reset_transform():
    """Clear the global coordinate transform and all scanned pairs."""
    with transform_lock:
        transform["active"] = False
        transform["scale"] = 1.0
        transform["theta"] = 0.0
        transform["cos"] = 1.0
        transform["sin"] = 0.0
        transform["tx"] = 0.0
        transform["ty"] = 0.0
        transform["tz"] = 0.0
        transform["pairs"].clear()


def start_qr_collection(qr_code):
    """Start collecting UWB ranges for a QR-scanned reference point."""
    point = None
    point_id = None
    for pid, p in trny.items():
        if p.get("qr") == qr_code:
            point = p
            point_id = pid
            break

    if point is None:
        log(f"[QR] Unknown QR code: {qr_code}")
        return False

    scan_id = datetime.now().strftime("%Y%m%d%H%M%S")
    collection = {
        "active": True,
        "scan_id": scan_id,
        "qr_code": qr_code,
        "point_id": point_id,
        "point_xyz": (point["x"], point["y"], point["z"]),
        "tag_id": None,
        "start_ms": time.time() * 1000,
        "duration_ms": QR_COLLECT_MS,
        "samples": defaultdict(list),
        "packet_count": 0,
    }
    with qr_collect_lock:
        qr_active.append(collection)
    log(f"[QR] Started collection for {qr_code} (point {point_id}, {QR_COLLECT_MS}ms)")
    threading.Timer(QR_COLLECT_MS / 1000.0, lambda c=collection: finish_qr_collection(c)).start()
    return True


def finish_qr_collection(collection):
    """Finish a QR-triggered measurement and write it to the session CSV."""
    with qr_collect_lock:
        if collection not in qr_active:
            return
        qr_active.remove(collection)

    if not collection["active"]:
        return
    collection["active"] = False

    scan_id = collection["scan_id"]
    qr_code = collection["qr_code"]
    point_id = collection["point_id"]
    point_xyz = collection["point_xyz"]
    tag_id = collection["tag_id"]
    samples = dict(collection["samples"])

    if tag_id is None or not samples:
        log(f"[QR] No UWB data received for {qr_code}")
        return

    median_ranges = {}
    for aid, dists in samples.items():
        if dists:
            m = median(dists)
            if m is not None and m > 0:
                median_ranges[aid] = m

    # Compute tag position using currently calibrated anchors if possible.
    computed_xyz = solve_tag_position(median_ranges)
    source = "UWB" if computed_xyz else "NONE"
    global_xyz = None

    if computed_xyz:
        # Store this scan as a mapping pair for real-world calibration.
        with transform_lock:
            transform["pairs"].append({
                "point_id": point_id,
                "uwb": computed_xyz,
                "global": point_xyz,
            })
        if transform["active"]:
            global_xyz = apply_transform(computed_xyz)
    else:
        computed_xyz = (None, None, None)

    ts = datetime.now().isoformat()
    if session_csv:
        # Write every individual range sample to QR_RAW.
        raw_rows = []
        for aid, dists in samples.items():
            for d in dists:
                raw_rows.append([scan_id, ts, qr_code, tag_id, aid, d])
        session_csv.append_rows("QR_RAW",
            ["scan_id", "timestamp", "qr_code", "tag_id", "anchor_id", "range"], raw_rows)
        session_csv.append_qr_computed(scan_id, ts, qr_code, point_id, point_xyz,
                                       tag_id, sum(len(v) for v in samples.values()),
                                       computed_xyz, source, global_xyz)

    log(f"[QR] Saved {qr_code}: ranges={len(median_ranges)}, computed={computed_xyz}, global={global_xyz}")


def log(msg):
    t = datetime.now().strftime("%H:%M:%S")
    line = f"[{t}] {msg}"
    print(line)
    log_lines.append(line)
    if len(log_lines) > 200:
        log_lines.pop(0)


def get_pc_ip():
    """Best guess at the local IP used for the default route."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "0.0.0.0"


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def median(values):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def solve_anchor_position(known_points, ranges):
    """
    known_points: list of (x, y, z)
    ranges:       list of distances from the anchor to those points
    Returns (x, y, z) or None.
    """
    valid = [(p, r) for p, r in zip(known_points, ranges) if r is not None and r > 0]
    if len(valid) < 4:
        return None

    pts = [p for p, _ in valid]
    rad = [r for _, r in valid]
    # Reuse trilaterate_3d shape by pretending the anchor is a tag and the known points are anchors.
    anchors_dict = {i: p for i, p in enumerate(pts)}
    ranges_dict = {i: r for i, r in enumerate(rad)}
    return trilaterate_3d(ranges_dict, anchors_dict)


def solve_tag_position(ranges):
    """ranges: dict {anchor_id: distance}."""
    valid = {aid: r for aid, r in ranges.items() if r is not None and r > 0 and aid in anchors}
    if len(valid) >= 4:
        pos = trilaterate_3d(valid, anchors)
        if pos:
            return pos
        log("3D tag solve failed, trying 2D fallback")
    if len(valid) >= 3:
        return trilaterate(valid, anchors)
    return None


def _dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _norm(v):
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])


def _scale(v, s):
    return (v[0]*s, v[1]*s, v[2]*s)


def _add(a, b):
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])


def _sub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def _cross(a, b):
    return (a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0])


def trilaterate_3d_3spheres(p0, p1, p2, r0, r1, r2):
    """
    Explicit intersection of three spheres. Returns (x, y, z) with +Z,
    or None if geometry is degenerate.
    """
    # Translate p0 to origin.
    ex_prime = _sub(p1, p0)
    d = _norm(ex_prime)
    if d < 1e-6:
        return None
    ex = _scale(ex_prime, 1.0 / d)

    p2_prime = _sub(p2, p0)
    i = _dot(p2_prime, ex)
    ey_prime = _sub(p2_prime, _scale(ex, i))
    j_len = _norm(ey_prime)
    if j_len < 1e-6:
        return None
    ey = _scale(ey_prime, 1.0 / j_len)
    ez = _cross(ex, ey)
    j = _dot(p2_prime, ey)

    x = (r0*r0 - r1*r1 + d*d) / (2.0 * d)
    y = (r0*r0 - r2*r2 + i*i + j*j - 2.0*i*x) / (2.0 * j)
    z2 = r0*r0 - x*x - y*y
    if z2 < -1e-6:
        return None
    z = math.sqrt(max(z2, 0.0))

    # Pick +Z side relative to the plane normal ez.
    return _add(p0, _add(_add(_scale(ex, x), _scale(ey, y)), _scale(ez, z)))


def solve_sequential_anchor(ranges_to_fixed, fixed):
    """
    Solve an anchor position from ranges to already-fixed anchors, mirroring
    the firmware's sequential auto-calibration.

    fixed: dict {anchor_id: (x, y, z)}
    ranges_to_fixed: dict {anchor_id: distance}
    Returns (x, y, z) or None.
    """
    valid = [(fixed[aid], r) for aid, r in ranges_to_fixed.items()
             if aid in fixed and r is not None and r > 0]
    if not valid:
        return None

    # 1 fixed anchor -> place on +X axis relative to it.
    if len(valid) == 1:
        (x0, y0, z0), r = valid[0]
        return (x0 + r, y0, z0)

    # 2 fixed anchors -> circle intersection, pick +Y side.
    if len(valid) == 2:
        (x0, y0, z0), r0 = valid[0]
        (x1, y1, z1), r1 = valid[1]
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        d = math.sqrt(dx*dx + dy*dy + dz*dz)
        if d <= 0.0 or d > r0 + r1 or d < abs(r0 - r1):
            return None
        a = (r0*r0 - r1*r1 + d*d) / (2.0 * d)
        h = math.sqrt(max(r0*r0 - a*a, 0.0))
        xm = x0 + a * dx / d
        ym = y0 + a * dy / d
        zm = z0 + a * dz / d
        # Perpendicular in the XY plane (convention: anchors start in XY).
        ux, uy, uz = -dy, dx, 0.0
        ul = math.sqrt(ux*ux + uy*uy + uz*uz)
        if ul < 1e-6:
            ux, uy = 1.0, 0.0
        else:
            ux, uy = ux / ul, uy / ul
        return (xm + ux * h, ym + uy * h, zm)

    # 3+ fixed anchors. Try least-squares 3D if we have 4+ non-coplanar anchors.
    # Use the first valid fixed anchor as the reference for Z fallback.
    (x0, y0, z0), r0 = valid[0]

    if len(valid) >= 4:
        anchors_dict = {i: p for i, (p, _) in enumerate(valid)}
        ranges_dict = {i: r for i, (_, r) in enumerate(valid)}
        pos3d = trilaterate_3d(ranges_dict, anchors_dict)
        if pos3d:
            return pos3d

    # Either exactly 3 fixed anchors, or 4+ are coplanar and least-squares failed.
    # Use explicit 3-sphere intersection for the first three fixed anchors.
    (p0, r0), (p1, r1), (p2, r2) = valid[0], valid[1], valid[2]
    pos3d = trilaterate_3d_3spheres(p0, p1, p2, r0, r1, r2)
    if pos3d:
        return pos3d

    # Last resort: 2D fallback.
    anchors_dict = {i: (p[0], p[1]) for i, (p, _) in enumerate(valid[:3])}
    ranges_dict = {i: r for i, (_, r) in enumerate(valid[:3])}
    pos2d = trilaterate(ranges_dict, anchors_dict)
    if not pos2d:
        return None
    x, y = pos2d
    dx = x - x0
    dy = y - y0
    horiz2 = dx*dx + dy*dy
    h2 = r0*r0 - horiz2
    z = z0 + (math.sqrt(h2) if h2 > 0.0 else 0.0)
    return (x, y, z)


# ---------------------------------------------------------------------------
# UDP listener
# ---------------------------------------------------------------------------

def handle_rpt(text):
    parsed = parse_at_range_line(text)
    if not parsed:
        return
    tid, ranges = parsed
    now = time.time() * 1000
    if tid not in tags:
        tags[tid] = {"ranges": {}, "last_seen_ms": 0, "pos": None}
    tags[tid]["ranges"].update(ranges)
    tags[tid]["last_seen_ms"] = now

    # Add to active calibration window if any.
    if cal3d["active"] and cal3d["tag_id"] == tid:
        pt = cal3d["points"][cal3d["point_idx"]]
        for aid, dist in ranges.items():
            if 0 <= aid <= 9:
                pt["samples"].setdefault(aid, []).append(dist)

    # Add to automatic calibration samples when waiting for / collecting from a temporary tag.
    with auto_cal_lock:
        if (auto_cal["running"] and
                auto_cal["current_id"] == tid and
                auto_cal["phase"] in ("wait_tag", "collecting")):
            auto_cal["packet_count"] += 1
            ts = datetime.now().isoformat()
            for aid, dist in ranges.items():
                if 0 <= aid <= 9:
                    auto_cal["samples"].setdefault(aid, []).append(dist)
                    if session_csv:
                        session_csv.append_anchor_raw(ts, tid, aid, dist)
            if auto_cal["phase"] == "wait_tag":
                log(f"[AUTO] First RPT from tag {tid}; starting collection")
                auto_cal["phase"] = "collecting"
                auto_cal["deadline_ms"] = time.time() * 1000 + 30000  # max 30s collection

    # Add to active QR-triggered measurement windows if any.
    with qr_collect_lock:
        for coll in qr_active:
            if coll["active"]:
                coll["packet_count"] += 1
                if coll["tag_id"] is None:
                    coll["tag_id"] = tid
                if coll["tag_id"] == tid:
                    for aid, dist in ranges.items():
                        if 0 <= aid <= 9:
                            coll["samples"].setdefault(aid, []).append(dist)

    # Solve position if enough anchors are known.
    pos = solve_tag_position(tags[tid]["ranges"])
    if pos:
        tags[tid]["pos"] = pos


def qr_listener():
    """Listen for QR scan events from ESP32-CAM."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", QR_EVENT_PORT))
    except OSError as e:
        log(f"FATAL: cannot bind QR event port {QR_EVENT_PORT}: {e}")
        return
    sock.settimeout(1.0)
    log(f"Listening for QR events on port {QR_EVENT_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        except OSError:
            break

        text = data.decode("utf-8", errors="ignore").strip()
        if text.startswith("QR,"):
            qr_code = text[3:].strip()
            if qr_code:
                start_qr_collection(qr_code)


def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", UDP_PORT))
    except OSError as e:
        log(f"FATAL: cannot bind UDP port {UDP_PORT}: {e}")
        return
    sock.settimeout(1.0)
    log(f"Listening for UDP on port {UDP_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        except OSError:
            break

        text = data.decode("utf-8", errors="ignore").strip()
        ip = addr[0]

        if text.startswith("PONG,"):
            parts = text.split(",")
            if len(parts) >= 4:
                registry[ip] = {
                    "id": int(parts[1]),
                    "role": int(parts[2]),
                    "last_seen_ms": time.time() * 1000,
                    "has_pos": False,
                }
        elif text.startswith("HB,"):
            parts = text.split(",")
            if len(parts) >= 3:
                registry[ip] = {
                    "id": int(parts[1]),
                    "role": int(parts[2]),
                    "last_seen_ms": time.time() * 1000,
                    "has_pos": False,
                }
        elif text.startswith("RPT,"):
            handle_rpt(text[4:])


def discovery_task():
    global discovery_running
    discovery_running = True
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.5)
    try:
        sock.bind(("0.0.0.0", 0))
    except OSError:
        discovery_running = False
        return

    # Compute broadcast from local IP.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        parts = local_ip.split(".")
        broadcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
    except Exception:
        broadcast = "255.255.255.255"

    for _ in range(3):
        sock.sendto(b"PING", (broadcast, UDP_PORT))
        time.sleep(0.2)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        text = data.decode("utf-8", errors="ignore").strip()
        if text.startswith("PONG,"):
            parts = text.split(",")
            if len(parts) >= 4:
                registry[addr[0]] = {
                    "id": int(parts[1]),
                    "role": int(parts[2]),
                    "last_seen_ms": time.time() * 1000,
                    "has_pos": False,
                }

    sock.close()
    discovery_running = False


# ---------------------------------------------------------------------------
# Auto-calibration helpers
# ---------------------------------------------------------------------------

def get_node_ip_by_id(node_id):
    """Return the most recent IP for a given UWB index, or None."""
    now = time.time() * 1000
    best = None
    best_age = float("inf")
    for ip, info in registry.items():
        if info["id"] == node_id and (now - info["last_seen_ms"]) < HEARTBEAT_TIMEOUT_MS:
            age = now - info["last_seen_ms"]
            if age < best_age:
                best_age = age
                best = ip
    return best


def send_role_udp(ip, role):
    """Send ROLE command to a node's IP. Returns True on success."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.sendto(f"ROLE,{role}".encode(), (ip, UDP_PORT))
        return True
    except Exception as e:
        log(f"Failed to send ROLE,{role} to {ip}: {e}")
        return False
    finally:
        sock.close()


def auto_cal_reset():
    """Clear auto-calibration state."""
    with auto_cal_lock:
        auto_cal["running"] = False
        auto_cal["origin_id"] = None
        auto_cal["fixed"].clear()
        auto_cal["pending"].clear()
        auto_cal["current_id"] = None
        auto_cal["phase"] = "idle"
        auto_cal["deadline_ms"] = 0
        auto_cal["samples"] = defaultdict(list)
        auto_cal["packet_count"] = 0
        auto_cal["message"] = ""
        auto_cal["succeeded"].clear()
        auto_cal["failed"].clear()
        auto_cal["auto_retried"] = False


def auto_cal_loop():
    """Background thread implementing output-driven sequential anchor calibration."""
    while True:
        with auto_cal_lock:
            if not auto_cal["running"]:
                return
            phase = auto_cal["phase"]
            deadline = auto_cal["deadline_ms"]
            current_id = auto_cal["current_id"]
            packets_needed = auto_cal["packets_needed"]

        now_ms = time.time() * 1000

        if phase == "wait_tag":
            # Wait for the first RPT from the temporary tag. Fall back to a
            # hard timeout so we don't hang forever if the module is stuck.
            with auto_cal_lock:
                has_samples = bool(auto_cal["samples"])
                timed_out = now_ms >= deadline

            if not has_samples and not timed_out:
                time.sleep(0.2)
                continue

            if not has_samples and timed_out:
                log(f"[AUTO] Timeout waiting for tag {current_id} RPT")
                # Switch it back anyway so we don't leave it stuck as TAG.
                ip = get_node_ip_by_id(current_id)
                if ip:
                    send_role_udp(ip, 1)
                with auto_cal_lock:
                    auto_cal["failed"].add(current_id)
                    auto_cal["message"] = f"Timeout on tag {current_id}; switching back"
                    auto_cal["phase"] = "wait_anchor"
                    auto_cal["deadline_ms"] = now_ms + 60000
                continue

            # First RPT already moved us to collecting in handle_rpt.
            continue

        if phase == "collecting":
            with auto_cal_lock:
                packet_count = auto_cal["packet_count"]
                timed_out = now_ms >= deadline

            if packet_count < packets_needed and not timed_out:
                time.sleep(0.2)
                continue

            # Done collecting.
            with auto_cal_lock:
                samples = auto_cal["samples"]
                fixed = dict(auto_cal["fixed"])
                current_id = auto_cal["current_id"]
                actual_packets = auto_cal["packet_count"]

            # Compute median ranges to already-fixed anchors.
            median_ranges = {}
            for aid, dists in samples.items():
                if aid in fixed and dists:
                    m = median(dists)
                    if m is not None and m > 0:
                        median_ranges[aid] = m

            log(f"[AUTO] Collected {actual_packets} packets from tag {current_id}, median ranges: {median_ranges}")
            pos = solve_sequential_anchor(median_ranges, fixed)

            if pos:
                anchors[current_id] = pos
                with auto_cal_lock:
                    auto_cal["fixed"][current_id] = pos
                    auto_cal["succeeded"].add(current_id)
                save_anchors()
                log(f"[AUTO] Anchor {current_id} fixed at ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
            else:
                with auto_cal_lock:
                    auto_cal["failed"].add(current_id)
                log(f"[AUTO] Failed to solve anchor {current_id}; switching back anyway")

            ip = get_node_ip_by_id(current_id)
            if ip:
                send_role_udp(ip, 1)
                log(f"[AUTO] Sent ROLE,1 to anchor {current_id}")
            else:
                log(f"[AUTO] No IP for {current_id} to send ROLE,1")

            with auto_cal_lock:
                auto_cal["phase"] = "wait_anchor"
                auto_cal["deadline_ms"] = now_ms + 60000
                auto_cal["message"] = f"Waiting for anchor {current_id} heartbeat"
            continue

        if phase == "wait_anchor":
            # Wait until the heartbeat says this node is an anchor again.
            role_is_anchor = False
            current_ip = None
            for ip, info in registry.items():
                if info.get("id") == current_id and info.get("role") == 1:
                    role_is_anchor = True
                    current_ip = ip
                    break

            if role_is_anchor:
                log(f"[AUTO] Anchor {current_id} is back in ANCHOR role")
                with auto_cal_lock:
                    auto_cal["current_id"] = None
                    auto_cal["phase"] = "wait_next"
                continue

            timed_out = now_ms >= deadline
            if timed_out:
                log(f"[AUTO] Timeout waiting for anchor {current_id} to return")
                with auto_cal_lock:
                    auto_cal["current_id"] = None
                    auto_cal["phase"] = "wait_next"
                continue

            # Retry switch command every 5 seconds until confirmed.
            last_retry_key = f"last_retry_{current_id}"
            last_retry = auto_cal.get(last_retry_key, 0)
            if now_ms - last_retry >= 5000:
                ip = get_node_ip_by_id(current_id)
                if ip:
                    send_role_udp(ip, 1)
                    log(f"[AUTO] Retry ROLE,1 to anchor {current_id}")
                with auto_cal_lock:
                    auto_cal[last_retry_key] = now_ms

            time.sleep(0.5)
            continue

        if phase == "wait_next":
            with auto_cal_lock:
                if auto_cal["pending"]:
                    next_id = auto_cal["pending"].pop(0)
                    auto_cal["current_id"] = next_id
                    auto_cal["phase"] = "wait_tag"
                    auto_cal["samples"] = defaultdict(list)
                    auto_cal["packet_count"] = 0
                    auto_cal["deadline_ms"] = now_ms + 60000
                    auto_cal["message"] = f"Switching anchor {next_id} to TAG"
                else:
                    auto_cal["phase"] = "done"
                    auto_cal["message"] = "Auto-calibration complete"
                    auto_cal["running"] = False
                    log("[AUTO] Calibration complete")
                    return

            ip = get_node_ip_by_id(next_id)
            if ip:
                send_role_udp(ip, 0)
                log(f"[AUTO] Sent ROLE,0 to anchor {next_id}")
            else:
                log(f"[AUTO] No IP for anchor {next_id}; skipping")
                with auto_cal_lock:
                    auto_cal["failed"].add(next_id)
                    auto_cal["phase"] = "wait_next"
                    auto_cal["current_id"] = None
            continue

        # Idle / done / error
        return


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

HTML_PAGE = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>PC ANL - UWB Prototype</title>
    <style>
        body { font-family: sans-serif; max-width: 1100px; margin: 30px auto; padding: 0 20px; }
        h1, h2 { color: #333; }
        button { padding: 8px 16px; margin: 4px 4px 4px 0; font-size: 14px; cursor: pointer; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        input[type="text"], input[type="number"] { padding: 6px; font-size: 14px; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        th { background: #eee; }
        .section { margin-top: 25px; padding: 15px; border: 1px solid #ddd; border-radius: 6px; }
        .row { margin: 6px 0; }
        #logBox { border: 1px solid #ccc; padding: 10px; height: 200px; overflow-y: auto; background: #f9f9f9; font-family: monospace; font-size: 12px; }
        .log-line { margin: 2px 0; }
        . stale { color: #888; }
        #setupModal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: #ffffff; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 1000; text-align: center; }
        #setupModal h1 { font-size: 32px; margin-bottom: 30px; }
        #setupModal p { font-size: 20px; margin: 10px 0; max-width: 600px; }
        #setupModal button { padding: 15px 40px; font-size: 18px; margin-top: 30px; }
        #mainContent { display: none; }
    </style>
</head>
<body>
    <div id="setupModal">
        <h1>PC ANL - UWB Prototype</h1>
        <p><strong>Rozmísti krabičky.</strong></p>
        <p>Klikni Pokračovat, až budou rozmístěny.</p>
        <button onclick="startSetupFlow()">Pokračovat</button>
        <p style="margin-top: 30px; font-size: 14px;">
            <a href="#" onclick="skipSetupFlow(); return false;" style="color: #666;">Vývojářský režim – přeskočit kalibraci</a>
        </p>
    </div>

    <div id="mainContent">
    <h1>PC ANL (prototype over home WiFi)</h1>
    <p>PC IP: <strong>{{ pc_ip }}</strong> | UDP port: <strong>50000</strong></p>

    <div class="section">
        <h2>1. Discover / control nodes</h2>
        <button id="discoverBtn" onclick="discover()">Discover nodes</button>
        <div id="nodeTable"></div>
    </div>

    <div class="section">
        <h2>2. Anchor positions</h2>
        <p>Manually enter positions (cm) or use the calibration panel below.</p>
        <div class="row">
            Anchor ID: <input type="number" id="anchorId" min="0" max="9" style="width:60px">
            X: <input type="number" id="anchorX" style="width:80px">
            Y: <input type="number" id="anchorY" style="width:80px">
            Z: <input type="number" id="anchorZ" style="width:80px">
            <button onclick="setAnchor()">Set anchor</button>
            <button onclick="saveAnchors()">Save anchors</button>
            <button onclick="loadAnchors()">Load anchors</button>
        </div>
        <p><strong>Fixed anchors:</strong> <span id="anchorCount">0</span></p>
        <div id="anchorList"></div>
    </div>

    <div class="section">
        <h2>3. Calibrate anchors with known tag points</h2>
        <p>Move the tag to a measured point, enter its coordinates, and start collection. Do at least 4 points, then solve.</p>
        <div class="row">
            Tag ID: <input type="number" id="calTagId" min="0" max="9" value="0" style="width:60px">
            X: <input type="number" id="calX" style="width:80px">
            Y: <input type="number" id="calY" style="width:80px">
            Z: <input type="number" id="calZ" style="width:80px">
            <button id="calPointBtn" onclick="addCalPoint()">Start 15s collection</button>
        </div>
        <div id="calStatus"></div>
        <button onclick="solveCal()">Solve anchors</button>
        <button onclick="clearCal()">Clear calibration</button>
    </div>

    <div class="section">
        <h2>4. Auto-calibrate anchors (Mode A)</h2>
        <p>The PC temporarily switches each anchor to TAG, collects ranges to already-fixed anchors, solves its position, and switches it back.</p>
        <div class="row">
            Origin anchor ID: <input type="number" id="autoCalOrigin" min="0" max="9" value="0" style="width:60px">
            <button id="autoCalStartBtn" onclick="startAutoCal()">Start auto-calibration</button>
            <button onclick="stopAutoCal()">Stop / reset</button>
        </div>
        <div id="autoCalStatus"></div>
    </div>

    <div class="section">
        <h2>5. Live tag positions</h2>
        <div id="tagPositions"></div>
    </div>

    <div class="section">
        <h2>6. Map to real world (trny)</h2>
        <p>Scan QR codes on the known trny points. Once you have at least 3 scans, compute the transform to global coordinates.</p>
        <div class="row">
            <button onclick="pollTransformStatus()">Refresh status</button>
            <button onclick="computeTransform()">Compute transform</button>
            <button onclick="clearTransform()">Clear transform</button>
        </div>
        <div id="transformStatus"></div>
    </div>

    <div class="section">
        <h2>Log</h2>
        <div id="logBox"></div>
    </div>

    </div>

    <script>
        let pollInterval = null;

        function startSetupFlow() {
            document.getElementById('setupModal').style.display = 'none';
            document.getElementById('mainContent').style.display = 'block';
            fetch('/discover', {method: 'POST'})
                .then(r => r.json())
                .then(() => pollDiscoveryForAutoCal());
        }

        function skipSetupFlow() {
            document.getElementById('setupModal').style.display = 'none';
            document.getElementById('mainContent').style.display = 'block';
        }

        function pollDiscoveryForAutoCal() {
            fetch('/discovery_status')
                .then(r => r.json())
                .then(data => {
                    if (data.running) {
                        setTimeout(pollDiscoveryForAutoCal, 500);
                        return;
                    }
                    const anchors = data.nodes.filter(n => n.role === 1);
                    if (anchors.length === 0) {
                        alert('Nebyly nalezeny žádné kotvičky. Zkontroluj, že jsou krabičky zapnuté a na stejné síti.');
                        return;
                    }
                    // Use the first discovered anchor as the calibration origin.
                    const originId = anchors[0].id;
                    fetch('/auto_cal_start', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({origin_id: originId})
                    }).then(r => r.json()).then(data => {
                        if (data.error) {
                            alert(data.error);
                            return;
                        }
                        pollAutoCalStatus();
                    });
                });
        }

        function discover() {
            document.getElementById('discoverBtn').disabled = true;
            fetch('/discover', {method: 'POST'})
                .then(r => r.json())
                .then(() => pollDiscovery());
        }

        function pollDiscovery() {
            fetch('/discovery_status')
                .then(r => r.json())
                .then(data => {
                    if (data.running) {
                        setTimeout(pollDiscovery, 400);
                        return;
                    }
                    document.getElementById('discoverBtn').disabled = false;
                    renderNodes(data.nodes);
                });
        }

        function renderNodes(nodes) {
            const div = document.getElementById('nodeTable');
            if (nodes.length === 0) {
                div.innerHTML = '<p>No nodes discovered yet.</p>';
                return;
            }
            nodes.sort((a, b) => a.id - b.id);
            let html = `<p>Connected: <strong>${nodes.length}</strong></p>`;
            html += '<table><tr><th>ID</th><th>IP</th><th>Role</th><th>Age (s)</th><th>Action</th></tr>';
            for (const n of nodes) {
                const target = n.role === 1 ? 'TAG' : 'ANCHOR';
                const roleNum = n.role === 1 ? '0' : '1';
                html += `<tr>
                    <td>${n.id}</td>
                    <td>${n.ip}</td>
                    <td>${n.role === 0 ? 'TAG' : 'ANCHOR'}</td>
                    <td>${(n.age_ms / 1000).toFixed(1)}</td>
                    <td><button onclick="switchRole('${n.ip}', '${roleNum}', '${n.id}', '${target}')">Switch to ${target}</button></td>
                </tr>`;
            }
            html += '</table>';
            div.innerHTML = html;
        }

        function switchRole(ip, roleNum, id, target) {
            if (!confirm(`Switch node ${id} (${ip}) to ${target}?`)) return;
            fetch('/switch_role', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ip: ip, role: roleNum, id: id})
            }).then(r => r.json()).then(data => {
                alert(data.message || data.error);
                refreshState();
            });
        }

        function setAnchor() {
            const id = document.getElementById('anchorId').value;
            const x = document.getElementById('anchorX').value;
            const y = document.getElementById('anchorY').value;
            const z = document.getElementById('anchorZ').value;
            fetch('/set_anchor', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id, x, y, z})
            }).then(r => r.json()).then(data => {
                if (data.error) alert(data.error);
                refreshState();
            });
        }

        function saveAnchors() {
            fetch('/save_anchors', {method: 'POST'})
                .then(r => r.json())
                .then(data => { alert(`Saved ${data.count} anchor(s)`); });
        }

        function loadAnchors() {
            fetch('/load_anchors', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    alert(`Loaded ${data.count} anchor(s)`);
                    refreshState();
                });
        }

        function addCalPoint() {
            const tag_id = document.getElementById('calTagId').value;
            const x = document.getElementById('calX').value;
            const y = document.getElementById('calY').value;
            const z = document.getElementById('calZ').value;
            const btn = document.getElementById('calPointBtn');
            btn.disabled = true;
            fetch('/cal_point', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({tag_id, x, y, z})
            }).then(r => r.json()).then(data => {
                if (data.error) alert(data.error);
                pollCalStatus();
            });
        }

        function pollCalStatus() {
            fetch('/cal_status')
                .then(r => r.json())
                .then(data => {
                    const div = document.getElementById('calStatus');
                    let html = `<p>Active: ${data.active}, Points: ${data.point_count}</p>`;
                    if (data.points) {
                        html += '<ul>';
                        for (const p of data.points) {
                            html += `<li>(${p.x}, ${p.y}, ${p.z}) — ${p.samples} samples</li>`;
                        }
                        html += '</ul>';
                    }
                    div.innerHTML = html;
                    if (data.active) {
                        setTimeout(pollCalStatus, 500);
                    } else {
                        document.getElementById('calPointBtn').disabled = false;
                    }
                });
        }

        function solveCal() {
            fetch('/cal_solve', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    alert(data.message || data.error);
                    refreshState();
                });
        }

        function clearCal() {
            fetch('/cal_clear', {method: 'POST'})
                .then(r => r.json())
                .then(data => { refreshState(); });
        }

        function startAutoCal() {
            const origin = document.getElementById('autoCalOrigin').value;
            document.getElementById('autoCalStartBtn').disabled = true;
            fetch('/auto_cal_start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({origin_id: origin})
            }).then(r => r.json()).then(data => {
                if (data.error) alert(data.error);
                pollAutoCalStatus();
            });
        }

        function stopAutoCal() {
            fetch('/auto_cal_stop', {method: 'POST'})
                .then(r => r.json())
                .then(data => { pollAutoCalStatus(); });
        }

        function pollAutoCalStatus() {
            fetch('/auto_cal_status')
                .then(r => r.json())
                .then(data => {
                    const div = document.getElementById('autoCalStatus');
                    let html = `<p><strong>Status:</strong> ${data.phase}</p>`;
                    if (data.message) {
                        html += `<p>${data.message}</p>`;
                    }
                    if (data.current_id !== null) {
                        html += `<p>Current tag: ${data.current_id}</p>`;
                        html += `<p>Packets: ${data.packet_count} / ${data.packets_needed}</p>`;
                    }
                    html += '<p><strong>Fixed anchors:</strong></p><ul>';
                    for (const [id, p] of Object.entries(data.fixed)) {
                        html += `<li>${id}: (${p[0].toFixed(2)}, ${p[1].toFixed(2)}, ${p[2].toFixed(2)})</li>`;
                    }
                    html += '</ul>';
                    if (data.pending && data.pending.length > 0) {
                        html += `<p><strong>Pending:</strong> ${data.pending.join(', ')}</p>`;
                    }
                    if (data.succeeded && data.succeeded.length > 0) {
                        html += `<p style="color:green"><strong>Successfully calibrated:</strong> ${data.succeeded.join(', ')}</p>`;
                    }
                    if (data.failed && data.failed.length > 0) {
                        html += `<p style="color:red"><strong>Failed:</strong> ${data.failed.join(', ')}</p>`;
                    }

                    const done = !data.running && data.phase === 'done';
                    const hasFailed = data.failed && data.failed.length > 0;

                    if (done && hasFailed) {
                        html += `<div style="margin-top:15px">`;
                        html += `<button onclick="retryFailedAutoCal()" style="margin-right:10px">Kalibrovat neúspěšné kotvičky</button>`;
                        html += `<button onclick="startFullAutoCal()">Nová plná kalibrace</button>`;
                        html += `</div>`;

                        // One automatic retry on the first unsuccessful run.
                        if (!data.auto_retried) {
                            html += `<p style="color:orange">Některé kotvičky se nepodařilo vykalibrovat. Zkouším to znovu automaticky...</p>`;
                            div.innerHTML = html;
                            retryFailedAutoCal();
                            refreshState();
                            return;
                        }
                    }
                    div.innerHTML = html;

                    if (data.running) {
                        setTimeout(pollAutoCalStatus, 1000);
                    } else {
                        document.getElementById('autoCalStartBtn').disabled = false;
                    }
                    refreshState();
                });
        }

        function retryFailedAutoCal() {
            const div = document.getElementById('autoCalStatus');
            div.innerHTML = '<p>Opakuji kalibraci neúspěšných kotviček...</p>';
            fetch('/auto_cal_retry_failed', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        alert(data.error);
                        return;
                    }
                    pollAutoCalStatus();
                });
        }

        function startFullAutoCal() {
            if (!confirm('Toto smaže všechny uložené pozice kotviček a spustí úplně novou kalibraci. Pokračovat?')) return;
            const div = document.getElementById('autoCalStatus');
            div.innerHTML = '<p>Mažu uložené pozice a vyhledávám kotvičky pro novou kalibraci...</p>';
            fetch('/reset_anchors', {method: 'POST'})
                .then(r => r.json())
                .then(() => fetch('/discover', {method: 'POST'}))
                .then(r => r.json())
                .then(() => pollDiscoveryForFullAutoCal());
        }

        function pollDiscoveryForFullAutoCal() {
            fetch('/discovery_status')
                .then(r => r.json())
                .then(data => {
                    if (data.running) {
                        setTimeout(pollDiscoveryForFullAutoCal, 500);
                        return;
                    }
                    const anchors = data.nodes.filter(n => n.role === 1);
                    if (anchors.length === 0) {
                        alert('Nebyly nalezeny žádné kotvičky. Zkontroluj, že jsou krabičky zapnuté a na stejné síti.');
                        return;
                    }
                    const originId = anchors[0].id;
                    fetch('/auto_cal_start', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({origin_id: originId})
                    }).then(r => r.json()).then(data => {
                        if (data.error) {
                            alert(data.error);
                            return;
                        }
                        pollAutoCalStatus();
                    });
                });
        }

        function refreshState() {
            fetch('/state')
                .then(r => r.json())
                .then(data => {
                    renderNodes(data.nodes);
                    const anchorIds = Object.keys(data.anchors);
                    document.getElementById('anchorCount').textContent = anchorIds.length;

                    const aDiv = document.getElementById('anchorList');
                    const showGlobal = data.transform_active;
                    let aHtml = showGlobal
                        ? '<table><tr><th>ID</th><th>UWB X</th><th>UWB Y</th><th>UWB Z</th><th>Global X</th><th>Global Y</th><th>Global Z</th></tr>'
                        : '<table><tr><th>ID</th><th>X</th><th>Y</th><th>Z</th></tr>';
                    for (const id of anchorIds) {
                        const p = data.anchors[id];
                        const g = data.anchors_global[id];
                        aHtml += `<tr><td>${id}</td><td>${p[0].toFixed(2)}</td><td>${p[1].toFixed(2)}</td><td>${p[2].toFixed(2)}</td>`;
                        if (showGlobal) {
                            aHtml += `<td>${g[0].toFixed(2)}</td><td>${g[1].toFixed(2)}</td><td>${g[2].toFixed(2)}</td>`;
                        }
                        aHtml += '</tr>';
                    }
                    aHtml += '</table>';
                    aDiv.innerHTML = aHtml;

                    const tDiv = document.getElementById('tagPositions');
                    let tHtml = showGlobal
                        ? '<table><tr><th>Tag ID</th><th>UWB X</th><th>UWB Y</th><th>UWB Z</th><th>Global X</th><th>Global Y</th><th>Global Z</th><th>Age (s)</th></tr>'
                        : '<table><tr><th>Tag ID</th><th>X</th><th>Y</th><th>Z</th><th>Age (s)</th></tr>';
                    for (const [id, t] of Object.entries(data.tags)) {
                        const pos = t.pos || [];
                        const gpos = t.global_pos || [];
                        const x = pos.length > 0 ? pos[0].toFixed(2) : '---';
                        const y = pos.length > 1 ? pos[1].toFixed(2) : '---';
                        const z = pos.length > 2 ? pos[2].toFixed(2) : '0.00';
                        const gx = gpos.length > 0 ? gpos[0].toFixed(2) : '---';
                        const gy = gpos.length > 1 ? gpos[1].toFixed(2) : '---';
                        const gz = gpos.length > 2 ? gpos[2].toFixed(2) : '0.00';
                        tHtml += `<tr><td>${id}</td><td>${x}</td><td>${y}</td><td>${z}</td>`;
                        if (showGlobal) {
                            tHtml += `<td>${gx}</td><td>${gy}</td><td>${gz}</td>`;
                        }
                        tHtml += `<td>${(t.age_ms / 1000).toFixed(1)}</td></tr>`;
                    }
                    tHtml += '</table>';
                    tDiv.innerHTML = tHtml;

                    const box = document.getElementById('logBox');
                    const cur = box.children.length;
                    for (let i = cur; i < data.log.length; i++) {
                        const div = document.createElement('div');
                        div.className = 'log-line';
                        div.textContent = data.log[i];
                        box.appendChild(div);
                        box.scrollTop = box.scrollHeight;
                    }
                });
        }

        function pollTransformStatus() {
            fetch('/transform_status')
                .then(r => r.json())
                .then(data => renderTransformStatus(data));
        }

        function renderTransformStatus(data) {
            const div = document.getElementById('transformStatus');
            let html = `<p><strong>Transform active:</strong> ${data.active ? 'YES' : 'NO'}</p>`;
            if (data.active) {
                html += `<p>Scale: ${data.scale.toFixed(4)}, Rotation: ${(data.theta * 180 / Math.PI).toFixed(2)}°, Offset: (${data.tx.toFixed(2)}, ${data.ty.toFixed(2)}, ${data.tz.toFixed(2)})</p>`;
            }
            html += `<p><strong>Scanned trny points:</strong> ${data.pairs.length}</p>`;
            if (data.pairs.length > 0) {
                html += '<table><tr><th>Point</th><th>UWB X</th><th>UWB Y</th><th>UWB Z</th><th>Global X</th><th>Global Y</th><th>Global Z</th></tr>';
                for (const p of data.pairs) {
                    const u = p.uwb;
                    const g = p.global;
                    html += `<tr><td>${p.point_id}</td>` +
                        `<td>${u[0].toFixed(2)}</td><td>${u[1].toFixed(2)}</td><td>${u[2].toFixed(2)}</td>` +
                        `<td>${g[0].toFixed(2)}</td><td>${g[1].toFixed(2)}</td><td>${g[2].toFixed(2)}</td></tr>`;
                }
                html += '</table>';
            }
            div.innerHTML = html;
        }

        function computeTransform() {
            fetch('/compute_transform', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.error) alert(data.error);
                    else {
                        alert('Transform computed successfully');
                        refreshState();
                    }
                    pollTransformStatus();
                });
        }

        function clearTransform() {
            if (!confirm('Clear the global coordinate transform and all scanned trny pairs?')) return;
            fetch('/clear_transform', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    refreshState();
                    pollTransformStatus();
                });
        }

        setInterval(refreshState, 1000);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_PAGE, pc_ip=get_pc_ip())


@app.route("/discover", methods=["POST"])
def discover():
    global discovery_running
    if discovery_running:
        return jsonify({"error": "Discovery already running"}), 429
    t = threading.Thread(target=discovery_task, daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/discovery_status")
def discovery_status():
    now = time.time() * 1000
    nodes = []
    for ip, info in registry.items():
        nodes.append({
            "ip": ip,
            "id": info["id"],
            "role": info["role"],
            "age_ms": now - info["last_seen_ms"],
        })
    return jsonify({"running": discovery_running, "nodes": nodes})


@app.route("/switch_role", methods=["POST"])
def switch_role():
    data = request.get_json(silent=True) or {}
    ip = data.get("ip")
    role = data.get("role")
    if not ip:
        return jsonify({"error": "Missing IP"}), 400
    if role not in ("0", "1"):
        return jsonify({"error": "Role must be 0 (TAG) or 1 (ANCHOR)"}), 400

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.sendto(f"ROLE,{role}".encode(), (ip, UDP_PORT))
    except Exception as e:
        return jsonify({"error": f"Failed to send ROLE,{role} to {ip}: {e}"}), 500
    sock.close()

    role_name = "TAG" if role == "0" else "ANCHOR"
    return jsonify({"ok": True, "message": f"Sent ROLE,{role} ({role_name}) to {ip}. Device will rejoin."})


@app.route("/save_anchors", methods=["POST"])
def save_anchors_route():
    save_anchors()
    return jsonify({"ok": True, "count": len(anchors)})


@app.route("/load_anchors", methods=["POST"])
def load_anchors_route():
    load_anchors()
    return jsonify({"ok": True, "count": len(anchors)})


@app.route("/set_anchor", methods=["POST"])
def set_anchor():
    data = request.get_json(silent=True) or {}
    try:
        aid = int(data["id"])
        x = float(data["x"])
        y = float(data["y"])
        z = float(data["z"])
    except Exception:
        return jsonify({"error": "Bad anchor data"}), 400
    anchors[aid] = (x, y, z)
    save_anchors()
    log(f"Anchor {aid} set to ({x:.2f}, {y:.2f}, {z:.2f})")
    return jsonify({"ok": True})


@app.route("/cal_point", methods=["POST"])
def cal_point():
    global cal3d
    data = request.get_json(silent=True) or {}
    try:
        tid = int(data["tag_id"])
        x = float(data["x"])
        y = float(data["y"])
        z = float(data["z"])
    except Exception:
        return jsonify({"error": "Bad point data"}), 400

    if cal3d["active"]:
        return jsonify({"error": "Collection already running"}), 429

    cal3d["active"] = True
    cal3d["tag_id"] = tid
    cal3d["points"].append({"x": x, "y": y, "z": z, "samples": defaultdict(list)})
    cal3d["point_idx"] = len(cal3d["points"]) - 1
    cal3d["timer_deadline"] = time.time() * 1000 + CAL3D_COLLECT_MS

    log(f"Calibration point {cal3d['point_idx']} started for tag {tid}")

    def finish():
        time.sleep(CAL3D_COLLECT_MS / 1000.0)
        cal3d["active"] = False
        log(f"Calibration point {cal3d['point_idx']} finished")

    threading.Thread(target=finish, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/cal_status")
def cal_status():
    points = []
    for i, p in enumerate(cal3d["points"]):
        total = sum(len(v) for v in p["samples"].values())
        points.append({
            "index": i,
            "x": p["x"], "y": p["y"], "z": p["z"],
            "samples": total,
        })
    return jsonify({
        "active": cal3d["active"],
        "point_count": len(cal3d["points"]),
        "points": points,
    })


@app.route("/cal_solve", methods=["POST"])
def cal_solve():
    global cal3d
    if cal3d["active"]:
        return jsonify({"error": "Wait for current collection to finish"}), 429
    if len(cal3d["points"]) < 4:
        return jsonify({"error": f"Need >=4 points, have {len(cal3d['points'])}"}), 400

    # Build per-anchor (known point, median range) lists.
    anchor_samples = defaultdict(list)
    for p in cal3d["points"]:
        for aid, dists in p["samples"].items():
            r = median(dists)
            if r is not None and r > 0:
                anchor_samples[aid].append(((p["x"], p["y"], p["z"]), r))

    solved = 0
    for aid, pairs in anchor_samples.items():
        if len(pairs) < 4:
            log(f"Anchor {aid} skipped: only {len(pairs)} valid points")
            continue
        pts = [pt for pt, _ in pairs]
        rad = [r for _, r in pairs]
        pos = solve_anchor_position(pts, rad)
        if pos:
            anchors[aid] = pos
            log(f"Anchor {aid} solved at ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
            solved += 1
        else:
            log(f"Anchor {aid} solve failed")

    if solved > 0:
        save_anchors()

    return jsonify({"ok": True, "message": f"Solved {solved} anchor(s)"})


@app.route("/cal_clear", methods=["POST"])
def cal_clear():
    global cal3d
    cal3d = {
        "active": False,
        "tag_id": None,
        "point_idx": 0,
        "points": [],
        "timer_deadline": 0,
    }
    log("Calibration cleared")
    return jsonify({"ok": True})


@app.route("/auto_cal_start", methods=["POST"])
def auto_cal_start():
    global auto_cal
    data = request.get_json(silent=True) or {}

    # origin_id is optional; if omitted the first discovered anchor is used.
    origin_id = data.get("origin_id")
    if origin_id is not None:
        try:
            origin_id = int(origin_id)
        except Exception:
            return jsonify({"error": "Bad origin_id"}), 400

    with auto_cal_lock:
        if auto_cal["running"]:
            return jsonify({"error": "Auto-calibration already running"}), 429

        # Build list of discovered anchor IDs (role == 1).
        anchor_ids = {info["id"] for info in registry.values() if info.get("role") == 1}

        if origin_id is None:
            if not anchor_ids:
                return jsonify({"error": "No anchors discovered"}), 400
            origin_id = min(anchor_ids)

        if origin_id not in anchor_ids:
            return jsonify({"error": f"Origin ID {origin_id} not found among discovered anchors"}), 400

        anchor_ids.discard(origin_id)
        if not anchor_ids:
            return jsonify({"error": "Need at least 2 anchors for auto-calibration"}), 400

        auto_cal["running"] = True
        auto_cal["origin_id"] = origin_id
        auto_cal["fixed"] = {origin_id: (0.0, 0.0, 0.0)}
        auto_cal["pending"] = sorted(anchor_ids)
        auto_cal["current_id"] = None
        auto_cal["phase"] = "wait_next"
        auto_cal["deadline_ms"] = 0
        auto_cal["samples"] = defaultdict(list)
        auto_cal["packet_count"] = 0
        auto_cal["message"] = f"Starting auto-calibration with origin {origin_id}"
        auto_cal["succeeded"].clear()
        auto_cal["failed"].clear()
        auto_cal["auto_retried"] = False

        # Write calibration start metadata to the session CSV.
        if session_csv:
            session_csv.write_session_info(origin_id)
            session_csv.write_trny(trny)
            session_csv.append_anchors_resolved(datetime.now().isoformat(), {origin_id: (0.0, 0.0, 0.0)})

    log(f"[AUTO] Starting calibration. Origin={origin_id}, pending={auto_cal['pending']}")
    threading.Thread(target=auto_cal_loop, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/auto_cal_stop", methods=["POST"])
def auto_cal_stop():
    with auto_cal_lock:
        if not auto_cal["running"]:
            return jsonify({"ok": True, "message": "Not running"})
        auto_cal["running"] = False
        auto_cal["phase"] = "idle"
        auto_cal["message"] = "Stopped by user"
    log("[AUTO] Stopped by user")
    return jsonify({"ok": True})


@app.route("/auto_cal_retry_failed", methods=["POST"])
def auto_cal_retry_failed():
    global auto_cal
    with auto_cal_lock:
        if auto_cal["running"]:
            return jsonify({"error": "Auto-calibration already running"}), 429

        failed = list(auto_cal["failed"])
        if not failed:
            return jsonify({"ok": True, "message": "No failed anchors to retry"})

        origin_id = auto_cal["origin_id"]
        if origin_id is None:
            return jsonify({"error": "No previous calibration to retry"}), 400

        # Keep the solved anchors, retry only the failed ones.
        auto_cal["running"] = True
        auto_cal["pending"] = sorted(failed)
        auto_cal["failed"].clear()
        auto_cal["current_id"] = None
        auto_cal["phase"] = "wait_next"
        auto_cal["deadline_ms"] = 0
        auto_cal["samples"] = defaultdict(list)
        auto_cal["packet_count"] = 0
        auto_cal["message"] = f"Retrying failed anchors: {failed}"
        auto_cal["auto_retried"] = True

    log(f"[AUTO] Retrying failed anchors: {failed}")
    threading.Thread(target=auto_cal_loop, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/reset_anchors", methods=["POST"])
def reset_anchors():
    global anchors
    anchors.clear()
    save_anchors()
    auto_cal_reset()
    log("Anchors reset")
    return jsonify({"ok": True})


@app.route("/transform_status")
def transform_status():
    with transform_lock:
        return jsonify({
            "active": transform["active"],
            "scale": transform["scale"],
            "theta": transform["theta"],
            "tx": transform["tx"],
            "ty": transform["ty"],
            "tz": transform["tz"],
            "pairs": [
                {"point_id": p["point_id"], "uwb": list(p["uwb"]), "global": list(p["global"])}
                for p in transform["pairs"]
            ],
        })


@app.route("/compute_transform", methods=["POST"])
def compute_transform():
    with transform_lock:
        pairs = list(transform["pairs"])
    if len(pairs) < 3:
        return jsonify({"error": f"Need at least 3 trny scans, have {len(pairs)}"}), 400

    uwb_points = [p["uwb"] for p in pairs]
    global_points = [p["global"] for p in pairs]
    result = compute_similarity_transform(uwb_points, global_points)
    if result is None:
        return jsonify({"error": "Could not compute transform (degenerate geometry)"}), 400

    with transform_lock:
        transform["active"] = True
        transform["scale"] = result["scale"]
        transform["theta"] = result["theta"]
        transform["cos"] = result["cos"]
        transform["sin"] = result["sin"]
        transform["tx"] = result["tx"]
        transform["ty"] = result["ty"]
        transform["tz"] = result["tz"]

    log(f"[TRANSFORM] scale={result['scale']:.4f}, theta={math.degrees(result['theta']):.2f}°, "
        f"offset=({result['tx']:.2f}, {result['ty']:.2f}, {result['tz']:.2f})")
    if session_csv:
        session_csv.append_anchors_global(datetime.now().isoformat(), {
            aid: apply_transform(p) for aid, p in anchors.items()
        })
    return jsonify({"ok": True, "transform": result})


@app.route("/clear_transform", methods=["POST"])
def clear_transform_route():
    reset_transform()
    log("Transform cleared")
    return jsonify({"ok": True})


@app.route("/auto_cal_status")
def auto_cal_status():
    with auto_cal_lock:
        return jsonify({
            "running": auto_cal["running"],
            "origin_id": auto_cal["origin_id"],
            "phase": auto_cal["phase"],
            "current_id": auto_cal["current_id"],
            "pending": list(auto_cal["pending"]),
            "fixed": {aid: list(p) for aid, p in auto_cal["fixed"].items()},
            "packet_count": auto_cal["packet_count"],
            "packets_needed": auto_cal["packets_needed"],
            "message": auto_cal["message"],
            "succeeded": sorted(auto_cal["succeeded"]),
            "failed": sorted(auto_cal["failed"]),
            "auto_retried": auto_cal["auto_retried"],
        })


@app.route("/state")
def state():
    now = time.time() * 1000
    nodes = []
    for ip, info in registry.items():
        nodes.append({
            "ip": ip,
            "id": info["id"],
            "role": info["role"],
            "age_ms": now - info["last_seen_ms"],
        })
    # Only report tags that are currently in TAG role (role == 0) in the registry.
    # This avoids showing anchors that were temporarily switched to TAG during
    # auto-calibration and then switched back.
    active_tag_ids = {info["id"] for info in registry.values() if info.get("role") == 0}
    tag_state = {}
    for tid, t in tags.items():
        if tid in active_tag_ids:
            tag_state[tid] = {
                "pos": list(t["pos"]) if t["pos"] else None,
                "global_pos": list(apply_transform(t["pos"])) if t["pos"] else None,
                "ranges": {aid: float(r) for aid, r in t["ranges"].items() if r is not None and r > 0},
                "age_ms": now - t["last_seen_ms"],
            }
    with transform_lock:
        transform_active = transform["active"]
    return jsonify({
        "nodes": nodes,
        "anchors": {aid: list(p) for aid, p in anchors.items()},
        "anchors_global": {aid: list(apply_transform(p)) for aid, p in anchors.items()},
        "tags": tag_state,
        "transform_active": transform_active,
        "log": log_lines,
    })


def main():
    global session_csv
    load_anchors()
    load_trny()
    session_csv = SessionCsvWriter()
    session_csv.write_trny(trny)
    threading.Thread(target=udp_listener, daemon=True).start()
    threading.Thread(target=qr_listener, daemon=True).start()
    ip = get_pc_ip()
    url = f"http://{ip}:5000"
    print("=" * 60)
    print("  PC ANL (prototype)")
    print("=" * 60)
    print(f"  Open browser at: {url}")
    print("=" * 60)
    # Open the default browser once the server is likely ready.
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
