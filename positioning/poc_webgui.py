"""
poc_webgui.py
=============
Web GUI for UWB SNAP measurements with node discovery.

Connect your PC to the RTLS-NET-XXXX WiFi, run:
    pip install flask
    python poc_webgui.py

Then open the displayed URL in any browser.

Features:
  - Discover all nodes on the network (PING / PONG)
  - Trigger SNAP from any tag on the network
  - Switch any node between TAG and ANCHOR roles
"""

import os
import sys
import socket
import csv
import time
import threading
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request

UDP_PORT = 50000
LISTEN_SECONDS = 6

CSV_COLUMNS = [
    "timestamp_ms",
    "type",
    "tag_id",
    "source",
    "raw_line",
    "comment",
]

app = Flask(__name__)

# Global state
measurement_state = {
    "running": False,
    "progress": 0,
    "log": [],
    "csv_path": None,
    "snap_count": 0,
    "packets_received": 0,
    "mode": "single",   # "single" or "auto"
    "stop_requested": False,
    "current_comment": "",
}

discovery_state = {
    "running": False,
    "nodes": [],
}


def get_rtls_ip() -> str:
    """Find the IP address on the 192.168.4.x network."""
    import subprocess
    try:
        result = subprocess.run(["ipconfig"], capture_output=True, text=True)
        lines = result.stdout.split("\n")
        for line in lines:
            if "192.168.4." in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    ip = parts[1].strip()
                    if ip.startswith("192.168.4."):
                        return ip
    except Exception:
        pass
    return "0.0.0.0"


def send_snap_trigger(sock: socket.socket, target_ip: str | None = None) -> None:
    """Send SNAP trigger via broadcast and subnet scan."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except Exception:
        pass

    if target_ip:
        try:
            sock.sendto(b"SNAP", (target_ip, UDP_PORT))
            measurement_state["log"].append(f"  -> Sent SNAP to {target_ip} (direct)")
        except Exception as e:
            measurement_state["log"].append(f"  -> Direct send to {target_ip} failed: {e}")
    else:
        try:
            sock.sendto(b"SNAP", ("192.168.4.255", UDP_PORT))
            measurement_state["log"].append("  -> Sent SNAP to 192.168.4.255 (broadcast)")
        except Exception as e:
            measurement_state["log"].append(f"  -> Broadcast failed: {e}")
        for i in range(2, 11):
            ip = f"192.168.4.{i}"
            try:
                sock.sendto(b"SNAP", (ip, UDP_PORT))
            except Exception:
                pass
        measurement_state["log"].append("  -> Sent SNAP to 192.168.4.2-10 (subnet scan)")


def run_discovery() -> None:
    """Background thread: send PING, collect PONGs."""
    global discovery_state
    discovery_state["running"] = True
    discovery_state["nodes"] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", UDP_PORT))
    except OSError:
        discovery_state["running"] = False
        return
    sock.settimeout(0.5)

    # Send PING to broadcast and subnet
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except Exception:
        pass
    try:
        sock.sendto(b"PING", ("192.168.4.255", UDP_PORT))
    except Exception:
        pass
    for i in range(2, 11):
        try:
            sock.sendto(b"PING", (f"192.168.4.{i}", UDP_PORT))
        except Exception:
            pass

    # Collect PONGs for 2 seconds
    seen = set()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        text = data.decode("utf-8", errors="ignore").strip()
        if not text.startswith("PONG,"):
            continue
        parts = text.split(",")
        if len(parts) < 4:
            continue
        node_id = parts[1]
        role = parts[2]
        net_id = parts[3]
        key = (addr[0], node_id)
        if key in seen:
            continue
        seen.add(key)
        discovery_state["nodes"].append({
            "ip": addr[0],
            "id": node_id,
            "role": "TAG" if role == "0" else "ANCHOR",
            "role_num": role,
            "net_id": net_id,
        })

    sock.close()
    discovery_state["running"] = False


def run_measurement(comment: str, target_ip: str | None = None) -> None:
    """Background thread: trigger SNAP, listen, write CSV."""
    global measurement_state

    measurement_state["running"] = True
    measurement_state["progress"] = 0
    measurement_state["log"] = []
    measurement_state["snap_count"] = 0
    measurement_state["packets_received"] = 0
    measurement_state["csv_path"] = None
    measurement_state["mode"] = "single"
    measurement_state["stop_requested"] = False

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(os.path.dirname(__file__), f"uwb_log_{now}.csv")
    measurement_state["csv_path"] = csv_path

    bind_ip = get_rtls_ip()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((bind_ip, UDP_PORT))
        measurement_state["log"].append(f"Bound to {bind_ip}:{UDP_PORT}")
    except OSError as e:
        measurement_state["log"].append(f"Failed to bind to {bind_ip}:{UDP_PORT} — {e}")
        measurement_state["log"].append("Trying 0.0.0.0 instead...")
        try:
            sock.bind(("0.0.0.0", UDP_PORT))
            measurement_state["log"].append(f"Bound to 0.0.0.0:{UDP_PORT}")
        except OSError as e2:
            measurement_state["log"].append(f"ERROR: Failed to bind port {UDP_PORT}: {e2}")
            measurement_state["running"] = False
            return
    sock.settimeout(1.0)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        send_snap_trigger(sock, target_ip)
        measurement_state["log"].append("SNAP trigger sent. Listening...")

        start_time = time.time()
        seen_packets = {}
        dedup_window = 2.0

        while time.time() - start_time < LISTEN_SECONDS:
            elapsed = time.time() - start_time
            measurement_state["progress"] = int((elapsed / LISTEN_SECONDS) * 100)

            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue

            text = data.decode("utf-8", errors="ignore").strip()
            measurement_state["packets_received"] += 1

            # Debug: log every raw packet
            measurement_state["log"].append(f"[RAW from {addr[0]}] {text[:120]}")

            if not text.startswith("SNAP,"):
                continue

            parts = text.split(",")
            if len(parts) < 5:
                measurement_state["log"].append("  -> malformed SNAP packet")
                continue

            tag_id_str = parts[1]
            source = parts[2]
            raw_line = ",".join(parts[3:-1])
            ts = parts[-1]

            dedup_key = (tag_id_str, source, raw_line, ts)
            now_mono = time.time()
            seen_packets = {
                k: v for k, v in seen_packets.items()
                if now_mono - v < dedup_window
            }
            if dedup_key in seen_packets:
                measurement_state["log"].append("  -> DUPLICATE suppressed")
                continue
            seen_packets[dedup_key] = now_mono

            writer.writerow({
                "timestamp_ms": ts,
                "type": "SNAP",
                "tag_id": tag_id_str,
                "source": source,
                "raw_line": raw_line,
                "comment": comment,
            })
            f.flush()

            measurement_state["snap_count"] += 1
            measurement_state["log"].append(f"  -> [{tag_id_str}] src={source} logged")

    sock.close()
    measurement_state["progress"] = 100
    measurement_state["log"].append(
        f"Done. {measurement_state['snap_count']} SNAP rows saved."
    )
    measurement_state["running"] = False


def run_auto_log() -> None:
    """Background thread: continuously listen for SNAP packets and append to CSV."""
    global measurement_state

    measurement_state["running"] = True
    measurement_state["progress"] = 0
    measurement_state["log"] = []
    measurement_state["snap_count"] = 0
    measurement_state["packets_received"] = 0
    measurement_state["csv_path"] = None
    measurement_state["mode"] = "auto"
    measurement_state["stop_requested"] = False

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(os.path.dirname(__file__), f"uwb_log_{now}.csv")
    measurement_state["csv_path"] = csv_path

    bind_ip = get_rtls_ip()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((bind_ip, UDP_PORT))
        measurement_state["log"].append(f"[AUTO] Bound to {bind_ip}:{UDP_PORT}")
    except OSError as e:
        measurement_state["log"].append(f"[AUTO] Failed to bind to {bind_ip}:{UDP_PORT} — {e}")
        measurement_state["log"].append("[AUTO] Trying 0.0.0.0 instead...")
        try:
            sock.bind(("0.0.0.0", UDP_PORT))
            measurement_state["log"].append(f"[AUTO] Bound to 0.0.0.0:{UDP_PORT}")
        except OSError as e2:
            measurement_state["log"].append(f"[AUTO] ERROR: Failed to bind port {UDP_PORT}: {e2}")
            measurement_state["running"] = False
            return
    sock.settimeout(1.0)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        measurement_state["log"].append("[AUTO] Logging started. Press button on tag anytime.")

        seen_packets = {}
        dedup_window = 2.0
        start_time = time.time()

        while not measurement_state["stop_requested"]:
            elapsed = time.time() - start_time
            # Fake progress that cycles every 60s so the bar isn't static
            measurement_state["progress"] = int(((elapsed % 60) / 60) * 100)

            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue

            text = data.decode("utf-8", errors="ignore").strip()
            measurement_state["packets_received"] += 1

            if not text.startswith("SNAP,"):
                continue

            parts = text.split(",")
            if len(parts) < 5:
                continue

            tag_id_str = parts[1]
            source = parts[2]
            raw_line = ",".join(parts[3:-1])
            ts = parts[-1]

            dedup_key = (tag_id_str, source, raw_line, ts)
            now_mono = time.time()
            seen_packets = {
                k: v for k, v in seen_packets.items()
                if now_mono - v < dedup_window
            }
            if dedup_key in seen_packets:
                continue
            seen_packets[dedup_key] = now_mono

            comment = measurement_state.get("current_comment", "")
            writer.writerow({
                "timestamp_ms": ts,
                "type": "SNAP",
                "tag_id": tag_id_str,
                "source": source,
                "raw_line": raw_line,
                "comment": comment,
            })
            f.flush()

            measurement_state["snap_count"] += 1
            measurement_state["log"].append(f"[AUTO] [{tag_id_str}] src={source} logged (total: {measurement_state['snap_count']})")

    sock.close()
    measurement_state["progress"] = 100
    measurement_state["log"].append(
        f"[AUTO] Stopped. {measurement_state['snap_count']} SNAP rows saved."
    )
    measurement_state["running"] = False


HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>UWB SNAP Collector</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }
        h1 { color: #333; }
        label { display: block; margin-top: 15px; font-weight: bold; }
        input[type="text"] { width: 100%; padding: 8px; font-size: 14px; box-sizing: border-box; }
        button { margin-top: 10px; padding: 10px 20px; font-size: 16px; cursor: pointer; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        #progressBar { width: 100%; height: 24px; background: #eee; margin-top: 15px; border-radius: 4px; overflow: hidden; }
        #progressFill { height: 100%; width: 0%%; background: #4caf50; transition: width 0.3s; }
        #logBox { margin-top: 20px; border: 1px solid #ccc; padding: 10px; height: 250px; overflow-y: auto; background: #f9f9f9; font-family: monospace; font-size: 12px; }
        .log-line { margin: 2px 0; }
        #downloadLink { margin-top: 15px; display: inline-block; }
        .node-table { width: 100%%; border-collapse: collapse; margin-top: 10px; }
        .node-table th, .node-table td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        .node-table th { background: #eee; }
        .role-btn { padding: 6px 12px; font-size: 14px; }
        .section { margin-top: 25px; padding: 15px; border: 1px solid #ddd; border-radius: 6px; }
    </style>
</head>
<body>
    <h1>UWB SNAP Collector</h1>
    <p>Connect to <strong>RTLS-NET-XXXX</strong> WiFi, discover nodes, then trigger a SNAP.</p>

    <div class="section">
        <h2>1. Discover Nodes</h2>
        <button id="discoverBtn" onclick="discoverNodes()">Discover Nodes</button>
        <div id="nodeList"></div>
    </div>

    <div class="section">
        <h2>2. SNAP Trigger</h2>
        <label for="comment">Comment (applied to every row):</label>
        <input type="text" id="comment" placeholder="e.g. Position A, test run 3">
        <br>
        <button id="startBtn" onclick="startSnap()">START SNAP (all tags)</button>
        <button id="autoBtn" onclick="startAuto()">START AUTO LOG</button>
        <button id="stopBtn" onclick="stopAuto()" style="display:none;">STOP AUTO LOG</button>
    </div>

    <div class="section">
        <h2>3. Progress</h2>
        <div id="progressBar"><div id="progressFill"></div></div>
        <div id="logBox"></div>
        <a id="downloadLink" style="display:none;" href="#">Download CSV</a>
    </div>

    <script>
        let pollInterval = null;

        function addLog(text) {
            const box = document.getElementById('logBox');
            const div = document.createElement('div');
            div.className = 'log-line';
            div.textContent = text;
            box.appendChild(div);
            box.scrollTop = box.scrollHeight;
        }

        function discoverNodes() {
            const btn = document.getElementById('discoverBtn');
            btn.disabled = true;
            document.getElementById('nodeList').innerHTML = '<p>Scanning...</p>';

            fetch('/discover', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        document.getElementById('nodeList').innerHTML = '<p style="color:red">' + data.error + '</p>';
                        btn.disabled = false;
                        return;
                    }
                    pollDiscovery();
                })
                .catch(err => {
                    document.getElementById('nodeList').innerHTML = '<p style="color:red">' + err + '</p>';
                    btn.disabled = false;
                });
        }

        function pollDiscovery() {
            fetch('/discovery_status')
                .then(r => r.json())
                .then(data => {
                    if (data.running) {
                        setTimeout(pollDiscovery, 500);
                        return;
                    }
                    renderNodes(data.nodes);
                    document.getElementById('discoverBtn').disabled = false;
                });
        }

        function renderNodes(nodes) {
            const div = document.getElementById('nodeList');
            if (nodes.length === 0) {
                div.innerHTML = '<p>No nodes found. Make sure devices are powered on.</p>';
                return;
            }
            let html = '<table class="node-table"><tr><th>ID</th><th>Role</th><th>IP</th><th>Net ID</th><th>Action</th></tr>';
            for (const n of nodes) {
                const targetRole = n.role === 'ANCHOR' ? 'TAG' : 'ANCHOR';
                const targetRoleNum = n.role === 'ANCHOR' ? '0' : '1';
                const btnText = `Switch to ${targetRole}`;
                const btn = `<button class="role-btn" onclick="switchRole('${n.ip}', '${targetRoleNum}', '${n.id}', '${targetRole}')">${btnText}</button>`;
                html += `<tr><td>${n.id}</td><td>${n.role}</td><td>${n.ip}</td><td>${n.net_id}</td><td>${btn}</td></tr>`;
            }
            html += '</table>';
            div.innerHTML = html;
        }

        function switchRole(ip, roleNum, nodeId, targetRole) {
            if (!confirm(`Switch node ${nodeId} to ${targetRole}?`)) return;
            fetch('/switch_role', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ip: ip, role: roleNum})
            }).then(r => r.json()).then(data => {
                if (data.error) {
                    alert('ERROR: ' + data.error);
                    return;
                }
                alert(data.message);
                // Refresh discovery to show updated roles
                discoverNodes();
            }).catch(err => {
                alert('ERROR: ' + err);
            });
        }

        function startSnap() {
            const comment = document.getElementById('comment').value;
            runMeasurement({comment: comment, mode: 'single'});
        }

        function startAuto() {
            const comment = document.getElementById('comment').value;
            runMeasurement({comment: comment, mode: 'auto'});
        }

        function stopAuto() {
            fetch('/stop', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        addLog('ERROR: ' + data.error);
                        return;
                    }
                    addLog('Stop requested...');
                });
        }

        function runMeasurement(payload) {
            const btn = document.getElementById('startBtn');
            const autoBtn = document.getElementById('autoBtn');
            const stopBtn = document.getElementById('stopBtn');
            btn.disabled = true;
            autoBtn.style.display = 'none';
            document.getElementById('downloadLink').style.display = 'none';
            document.getElementById('logBox').innerHTML = '';
            addLog('Starting SNAP...');

            fetch('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            }).then(r => r.json()).then(data => {
                if (data.error) {
                    addLog('ERROR: ' + data.error);
                    btn.disabled = false;
                    autoBtn.style.display = 'inline-block';
                    stopBtn.style.display = 'none';
                    return;
                }
                if (payload.mode === 'auto') {
                    stopBtn.style.display = 'inline-block';
                }
                pollInterval = setInterval(pollStatus, 500);
            }).catch(err => {
                addLog('ERROR: ' + err);
                btn.disabled = false;
                autoBtn.style.display = 'inline-block';
                stopBtn.style.display = 'none';
            });
        }

        function pollStatus() {
            fetch('/status').then(r => r.json()).then(data => {
                document.getElementById('progressFill').style.width = data.progress + '%';
                const box = document.getElementById('logBox');
                const currentCount = box.children.length;
                for (let i = currentCount; i < data.log.length; i++) {
                    addLog(data.log[i]);
                }
                if (!data.running) {
                    clearInterval(pollInterval);
                    document.getElementById('startBtn').disabled = false;
                    document.getElementById('autoBtn').style.display = 'inline-block';
                    document.getElementById('stopBtn').style.display = 'none';
                    if (data.csv_path) {
                        const link = document.getElementById('downloadLink');
                        link.href = '/download?file=' + encodeURIComponent(data.csv_path);
                        link.textContent = 'Download ' + data.csv_path.split('/').pop();
                        link.style.display = 'inline-block';
                    }
                }
            });
        }
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/discover", methods=["POST"])
def discover():
    if discovery_state["running"]:
        return jsonify({"error": "Discovery already running"}), 429
    t = threading.Thread(target=run_discovery, daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/discovery_status")
def discovery_status():
    return jsonify({
        "running": discovery_state["running"],
        "nodes": discovery_state["nodes"],
    })


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


@app.route("/start", methods=["POST"])
def start():
    if measurement_state["running"]:
        return jsonify({"error": "Measurement already running"}), 429

    data = request.get_json(silent=True) or {}
    comment = data.get("comment", "")
    mode = data.get("mode", "single")

    measurement_state["current_comment"] = comment

    if mode == "auto":
        t = threading.Thread(target=run_auto_log, daemon=True)
    else:
        t = threading.Thread(
            target=run_measurement,
            args=(comment, None),
            daemon=True,
        )
    t.start()
    return jsonify({"ok": True})


@app.route("/stop", methods=["POST"])
def stop():
    if not measurement_state["running"]:
        return jsonify({"error": "No measurement running"}), 400
    measurement_state["stop_requested"] = True
    return jsonify({"ok": True, "message": "Stop requested."})


@app.route("/status")
def status():
    return jsonify({
        "running": measurement_state["running"],
        "progress": measurement_state["progress"],
        "log": measurement_state["log"],
        "snap_count": measurement_state["snap_count"],
        "packets_received": measurement_state["packets_received"],
        "csv_path": measurement_state["csv_path"],
        "mode": measurement_state.get("mode", "single"),
    })


@app.route("/download")
def download():
    from flask import send_file
    filepath = request.args.get("file", "")
    base = os.path.abspath(os.path.dirname(__file__))
    target = os.path.abspath(filepath)
    if not target.startswith(base):
        return "Invalid file", 403
    if not os.path.exists(target):
        return "File not found", 404
    return send_file(target, as_attachment=True)


def main():
    ip = get_rtls_ip()
    print("=" * 50)
    print("  UWB SNAP Web GUI")
    print("=" * 50)
    print(f"  Open your browser at: http://{ip}:5000")
    print("=" * 50)
    print("  Press Ctrl+C to stop the server")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    main()
