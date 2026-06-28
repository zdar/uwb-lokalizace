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
import socket
import time
import math
import threading
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
HEARTBEAT_TIMEOUT_MS = 15000
CAL3D_COLLECT_MS = 15000

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
    "deadline_ms": 0,
    "samples": defaultdict(list),  # fixed_anchor_id -> [distances]
    "message": "",
}
auto_cal_lock = threading.Lock()


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

    # 3+ fixed anchors -> 2D first, then +Z from distance to reference.
    # Use the first valid fixed anchor as the reference for Z.
    (x0, y0, z0), r0 = valid[0]

    # If we have 4+ fixed anchors, try full 3D least-squares first.
    if len(valid) >= 4:
        anchors_dict = {i: p for i, (p, _) in enumerate(valid)}
        ranges_dict = {i: r for i, (_, r) in enumerate(valid)}
        pos3d = trilaterate_3d(ranges_dict, anchors_dict)
        if pos3d:
            return pos3d

    # 2D fallback using the first 3 fixed anchors.
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

    # Add to automatic calibration samples if collecting.
    with auto_cal_lock:
        if auto_cal["running"] and auto_cal["phase"] == "collecting" and auto_cal["current_id"] == tid:
            for aid, dist in ranges.items():
                if 0 <= aid <= 9:
                    auto_cal["samples"].setdefault(aid, []).append(dist)

    # Solve position if enough anchors are known.
    pos = solve_tag_position(tags[tid]["ranges"])
    if pos:
        tags[tid]["pos"] = pos


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
        auto_cal["message"] = ""


def auto_cal_loop():
    """Background thread implementing sequential automatic anchor calibration."""
    while True:
        with auto_cal_lock:
            if not auto_cal["running"]:
                return
            phase = auto_cal["phase"]
            deadline = auto_cal["deadline_ms"]
            current_id = auto_cal["current_id"]

        now_ms = time.time() * 1000

        if phase == "wait_tag" or phase == "wait_anchor":
            if now_ms < deadline:
                time.sleep(0.5)
                continue

            if phase == "wait_tag":
                with auto_cal_lock:
                    auto_cal["phase"] = "collecting"
                    auto_cal["samples"] = defaultdict(list)
                    auto_cal["deadline_ms"] = now_ms + AUTO_CAL_COLLECT_S * 1000
                    auto_cal["message"] = f"Collecting ranges from tag {current_id}"
                log(f"[AUTO] Window open, collecting RPT from tag {current_id}")
                continue

            if phase == "wait_anchor":
                # Anchor should be back online; pick the next one.
                with auto_cal_lock:
                    if auto_cal["pending"]:
                        auto_cal["current_id"] = None
                        auto_cal["phase"] = "wait_next"
                    else:
                        auto_cal["current_id"] = None
                        auto_cal["phase"] = "done"
                        auto_cal["message"] = "Auto-calibration complete"
                        auto_cal["running"] = False
                        log("[AUTO] Calibration complete")
                continue

        if phase == "collecting":
            if now_ms < deadline:
                time.sleep(0.5)
                continue

            with auto_cal_lock:
                samples = auto_cal["samples"]
                fixed = dict(auto_cal["fixed"])
                current_id = auto_cal["current_id"]

            # Compute median ranges to already-fixed anchors.
            median_ranges = {}
            for aid, dists in samples.items():
                if aid in fixed and dists:
                    m = median(dists)
                    if m is not None and m > 0:
                        median_ranges[aid] = m

            log(f"[AUTO] Median ranges from tag {current_id}: {median_ranges}")
            pos = solve_sequential_anchor(median_ranges, fixed)

            if pos:
                anchors[current_id] = pos
                with auto_cal_lock:
                    auto_cal["fixed"][current_id] = pos
                log(f"[AUTO] Anchor {current_id} fixed at ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
            else:
                log(f"[AUTO] Failed to solve anchor {current_id}; will still switch back")

            ip = get_node_ip_by_id(current_id)
            if ip:
                send_role_udp(ip, 1)
                log(f"[AUTO] Sent ROLE,1 to anchor {current_id}")
            else:
                log(f"[AUTO] No IP for {current_id} to send ROLE,1")

            with auto_cal_lock:
                auto_cal["phase"] = "wait_anchor"
                auto_cal["deadline_ms"] = time.time() * 1000 + AUTO_CAL_ROLE_SWITCH_WAIT_S * 1000
                auto_cal["message"] = f"Waiting for anchor {current_id} to reconfigure"
            continue

        if phase == "wait_next":
            with auto_cal_lock:
                if auto_cal["pending"]:
                    next_id = auto_cal["pending"].pop(0)
                    auto_cal["current_id"] = next_id
                    auto_cal["phase"] = "wait_tag"
                    auto_cal["deadline_ms"] = time.time() * 1000 + AUTO_CAL_ROLE_SWITCH_WAIT_S * 1000
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
    </style>
</head>
<body>
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
        </div>
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
        <h2>Log</h2>
        <div id="logBox"></div>
    </div>

    <script>
        let pollInterval = null;

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
            let html = '<table><tr><th>ID</th><th>IP</th><th>Role</th><th>Age (s)</th><th>Action</th></tr>';
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
                body: JSON.stringify({ip: ip, role: roleNum})
            }).then(r => r.json()).then(data => {
                alert(data.message || data.error);
                discover();
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
                    }
                    html += '<p>Fixed anchors:</p><ul>';
                    for (const [id, p] of Object.entries(data.fixed)) {
                        html += `<li>${id}: (${p[0].toFixed(2)}, ${p[1].toFixed(2)}, ${p[2].toFixed(2)})</li>`;
                    }
                    html += '</ul>';
                    if (data.pending && data.pending.length > 0) {
                        html += `<p>Pending: ${data.pending.join(', ')}</p>`;
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

        function refreshState() {
            fetch('/state')
                .then(r => r.json())
                .then(data => {
                    renderNodes(data.nodes);
                    const aDiv = document.getElementById('anchorList');
                    let aHtml = '<table><tr><th>ID</th><th>X</th><th>Y</th><th>Z</th></tr>';
                    for (const [id, p] of Object.entries(data.anchors)) {
                        aHtml += `<tr><td>${id}</td><td>${p[0].toFixed(2)}</td><td>${p[1].toFixed(2)}</td><td>${p[2].toFixed(2)}</td></tr>`;
                    }
                    aHtml += '</table>';
                    aDiv.innerHTML = aHtml;

                    const tDiv = document.getElementById('tagPositions');
                    let tHtml = '<table><tr><th>Tag ID</th><th>X</th><th>Y</th><th>Z</th><th>Age (s)</th></tr>';
                    for (const [id, t] of Object.entries(data.tags)) {
                        const pos = t.pos ? `(${t.pos[0].toFixed(2)}, ${t.pos[1].toFixed(2)}, ${t.pos[2].toFixed(2)})` : '---';
                        tHtml += `<tr><td>${id}</td><td>${pos}</td><td>${(t.age_ms / 1000).toFixed(1)}</td></tr>`;
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
    return jsonify({"ok": True, "message": f"Sent ROLE,{role} ({role_name}) to {ip}. Device will reboot and rejoin."})


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
    try:
        origin_id = int(data.get("origin_id", 0))
    except Exception:
        return jsonify({"error": "Bad origin_id"}), 400

    with auto_cal_lock:
        if auto_cal["running"]:
            return jsonify({"error": "Auto-calibration already running"}), 429

        # Build list of discovered anchor IDs (role == 1) excluding origin.
        anchor_ids = set()
        for ip, info in registry.items():
            if info.get("role") == 1:
                anchor_ids.add(info["id"])
            elif info.get("role") == 0:
                # Treat currently-TAG nodes as anchors if the user says so? No,
                # only role==1 nodes are anchors; role==0 are tags.
                pass

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
        auto_cal["message"] = f"Starting auto-calibration with origin {origin_id}"

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
            "message": auto_cal["message"],
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
    tag_state = {}
    for tid, t in tags.items():
        tag_state[tid] = {
            "pos": list(t["pos"]) if t["pos"] else None,
            "age_ms": now - t["last_seen_ms"],
        }
    return jsonify({
        "nodes": nodes,
        "anchors": {aid: list(p) for aid, p in anchors.items()},
        "tags": tag_state,
        "log": log_lines,
    })


def main():
    threading.Thread(target=udp_listener, daemon=True).start()
    ip = get_pc_ip()
    print("=" * 60)
    print("  PC ANL (prototype)")
    print("=" * 60)
    print(f"  Open browser at: http://{ip}:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
