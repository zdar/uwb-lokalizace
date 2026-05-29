"""
UWB Wireless Positioning Visualizer
====================================
Works with the current MERGED firmware (src/main.cpp) WITHOUT any changes.

How it works
------------
When a tag is in a SNAP window (triggered by button press or UDP "SNAP" command),
it broadcasts AT+RANGE lines inside SNAP packets to 192.168.4.255:50000.
Any PC connected to the RTLS-NET-XXXX AP can receive these broadcasts directly.

Setup for a conference demo
---------------------------
1. Flash anchors with unique UWB_INDEX values matching the ANCHORS dict below.
2. Flash one node as a TAG (role 0).
3. Update ANCHORS coordinates to match your physical layout (centimetres).
4. Connect your PC to the RTLS-NET-XXXX WiFi network.
5. Run:  python positioning/position_wireless.py
6. Press the BOOT button on the tag (short press) to start a 5-second SNAP stream.
   The tag will broadcast ranges ~2×/s and the PC will compute & display its position.

Dependencies: pip install pygame
"""

import pygame
import socket
import time
import math
import sys

# ==================== CONFIGURATION ====================

# Anchor coordinates in centimetres.
# IDs must match the UWB_INDEX set on each anchor node.
# Update these to match your physical deployment.
ANCHORS = {
    0: (0.00,    0.00),
    1: (94.00,   0.00),
    2: (24.87,   96.86),
    3: (-73.22,  83.43),
}

UDP_PORT = 50000
UDP_BIND = "0.0.0.0"

SCREEN_X, SCREEN_Y = 800, 800
REFRESH_INTERVAL = 0.3          # display refresh period (seconds)

RED   = (255, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREY  = (180, 180, 180)
GREEN = (0, 200, 0)

MAX_ANCHORS = 8
MAX_TAGS = 8

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

    def cal(self):
        """Compute position from accumulated ranges."""
        valid = {aid: r for aid, r in self.ranges.items()
                 if r > 0.0 and aid in ANCHORS}
        if len(valid) < 3:
            print(f"[{self.name}] need >=3 anchors, have {len(valid)}")
            return False

        result = trilaterate(valid, ANCHORS)
        if result is None:
            print(f"[{self.name}] trilateration failed (geometry/noise)")
            return False

        self.set_loc(*result)
        print(f"[{self.name}] solved at ({self.x:.2f}, {self.y:.2f})")
        return True


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
    print("RAW>", line)

    try:
        if "tid:" not in line:
            return None
        tid = int(line.split("tid:")[1].split(",")[0])

        # BATCH format
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

        # SINGLE format
        elif "ancid:" in line:
            aid = int(line.split("ancid:")[1].split(",")[0])
            rng = float(line.split("range:")[1].split(",")[0])
            if 0 <= aid < MAX_ANCHORS and rng > 0:
                return tid, {aid: rng}
            return tid, {}

        else:
            print("  unrecognized AT+RANGE format")
            return None

    except Exception as e:
        print(f"Parse error: {e} | Line: {line}")
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

    # parts[0] = "SNAP"
    # parts[1] = tag_id
    # parts[2] = source (BTN / UDP)
    # parts[-1] = timestamp
    # everything in between = raw AT+RANGE line (may contain commas)
    try:
        tid = int(parts[1])
    except Exception:
        return None

    # Reconstruct the AT+RANGE line from parts[3:-1]
    raw_line = ",".join(parts[3:-1])
    parsed = parse_at_range_line(raw_line)
    if parsed:
        return parsed
    return None


# ==================== DISPLAY ====================

def compute_scale():
    xs = [v[0] for v in ANCHORS.values()]
    ys = [v[1] for v in ANCHORS.values()]
    if not xs:
        return 1.0, SCREEN_X / 2, SCREEN_Y / 2
    mx, my = sum(xs) / len(xs), sum(ys) / len(xs)
    mr = max(math.hypot(x - mx, y - my) for x, y in ANCHORS.values()) or 100.0
    cm2p = (SCREEN_X / 2 * 0.9) / mr
    xoff = SCREEN_X / 2 - mx * cm2p
    yoff = SCREEN_Y / 2 - my * cm2p
    return cm2p, xoff, yoff


def draw_item(screen, it, cm2p, xoff, yoff):
    if not it.status and it.typ == 1:
        return                      # don't draw tags with no fix yet
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
        "Mode: SNAP (wireless)",
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
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_X, SCREEN_Y))
    pygame.display.set_caption("UWB Wireless Positioning")

    anchors = []
    for i in range(MAX_ANCHORS):
        a = UWB(f"A{i}", 0)
        if i in ANCHORS:
            a.set_loc(*ANCHORS[i])
        anchors.append(a)

    tags = [UWB(f"T{i}", 1) for i in range(MAX_TAGS)]

    cm2p, xoff, yoff = compute_scale()

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        udp_sock.bind((UDP_BIND, UDP_PORT))
    except OSError as e:
        raise SystemExit(f"Failed to bind UDP port {UDP_PORT}: {e}")
    udp_sock.setblocking(False)
    print(f"Listening for SNAP packets on {UDP_BIND}:{UDP_PORT}")
    print("Make sure your PC is connected to the RTLS-NET-XXXX WiFi.")
    print("Press the BOOT button on the tag to start a 5-second SNAP stream.")

    refresh(screen, anchors, tags, cm2p, xoff, yoff, 0, None)

    t_next = time.time()
    running = True
    snap_count = 0
    last_seen_time = None

    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False

        # ---- UDP INPUT ----
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
                        tags[tid].cal()
        except BlockingIOError:
            pass
        except Exception as e:
            print(f"UDP error: {e}")

        # ---- REFRESH ----
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
