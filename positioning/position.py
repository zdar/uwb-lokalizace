"""
UWB Positioning Visualizer
============================
Works with the current MERGED firmware (src/main.cpp).

Three operating modes:
  1. SERIAL – USB cable to a TAG (default). Parses AT+RANGE lines directly.
  2. UDP    – WiFi listener. Receives RPT packets wirelessly (needs tag
              firmware change to broadcast instead of unicast).
  3. SOL    – WiFi listener. Receives SOL (solved) packets from the ANL.
              The ANL computes positions and broadcasts them – no local
              trilateration needed on the PC.

WIRELESS POSITIONING (no USB cable to the Tag)
-----------------------------------------------
With the stock firmware the Tag sends RPT packets to the ANL (192.168.4.1)
via UDP.  The ANL does NOT re-print the raw ranges on its own serial, so
simply moving the USB cable to the ANL will not give you positions.

Three ways to get wireless / cable-free tag positions:

A) PC joins the WiFi network + UDP broadcast (small firmware change)
   In src/main.cpp change relayUwbLine() from:
       udp.beginPacket("192.168.4.1", WIFI_PORT);
   to:
       udp.beginPacket(IPAddress(255,255,255,255), WIFI_PORT);
   Then set MODE = "udp" below and connect the PC to the RTLS-NET-XXXX AP.

B) Connect PC to the ANL via USB and add one line to the firmware
   In handleIncomingUdp() inside the RPT block, after the existing logs:
       SERIAL_LOG.print(F("RPTLINE,"));
       SERIAL_LOG.println(rpt);   // rpt = buf+4, the raw AT+RANGE string
   Then set MODE = "serial" and connect to the ANL COM port.
   The script will parse lines that start with "RPTLINE,AT+RANGE...".

C) Let the ANL compute positions itself  ← IMPLEMENTED
   The ANL now calls solveTrilateration2D() inside handleIncomingUdp()
   when an RPT arrives, then broadcasts a SOL packet to 255.255.255.255.
   Set MODE = "sol" below, connect the PC to the RTLS-NET-XXXX AP,
   and the script will display positions directly – no USB cable needed.
"""

import pygame
import serial
import serial.tools.list_ports
import socket
import time
import math
import sys

# ==================== CONFIGURATION ====================

# Anchor coordinates in centimetres.
# IDs must match the UWB_INDEX set on each anchor node.
# Update these to match your physical deployment.
# Each entry is (x, y, z); for 2D layouts set z = 0.
ANCHORS = {
    0: (0.00,    0.00,   0.00),
    1: (94.00,   0.00,   0.00),
    2: (24.87,   96.86,  0.00),
    3: (-73.22,  83.43,  0.00),
    # Example alternative layout (from dist_comp.py):
    # 0: (0.00,    0.00,   0.00),
    # 2: (41.54,  -84.33,  0.00),
    # 3: (-0.32,   96.00,   0.00),
    # 4: (70.00,   0.00,   0.00),
}

# "serial" -> USB cable to TAG (or ANL if you added RPTLINE output)
# "udp"    -> WiFi UDP listener. Receives RPT packets (needs tag broadcast).
# "sol"    -> WiFi UDP listener. Receives SOL packets from ANL (Option C).
MODE = "serial"

SERIAL_BAUD = 115200
SERIAL_TIMEOUT = 0.05

UDP_PORT = 50000
UDP_BIND = "0.0.0.0"

SCREEN_X, SCREEN_Y = 800, 800
REFRESH_INTERVAL = 0.5          # display refresh period (seconds)

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

    # Try every combination of 3 anchors and average the results.
    positions = []
    ids = [aid for aid, _ in valid]
    n = len(ids)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a0, a1, a2 = ids[i], ids[j], ids[k]
                r0, r1, r2 = ranges[a0], ranges[a1], ranges[a2]
                x0, y0 = anchors_coords[a0][:2]
                x1, y1 = anchors_coords[a1][:2]
                x2, y2 = anchors_coords[a2][:2]

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


def _solve_linear_3x3(A, b):
    """Solve A*x = b for a 3x3 matrix using Gaussian elimination."""
    M = [row[:] + [bi] for row, bi in zip(A, b)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-9:
            return None
        M[col], M[pivot] = M[pivot], M[col]
        piv = M[col][col]
        for k in range(col, 4):
            M[col][k] /= piv
        for row in range(3):
            if row == col:
                continue
            factor = M[row][col]
            if abs(factor) < 1e-12:
                continue
            for k in range(col, 4):
                M[row][k] -= factor * M[col][k]
    return [M[0][3], M[1][3], M[2][3]]


def _solve_least_squares_3d(A, b):
    """Solve the over-determined linear system A*x = b in the least-squares sense.
    A is a list of rows (each length 3). Builds normal equations A^T A x = A^T b.
    """
    AtA = [[0.0]*3 for _ in range(3)]
    Atb = [0.0]*3
    for row, bi in zip(A, b):
        for i in range(3):
            for j in range(3):
                AtA[i][j] += row[i] * row[j]
            Atb[i] += row[i] * bi
    return _solve_linear_3x3(AtA, Atb)


def trilaterate_3d(ranges, anchors_coords):
    """
    ranges         – dict {anchor_id: distance}
    anchors_coords – dict {anchor_id: (x, y, z)}
    Returns (x, y, z) or None.
    Uses linear least-squares (first equation subtracted).
    """
    valid = [(aid, r, anchors_coords[aid])
             for aid, r in ranges.items()
             if r > 0.0 and aid in anchors_coords]
    if len(valid) < 4:
        return None

    # Use the first valid anchor as the reference equation.
    _, ref_r, (x0, y0, z0) = valid[0]
    p0sq = x0*x0 + y0*y0 + z0*z0

    A = []
    b = []
    for aid, r, (x, y, z) in valid[1:]:
        A.append([2*(x - x0), 2*(y - y0), 2*(z - z0)])
        pisq = x*x + y*y + z*z
        b.append((pisq - r*r) - (p0sq - ref_r*ref_r))

    sol = _solve_least_squares_3d(A, b)
    if sol is None:
        return None
    return tuple(sol)


# ==================== UWB OBJECT ====================

class UWB:
    def __init__(self, name, typ):
        self.name = name
        self.typ = typ                 # 0 = anchor, 1 = tag
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.status = False
        self.ranges = {}               # anchor_id -> distance
        self.color = RED if typ == 1 else BLACK

    def set_loc(self, x, y, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
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

        # Use 3D whenever at least 4 anchors are available, but fall back to 2D.
        if len(valid) >= 4:
            result = trilaterate_3d(valid, ANCHORS)
            if result is not None:
                self.set_loc(*result)
                print(f"[{self.name}] solved at ({self.x:.2f}, {self.y:.2f}, {self.z:.2f})")
                return True
            print(f"[{self.name}] 3D trilateration failed, trying 2D fallback")

        result = trilaterate(valid, ANCHORS)
        if result is None:
            print(f"[{self.name}] trilateration failed (geometry/noise)")
            return False
        self.set_loc(*result)
        print(f"[{self.name}] solved at ({self.x:.2f}, {self.y:.2f})")
        return True


# ==================== I/O HELPERS ====================

def get_first_com():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return None
    print(f"Using serial port: {ports[0].device}")
    return ports[0].device


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


def parse_rpt_udp(data):
    """
    UDP packet:  b"RPT,AT+RANGE tid:0,range:(...),ancid:(...)"
    """
    text = data.decode("utf-8", errors="ignore").strip()
    if text.startswith("RPT,"):
        return parse_at_range_line(text[4:])
    return None


def _parse_sol_parts(parts):
    """Parse the comma-separated fields of a SOL packet.
    Accepts both legacy 4-field (x,y) and new 5-field (x,y,z) formats.
    Returns (tag_id, x, y, z) or None.
    """
    try:
        if len(parts) == 4:
            tid = int(parts[1])
            x = float(parts[2])
            y = float(parts[3])
            return tid, x, y, 0.0
        if len(parts) == 5:
            tid = int(parts[1])
            x = float(parts[2])
            y = float(parts[3])
            z = float(parts[4])
            return tid, x, y, z
    except Exception:
        pass
    return None


def parse_sol_udp(data):
    """
    UDP packet:  b"SOL,0,123.45,67.89,0.00"  or legacy b"SOL,0,123.45,67.89"
    Returns (tag_id, x, y, z) or None.
    """
    text = data.decode("utf-8", errors="ignore").strip()
    if not text.startswith("SOL,"):
        return None
    return _parse_sol_parts(text.split(","))


def parse_sol_line(line):
    """
    Serial line:  "SOL,0,123.45,67.89,0.00"  or legacy "SOL,0,123.45,67.89"
    Returns (tag_id, x, y, z) or None.
    """
    if not line.startswith("SOL,"):
        return None
    return _parse_sol_parts(line.split(","))


# ==================== DISPLAY ====================

def compute_scale():
    xs = [v[0] for v in ANCHORS.values()]
    ys = [v[1] for v in ANCHORS.values()]
    if not xs:
        return 1.0, SCREEN_X / 2, SCREEN_Y / 2
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
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

    if it.status:
        if it.z != 0.0 or it.typ == 1:
            label = f"{it.name} ({it.x:.1f},{it.y:.1f},{it.z:.1f})"
        else:
            label = f"{it.name} ({it.x:.1f},{it.y:.1f})"
    else:
        label = it.name
    font = pygame.font.SysFont("Consola", 16)
    txt = font.render(label, True, it.color)
    screen.blit(txt, (px + 10, py - 10))


def refresh(screen, anchors, tags, cm2p, xoff, yoff):
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
        f"Mode: {MODE}",
        "Red = Tag | Green = Anchor",
        "Close window to quit",
    ]
    for i, line in enumerate(lines):
        txt = font.render(line, True, BLACK)
        screen.blit(txt, (10, 10 + i * 16))

    pygame.display.flip()


# ==================== MAIN ====================

def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_X, SCREEN_Y))
    pygame.display.set_caption("UWB Positioning")

    anchors = []
    for i in range(MAX_ANCHORS):
        a = UWB(f"A{i}", 0)
        if i in ANCHORS:
            a.set_loc(*ANCHORS[i])
        anchors.append(a)

    tags = [UWB(f"T{i}", 1) for i in range(MAX_TAGS)]

    cm2p, xoff, yoff = compute_scale()

    ser = None
    udp_sock = None

    if MODE == "serial":
        com = get_first_com()
        if not com:
            raise SystemExit("No COM port found.  Is the TAG (or ANL) connected via USB?")
        ser = serial.Serial(com, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
        ser.reset_input_buffer()
        print("Serial mode active.")

    elif MODE == "udp":
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.bind((UDP_BIND, UDP_PORT))
        udp_sock.setblocking(False)
        print(f"UDP mode active.  Listening on {UDP_BIND}:{UDP_PORT}")
        print("Make sure the firmware broadcasts RPT packets (see docstring).")

    elif MODE == "sol":
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.bind((UDP_BIND, UDP_PORT))
        udp_sock.setblocking(False)
        print(f"SOL mode active.  Listening on {UDP_BIND}:{UDP_PORT}")
        print("ANL broadcasts solved positions – no local math needed.")

    else:
        raise SystemExit(f"Unknown MODE: {MODE}")

    refresh(screen, anchors, tags, cm2p, xoff, yoff)

    t_next = time.time()
    running = True

    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False

        # ---- SERIAL INPUT ----
        if MODE == "serial" and ser:
            while ser.in_waiting > 0:
                try:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue
                if not line:
                    continue

                # If connected to ANL with RPTLINE forwarding, strip the prefix
                if line.startswith("RPTLINE,"):
                    line = line[8:]

                # SOL line from ANL serial (Option C over USB)
                if line.startswith("SOL,"):
                    parsed = parse_sol_line(line)
                    if parsed:
                        tid, x, y, z = parsed
                        print(f"  SOL from serial: tid={tid} x={x:.2f} y={y:.2f} z={z:.2f}")
                        if 0 <= tid < len(tags):
                            tags[tid].set_loc(x, y, z)
                    continue

                if "AT+RANGE" not in line:
                    if line:
                        print("[LOG]", line)
                    continue

                parsed = parse_at_range_line(line)
                if parsed:
                    tid, ranges = parsed
                    if 0 <= tid < len(tags):
                        # BATCH replaces everything; SINGLE adds one.
                        # For simplicity we merge: if BATCH came in it already
                        # contains all anchors for this report.
                        tags[tid].ranges.update(ranges)
                        if len(ranges) >= 3:
                            tags[tid].cal()

        # ---- UDP INPUT ----
        elif MODE in ("udp", "sol") and udp_sock:
            try:
                data, addr = udp_sock.recvfrom(1024)
                if MODE == "udp":
                    parsed = parse_rpt_udp(data)
                    if parsed:
                        tid, ranges = parsed
                        print(f"  UDP from {addr}: tid={tid} ranges={ranges}")
                        if 0 <= tid < len(tags):
                            tags[tid].ranges.update(ranges)
                            if len(ranges) >= 3:
                                tags[tid].cal()
                elif MODE == "sol":
                    parsed = parse_sol_udp(data)
                    if parsed:
                        tid, x, y, z = parsed
                        print(f"  SOL from {addr}: tid={tid} x={x:.2f} y={y:.2f} z={z:.2f}")
                        if 0 <= tid < len(tags):
                            tags[tid].set_loc(x, y, z)
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"UDP error: {e}")

        # ---- REFRESH ----
        if time.time() >= t_next:
            refresh(screen, anchors, tags, cm2p, xoff, yoff)
            t_next = time.time() + REFRESH_INTERVAL

        time.sleep(0.01)

    pygame.quit()
    if ser:
        ser.close()
    if udp_sock:
        udp_sock.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
