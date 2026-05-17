import pygame
import serial
import serial.tools.list_ports
import time
import math

RED    = [255, 0, 0]
BLACK  = [0, 0, 0]
WHITE  = [255, 255, 255]
GREY   = [180, 180, 180]

ANCHORS = {
    0: (0.0,   0.0),
    1: (90.0,  0.0),
    2: (19.09, 93.06),
}
MAX_ANCHORS = 8
MAX_TAGS    = 8


class UWB:
    def __init__(self, name, typ):
        self.name   = name
        self.typ    = typ
        self.x = self.y = 0
        self.status = False
        self.list   = [0.0] * MAX_ANCHORS

        self.color = RED if typ == 1 else BLACK

    def set_loc(self, x, y):
        self.x = int(x)
        self.y = int(y)
        self.status = True

    def cal(self):
        anc_ids = [i for i, r in enumerate(self.list) if r > 0.0]

        print(f"[{self.name}] got ranges at anchors: {anc_ids}  values: {[self.list[i] for i in anc_ids]}")

        if len(anc_ids) < 3:
            print(f"  -> need 3 anchors to solve, only have {len(anc_ids)}")
            return False

        a0, a1, a2 = anc_ids[0], anc_ids[1], anc_ids[2]
        r0, r1, r2 = self.list[a0], self.list[a1], self.list[a2]

        for a in (a0, a1, a2):
            if a not in ANCHORS:
                print(f"  -> ERROR: anchor ID {a} has no hardcoded coordinate!")
                return False

        pts = circle_intersections(
            ANCHORS[a0][0], ANCHORS[a0][1], r0,
            ANCHORS[a1][0], ANCHORS[a1][1], r1
        )
        if pts is None:
            print("  -> circle intersection failed (noisy/bad ranges)")
            return False

        (xa, ya), (xb, yb) = pts
        da = math.hypot(xa - ANCHORS[a2][0], ya - ANCHORS[a2][1])
        db = math.hypot(xb - ANCHORS[a2][0], yb - ANCHORS[a2][1])

        if abs(da - r2) < abs(db - r2):
            self.set_loc(xa, ya)
        else:
            self.set_loc(xb, yb)

        print(f"  -> SOLVED {self.name} at ({self.x}, {self.y})")
        return True


def get_first_com():
    for p in serial.tools.list_ports.comports():
        print(f"Using: {p.device}")
        return p.device
    return ""


def circle_intersections(x0, y0, r0, x1, y1, r1):
    d = math.hypot(x1 - x0, y1 - y0)
    if d == 0 or d > r0 + r1 or d < abs(r0 - r1):
        return None
    a = (r0*r0 - r1*r1 + d*d) / (2.0*d)
    h = math.sqrt(max(r0*r0 - a*a, 0))
    xm = x0 + a*(x1-x0)/d
    ym = y0 + a*(y1-y0)/d
    rx = -(y1-y0)*(h/d)
    ry =  (x1-x0)*(h/d)
    return ((xm+rx, ym+ry), (xm-rx, ym-ry))


def draw_item(it):
    if not it.status:
        return
    px = int(it.x * cm2p + xoff)
    py = SCREEN_Y - int(it.y * cm2p + yoff)
    pygame.draw.circle(screen, it.color, [px+20, py+20], 8 if it.typ else 4, 0)
    txt = pygame.font.SysFont("Consola", 18).render(
        f"{it.name} ({it.x},{it.y})", True, it.color)
    screen.blit(txt, [px, py])


def read_data(ser):
    if ser.in_waiting == 0:
        return

    try:
        line = ser.readline().decode('UTF-8', errors='ignore').strip()
    except Exception:
        return

    if not line:
        return

    if "AT+RANGE" not in line:
        print("[LOG]", line)
        return

    print("RAW>", line)

    try:
        # =========================================================
        #  BATCH  format:  range:(101,109,54,...),ancid:(0,1,2,...)
        #  Check this FIRST because it also contains the word "ancid:"
        # =========================================================
        if "ancid:(" in line and "range:(" in line:
            tid = int(line.split("tid:")[1].split(",")[0])

            # extract the two parenthesised lists
            range_str  = line.split("range:(")[1].split(")")[0]
            ancid_str  = line.split("ancid:(")[1].split(")")[0]

            ranges = [float(v.strip()) if v.strip() else 0.0 for v in range_str.split(",")]
            ancids = [int(v.strip())   if v.strip() else -1  for v in ancid_str.split(",")]

            if 0 <= tid < len(tags):
                filled = 0
                for aid, rng in zip(ancids, ranges):
                    if 0 <= aid < MAX_ANCHORS and rng > 0:
                        tags[tid].list[aid] = rng
                        filled += 1
                print(f"  parsed batch -> tid={tid} filled={filled} pairs")
                if filled >= 3:
                    tags[tid].cal()

        # =========================================================
        #  SINGLE format:  range:45,ancid:0
        # =========================================================
        elif "ancid:" in line:
            tid = int(line.split("tid:")[1].split(",")[0])
            aid = int(line.split("ancid:")[1].split(",")[0])
            rng = float(line.split("range:")[1].split(",")[0])

            if 0 <= tid < len(tags) and 0 <= aid < MAX_ANCHORS:
                tags[tid].list[aid] = rng
                print(f"  parsed single -> tid={tid} anc={aid} rng={rng}")
                tags[tid].cal()
        else:
            print("  unrecognized AT+RANGE format")

    except Exception as e:
        print(f"Parse error: {e} | Line: {line}")


def refresh():
    screen.fill(WHITE)
    pygame.draw.line(screen, GREY, (SCREEN_X//2, 0), (SCREEN_X//2, SCREEN_Y), 1)
    pygame.draw.line(screen, GREY, (0, SCREEN_Y//2), (SCREEN_X, SCREEN_Y//2), 1)

    for a in anchors:
        draw_item(a)
    for t in tags:
        draw_item(t)
    pygame.display.flip()


# ================= MAIN =================
SCREEN_X, SCREEN_Y = 800, 800
pygame.init()
screen = pygame.display.set_mode([SCREEN_X, SCREEN_Y])

com = get_first_com()
if not com:
    raise SystemExit("No COM port")
ser = serial.Serial(com, 115200, timeout=0.05)

anchors = []
for i in range(MAX_ANCHORS):
    a = UWB(f"A{i}", 0)
    if i in ANCHORS:
        a.set_loc(*ANCHORS[i])
    anchors.append(a)

tags = [UWB(f"T{i}", 1) for i in range(MAX_TAGS)]

xs = [v[0] for v in ANCHORS.values()]
ys = [v[1] for v in ANCHORS.values()]
mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
mr = max(math.hypot(x-mx, y-my) for x,y in ANCHORS.values()) or 100

cm2p = (SCREEN_X/2 * 0.9) / mr
xoff = SCREEN_X/2 - mx*cm2p
yoff = SCREEN_Y/2 - my*cm2p

refresh()
ser.reset_input_buffer()

t_next = time.time()

while True:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            exit()

    read_data(ser)

    if time.time() >= t_next:
        refresh()
        t_next = time.time() + 0.5