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
        <h2>4. Live tag positions</h2>
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
