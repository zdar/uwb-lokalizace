"""
UWB Wireless Positioning with Auto-Calibration
================================================
Works with the current MERGED firmware (src/main.cpp) WITHOUT any changes.

Auto-calibration discovers anchor positions automatically:
  1. Discover all nodes on the network (PING / PONG)
  2. Identify the ANL (IP 192.168.4.1) and fix it at (0, 0)
  3. For each remaining anchor, temporarily switch it to TAG via UDP
  4. Trigger SNAP, collect ranges to the ANL and other anchors
  5. Switch it back to ANCHOR
  6. Solve all anchor positions from the pairwise distances
  7. Start the live Pygame visualizer with the computed coordinates

Usage:
    python positioning/position_wireless_autocal.py
    python positioning/position_wireless_autocal.py --skip-autocal

Conference demo flow:
  1. Power on all anchors (one is the ANL AP) and the tag
  2. Connect your PC to the RTLS-NET-XXXX WiFi
  3. Run this script — auto-cal runs automatically (~2 min for 4 anchors)
  4. Once the map appears, press the BOOT button on the tag to start SNAP
  5. Walk the tag around and watch the red dot move in real time

Dependencies: pip install pygame
"""

import os
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
import socket
import time
import math
import sys
import argparse

# ==================== CONFIGURATION ====================

# Fallback anchor coordinates (used when --skip-autocal is given).
# IDs must match the UWB_INDEX set on each anchor node.
ANCHORS = {
    0: (0.00,    0.00),
    1: (94.00,   0.00),
    2: (24.87,   96.86),
    3: (-73.22,  83.43),
}

UDP_PORT = 50000
UDP_BIND = "0.0.0.0"

SCREEN_X, SCREEN_Y = 800, 800
REFRESH_INTERVAL = 0.3

RED   = (255, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREY  = (180, 180, 180)
GREEN = (0, 200, 0)
BLUE  = (0, 0, 255)

MAX_ANCHORS = 8
MAX_TAGS = 8

# Auto-cal timing
# NOTE: after the firmware fix (AT+RESTORE + 8 s restore delay + 4 s reboot delay),
# role switching needs more time than before.
ROLE_SWITCH_DELAY = 45      # seconds to wait after ROLE command for restore + reboot + rejoin
SNAP_LISTEN_SECONDS = 8     # seconds to listen for SNAP packets
PING_TIMEOUT = 2.5          # seconds to collect PONGs
DISCOVERY_RETRIES = 3

# ==================== MATH ====================

def circle_intersections(x0, y0, r0, x1, y1, r1):
    """Return two intersection points of two circles, or None."""
    d = math.hypot(x1 - x0, y1 - y0)
    if d == 0 or d > r0 + r1 or d < abs(r0 - r1):
        return None
    a = (r0 * r0 - r1 * r1 + d * d) / (2.0 * d)
    h = math.sqrt(max(r0 * r0 - a * a, 0.0))
    xm = x0 + a * (x1 - x0) / d
    ym = y0 + a * (y1 - y0) / d
    rx = -(y1 - y0) * (h / d)
    ry =  (x1 - x0) * (h / d)
    return ((xm + rx, ym + ry), (xm - rx, ym - ry))


def trilaterate(ranges, anchors_coords):
    """
    ranges         – dict {anchor_id: distance}
    anchors_coords – dict {anchor_id: (x, y)}
    Returns (x, y) or None.
    """
    valid = [(aid, r) for aid, r in ranges.items()
             if r > 0.0 and aid in anchors_coords]
    if len(valid) < 3:
        return None

    positions = []
    ids = [aid for aid, _ in valid]
    n = len(ids)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a0, a1, a2 = ids[i], ids[j], ids[k]
                r0, r1, r2 = ranges[a0], ranges[a1], ranges[a2]
                x0, y0 = anchors_coords[a0]
                x1, y1 = anchors_coords[a1]
                x2, y2 = anchors_coords[a2]

                pts = circle_intersections(x0, y0, r0, x1, y1, r1)
                if pts is None:
                    continue
                (xa, ya), (xb, yb) = pts
                da = math.hypot(xa - x2, ya - y2)
                db = math.hypot(xb - x2, yb - y2)
                positions.append((xa, ya) if abs(da - r2) < abs(db - r2) else (xb, yb))

    if not positions:
        return None

    avg_x = sum(p[0] for p in positions) / len(positions)
    avg_y = sum(p[1] for p in positions) / len(positions)
    return (avg_x, avg_y)


def solve_anchor_positions(distances, anchor_ids):
    """
    Solve anchor positions from pairwise distances.
    distances: dict {(i, j): measured_distance} for i < j
    anchor_ids: sorted list of anchor IDs
    Returns dict {anchor_id: (x, y)}.
    """
    n = len(anchor_ids)
    coords = {}

    # Place first anchor at origin
    coords[anchor_ids[0]] = (0.0, 0.0)
    if n < 2:
        return coords

    # Place second anchor on positive x-axis
    d01 = distances.get((min(anchor_ids[0], anchor_ids[1]),
                         max(anchor_ids[0], anchor_ids[1])), 0)
    if d01 <= 0:
        d01 = 100.0  # fallback
    coords[anchor_ids[1]] = (d01, 0.0)
    if n < 3:
        return coords

    # Place third anchor using intersection of circles from 0 and 1
    d02 = distances.get((min(anchor_ids[0], anchor_ids[2]),
                         max(anchor_ids[0], anchor_ids[2])), 0)
    d12 = distances.get((min(anchor_ids[1], anchor_ids[2]),
                         max(anchor_ids[1], anchor_ids[2])), 0)
    pts = circle_intersections(0.0, 0.0, d02, d01, 0.0, d12)
    if pts:
        (xa, ya), (xb, yb) = pts
        # Pick positive Y as convention
        coords[anchor_ids[2]] = (xa, ya) if ya >= 0 else (xb, yb) if yb >= 0 else (xa, ya)
    else:
        # Degenerate: place at 60° as fallback
        coords[anchor_ids[2]] = (d02 * 0.5, d02 * 0.866)

    # Place remaining anchors using trilateration from any 3 already placed
    for idx in range(3, n):
        aid = anchor_ids[idx]
        placed = [a for a in anchor_ids[:idx] if a in coords]
        ranges = {}
        for p in placed:
            d = distances.get((min(aid, p), max(aid, p)), 0)
            if d > 0:
                ranges[p] = d

        if len(ranges) >= 3:
            pos = trilaterate(ranges, coords)
            if pos:
                coords[aid] = pos
                continue

        # Fallback: use first 2 placed anchors with circle intersection
        if len(ranges) >= 2:
            keys = list(ranges.keys())
            p0, p1 = keys[0], keys[1]
            pts = circle_intersections(coords[p0][0], coords[p0][1], ranges[p0],
                                       coords[p1][0], coords[p1][1], ranges[p1])
            if pts:
                (xa, ya), (xb, yb) = pts
                if len(ranges) >= 3:
                    p2 = keys[2]
                    x2, y2 = coords[p2]
                    da = math.hypot(xa - x2, ya - y2)
                    db = math.hypot(xb - x2, yb - y2)
                    coords[aid] = (xa, ya) if abs(da - ranges[p2]) < abs(db - ranges[p2]) else (xb, yb)
                else:
                    coords[aid] = (xa, ya) if ya >= 0 else (xb, yb)
                continue

        # Ultimate fallback
        coords[aid] = (0.0, 0.0)

    return coords


# ==================== UWB OBJECT ====================

class UWB:
    def __init__(self, name, typ):
        self.name = name
        self.typ = typ                 # 0 = anchor, 1 = tag
        self.x = 0.0
        self.y = 0.0
        self.status = False
        self.ranges = {}               # anchor_id -> distance
        self.color = RED if typ == 1 else BLACK

    def set_loc(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.status = True

    def update_range(self, anchor_id, distance):
        self.ranges[anchor_id] = distance

    def clear_ranges(self):
        self.ranges.clear()

    def cal(self, anchors_coords):
        """Compute position from accumulated ranges."""
        valid = {aid: r for aid, r in self.ranges.items()
                 if r > 0.0 and aid in anchors_coords}
        if len(valid) < 3:
            print(f"[{self.name}] need >=3 anchors, have {len(valid)}")
            return False

        result = trilaterate(valid, anchors_coords)
        if result is None:
            print(f"[{self.name}] trilateration failed (geometry/noise)")
            return False

        self.set_loc(*result)
        print(f"[{self.name}] solved at ({self.x:.2f}, {self.y:.2f})")
        return True


# ==================== NETWORKING ====================

def create_udp_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((UDP_BIND, UDP_PORT))
    except OSError as e:
        raise SystemExit(f"Failed to bind UDP port {UDP_PORT}: {e}")
    sock.settimeout(1.0)
    return sock


def send_broadcast(sock, message: bytes, port=UDP_PORT):
    """Send a UDP message to broadcast and subnet."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except Exception:
        pass
    try:
        sock.sendto(message, ("192.168.4.255", port))
    except Exception:
        pass
    for i in range(2, 11):
        try:
            sock.sendto(message, (f"192.168.4.{i}", port))
        except Exception:
            pass


def discover_nodes(sock):
    """
    Send PING and collect PONGs.
    Returns list of dicts: [{'ip': str, 'id': int, 'role': int, 'net_id': int}, ...]
    """
    nodes = []
    seen = set()

    for attempt in range(DISCOVERY_RETRIES):
        print(f"\n[DISCOVERY] Attempt {attempt + 1}/{DISCOVERY_RETRIES}")
        send_broadcast(sock, b"PING")

        deadline = time.time() + PING_TIMEOUT
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

            try:
                node_id = int(parts[1])
                role = int(parts[2])
                net_id = int(parts[3])
            except Exception:
                continue

            key = (addr[0], node_id)
            if key in seen:
                continue
            seen.add(key)

            nodes.append({
                "ip": addr[0],
                "id": node_id,
                "role": role,
                "net_id": net_id,
            })
            print(f"  Found node ID={node_id} role={'ANCHOR' if role == 1 else 'TAG'} ip={addr[0]}")

        if nodes:
            break
        time.sleep(0.5)

    return nodes


def wait_for_node(sock, target_id, target_role, timeout=ROLE_SWITCH_DELAY):
    """Wait until a node responds to PING with the expected ID and role."""
    print(f"  Waiting for node {target_id} (role={target_role})...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        send_broadcast(sock, b"PING")
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

        try:
            node_id = int(parts[1])
            role = int(parts[2])
        except Exception:
            continue

        if node_id == target_id and role == target_role:
            print(f"  Node {target_id} is back (role={target_role}, ip={addr[0]}).")
            return True

    print(f"  WARNING: Node {target_id} did not respond in time.")
    return False


def send_role_command(sock, ip, new_role):
    """Send ROLE command and wait for ACK."""
    print(f"  Sending ROLE,{new_role} to {ip}...")
    try:
        sock.sendto(f"ROLE,{new_role}".encode(), (ip, UDP_PORT))
    except Exception as e:
        print(f"  ERROR sending ROLE: {e}")
        return False

    # Wait a moment for ACK
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        text = data.decode("utf-8", errors="ignore").strip()
        if text.startswith("ACK,ROLE,") and addr[0] == ip:
            print(f"  ACK received: {text}")
            return True

    print("  No ACK received, but proceeding anyway...")
    return True  # Proceed even without ACK; node may have rebooted quickly


def trigger_snap_and_collect(sock, target_id, all_anchor_ids):
    """
    Send SNAP trigger to the tag and collect ranges.
    Returns dict {anchor_id: median_distance}.
    """
    print(f"  Triggering SNAP for tag {target_id}...")
    send_broadcast(sock, b"SNAP")

    # Also try direct sends to common tag IPs
    for i in range(2, 11):
        try:
            sock.sendto(b"SNAP", (f"192.168.4.{i}", UDP_PORT))
        except Exception:
            pass

    samples = {aid: [] for aid in all_anchor_ids}
    deadline = time.time() + SNAP_LISTEN_SECONDS

    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue

        parsed = parse_snap_udp(data)
        if parsed is None:
            continue

        tid, ranges = parsed
        if tid != target_id:
            continue

        for aid, dist in ranges.items():
            if aid in samples and dist > 0:
                samples[aid].append(dist)

    # Compute medians
    result = {}
    for aid, vals in samples.items():
        if vals:
            vals.sort()
            n = len(vals)
            median = vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
            result[aid] = median
            print(f"    -> A{aid}: {median:.1f} cm (from {n} samples)")
        else:
            print(f"    -> A{aid}: NO DATA")

    return result


# ==================== PARSING ====================

def parse_at_range_line(line):
    """
    Parse AT+RANGE lines.
    BATCH : AT+RANGE tid:0,range:(101,109,54),ancid:(0,1,2)
    SINGLE: AT+RANGE tid:0,range:45,ancid:0
    Returns (tag_id, {anchor_id: distance}) or None.
    """
    if "AT+RANGE" not in line:
        return None

    line = line.strip()

    try:
        if "tid:" not in line:
            return None
        tid = int(line.split("tid:")[1].split(",")[0])

        if "ancid:(" in line and "range:(" in line:
            range_str = line.split("range:(")[1].split(")")[0]
            ancid_str = line.split("ancid:(")[1].split(")")[0]

            ranges = [float(v.strip()) if v.strip() else 0.0
                      for v in range_str.split(",")]
            ancids = [int(v.strip()) if v.strip() else -1
                      for v in ancid_str.split(",")]

            result = {}
            for aid, rng in zip(ancids, ranges):
                if 0 <= aid < MAX_ANCHORS and rng > 0:
                    result[aid] = rng
            return tid, result

        elif "ancid:" in line:
            aid = int(line.split("ancid:")[1].split(",")[0])
            rng = float(line.split("range:")[1].split(",")[0])
            if 0 <= aid < MAX_ANCHORS and rng > 0:
                return tid, {aid: rng}
            return tid, {}

        else:
            return None

    except Exception:
        return None


def parse_snap_udp(data):
    """
    SNAP packet:  b"SNAP,0,BTN,AT+RANGE tid:0,range:(...),ancid:(...),12345"
    Returns (tag_id, {anchor_id: distance}) or None.
    """
    text = data.decode("utf-8", errors="ignore").strip()
    if not text.startswith("SNAP,"):
        return None

    parts = text.split(",")
    if len(parts) < 5:
        return None

    try:
        tid = int(parts[1])
    except Exception:
        return None

    raw_line = ",".join(parts[3:-1])
    parsed = parse_at_range_line(raw_line)
    if parsed:
        return parsed
    return None


# ==================== AUTO-CALIBRATION ====================

def run_auto_calibration(sock):
    """
    Full auto-calibration sequence.
    Returns dict {anchor_id: (x, y)} or None on failure.
    """
    print("\n" + "=" * 50)
    print("AUTO-CALIBRATION")
    print("=" * 50)
    print("Make sure all anchors are powered on and joined to the ANL.")
    print("The ANL must be at IP 192.168.4.1.")
    input("\nPress ENTER to start auto-calibration...")

    # --- Discovery ---
    print("\n[1/4] Discovering nodes...")
    nodes = discover_nodes(sock)
    if not nodes:
        print("ERROR: No nodes found. Check WiFi connection and power.")
        return None

    # Identify ANL
    anl_node = None
    for n in nodes:
        if n["ip"] == "192.168.4.1":
            anl_node = n
            break

    if anl_node is None:
        print("WARNING: No node at 192.168.4.1 found. Using first node as origin.")
        anl_node = nodes[0]

    print(f"\nANL identified: ID={anl_node['id']} at {anl_node['ip']}")

    # Build list of anchors to calibrate (all anchors except ANL)
    anchor_nodes = [n for n in nodes if n["role"] == 1 and n["id"] != anl_node["id"]]
    all_anchor_ids = sorted([anl_node["id"]] + [n["id"] for n in anchor_nodes])
    print(f"Anchor IDs to calibrate: {all_anchor_ids}")

    if len(all_anchor_ids) < 3:
        print("ERROR: Need at least 3 anchors for 2D positioning.")
        return None

    # --- Collect pairwise distances ---
    distances = {}  # (min_id, max_id) -> median_distance

    # Distances from ANL to others: we need to turn each other anchor into a tag
    print(f"\n[2/4] Measuring pairwise distances ({len(anchor_nodes)} anchors to switch)...")

    for node in anchor_nodes:
        node_id = node["id"]
        node_ip = node["ip"]

        print(f"\n-- Switching anchor {node_id} to TAG --")
        if not send_role_command(sock, node_ip, 0):
            print(f"  FAILED to send ROLE,0 to {node_ip}. Skipping.")
            continue

        if not wait_for_node(sock, node_id, 0, timeout=ROLE_SWITCH_DELAY):
            print(f"  Node {node_id} did not become TAG. Trying anyway...")

        ranges = trigger_snap_and_collect(sock, node_id, all_anchor_ids)

        # Store distances (this tag to each anchor it measured)
        for aid, dist in ranges.items():
            key = (min(node_id, aid), max(node_id, aid))
            if key not in distances or distances[key] == 0:
                distances[key] = dist
            else:
                # Average with existing measurement
                distances[key] = (distances[key] + dist) / 2.0

        print(f"-- Switching tag {node_id} back to ANCHOR --")
        send_role_command(sock, node_ip, 1)
        wait_for_node(sock, node_id, 1, timeout=ROLE_SWITCH_DELAY)

    # --- Solve positions ---
    print("\n[3/4] Solving anchor positions...")
    print(f"Distance matrix ({len(distances)} pairs):")
    for (a, b), d in sorted(distances.items()):
        print(f"  A{a} <-> A{b}: {d:.1f} cm")

    coords = solve_anchor_positions(distances, all_anchor_ids)

    print("\nComputed anchor positions:")
    for aid in sorted(coords.keys()):
        x, y = coords[aid]
        print(f"  A{aid}: ({x:.2f}, {y:.2f})")

    print("\n[4/4] Auto-calibration complete!")
    return coords


# ==================== DISPLAY ====================

def compute_scale(anchors_coords):
    xs = [v[0] for v in anchors_coords.values()]
    ys = [v[1] for v in anchors_coords.values()]
    if not xs:
        return 1.0, SCREEN_X / 2, SCREEN_Y / 2
    mx, my = sum(xs) / len(xs), sum(ys) / len(xs)
    mr = max(math.hypot(x - mx, y - my) for x, y in anchors_coords.values()) or 100.0
    cm2p = (SCREEN_X / 2 * 0.9) / mr
    xoff = SCREEN_X / 2 - mx * cm2p
    yoff = SCREEN_Y / 2 - my * cm2p
    return cm2p, xoff, yoff


def draw_item(screen, it, cm2p, xoff, yoff):
    if not it.status and it.typ == 1:
        return
    px = int(it.x * cm2p + xoff)
    py = SCREEN_Y - int(it.y * cm2p + yoff)

    radius = 8 if it.typ == 1 else 5
    color = GREEN if it.typ == 0 else it.color
    pygame.draw.circle(screen, color, (px, py), radius, 0)

    label = f"{it.name} ({it.x:.1f},{it.y:.1f})" if it.status else it.name
    font = pygame.font.SysFont("Consola", 16)
    txt = font.render(label, True, it.color)
    screen.blit(txt, (px + 10, py - 10))


def refresh(screen, anchors, tags, cm2p, xoff, yoff, snap_count, last_seen_age):
    screen.fill(WHITE)
    pygame.draw.line(screen, GREY, (SCREEN_X // 2, 0),
                     (SCREEN_X // 2, SCREEN_Y), 1)
    pygame.draw.line(screen, GREY, (0, SCREEN_Y // 2),
                     (SCREEN_X, SCREEN_Y // 2), 1)

    for a in anchors:
        draw_item(screen, a, cm2p, xoff, yoff)
    for t in tags:
        draw_item(screen, t, cm2p, xoff, yoff)

    font = pygame.font.SysFont("Consola", 14)
    lines = [
        "Mode: SNAP (wireless, auto-cal)",
        "Red = Tag | Green = Anchor",
        f"SNAP packets: {snap_count}",
    ]
    if last_seen_age is not None:
        lines.append(f"Last update: {last_seen_age:.1f}s ago")
    else:
        lines.append("Waiting for SNAP... press tag button")
    lines.append("Close window to quit")

    for i, line in enumerate(lines):
        txt = font.render(line, True, BLACK)
        screen.blit(txt, (10, 10 + i * 16))

    pygame.display.flip()


# ==================== MAIN ====================

def main():
    parser = argparse.ArgumentParser(description="UWB Wireless Positioning with Auto-Calibration")
    parser.add_argument("--skip-autocal", action="store_true",
                        help="Skip auto-calibration and use hardcoded ANCHORS")
    args = parser.parse_args()

    # --- Auto-calibration phase ---
    if args.skip_autocal:
        anchors_coords = dict(ANCHORS)
        print("Using hardcoded ANCHORS (auto-cal skipped).")
    else:
        sock = create_udp_socket()
        anchors_coords = run_auto_calibration(sock)
        if anchors_coords is None:
            print("\nAuto-calibration failed. Falling back to hardcoded ANCHORS.")
            anchors_coords = dict(ANCHORS)
        sock.close()
        time.sleep(1)

    # --- Visualization phase ---
    print("\nStarting visualization...")
    print("Connect PC to RTLS-NET-XXXX WiFi and press the tag BOOT button.")

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_X, SCREEN_Y))
    pygame.display.set_caption("UWB Wireless Positioning")

    anchors = []
    for i in range(MAX_ANCHORS):
        a = UWB(f"A{i}", 0)
        if i in anchors_coords:
            a.set_loc(*anchors_coords[i])
        anchors.append(a)

    tags = [UWB(f"T{i}", 1) for i in range(MAX_TAGS)]

    cm2p, xoff, yoff = compute_scale(anchors_coords)

    udp_sock = create_udp_socket()
    udp_sock.setblocking(False)

    refresh(screen, anchors, tags, cm2p, xoff, yoff, 0, None)

    t_next = time.time()
    running = True
    snap_count = 0
    last_seen_time = None

    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False

        # UDP input
        try:
            data, addr = udp_sock.recvfrom(1024)
            parsed = parse_snap_udp(data)
            if parsed:
                tid, ranges = parsed
                print(f"  SNAP from {addr}: tid={tid} ranges={ranges}")
                snap_count += 1
                last_seen_time = time.time()
                if 0 <= tid < len(tags):
                    tags[tid].ranges.update(ranges)
                    if len(ranges) >= 3:
                        tags[tid].cal(anchors_coords)
        except BlockingIOError:
            pass
        except Exception as e:
            print(f"UDP error: {e}")

        # Refresh
        if time.time() >= t_next:
            age = (time.time() - last_seen_time) if last_seen_time else None
            refresh(screen, anchors, tags, cm2p, xoff, yoff, snap_count, age)
            t_next = time.time() + REFRESH_INTERVAL

        time.sleep(0.01)

    pygame.quit()
    udp_sock.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
