#!/usr/bin/env python3
"""
3D Anchor Calibration Driver
============================

Drives the ANL's option-B anchor self-calibration mode.  You move a single
tag to a few known 3D positions (measured relative to the ANL origin), the
ANL collects ranges from the tag's RPT packets, and then it solves each
anchor's 3D position with least-squares trilateration.

Usage
-----
    # Interactive wizard (default ANL IP is 192.168.4.1)
    python scripts/calibrate_anchors.py

    # Non-interactive single point
    python scripts/calibrate_anchors.py --tag 0 --point 100,50,30

    # Start / solve / cancel
    python scripts/calibrate_anchors.py --start
    python scripts/calibrate_anchors.py --solve
    python scripts/calibrate_anchors.py --cancel
    python scripts/calibrate_anchors.py --status
"""

import argparse
import socket
import sys
import time

ANL_IP = "192.168.4.1"
UDP_PORT = 50000
CAL3D_COLLECT_MS = 15000  # must match the ANL's CAL3D_COLLECT_MS


def send_cmd(ip, port, cmd, timeout=2.5):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    sock.sendto(cmd.encode("utf-8"), (ip, port))
    try:
        data, addr = sock.recvfrom(256)
        text = data.decode("utf-8", errors="ignore").strip()
        return text, addr
    except socket.timeout:
        return None, None
    finally:
        sock.close()


def interactive(ip, port, tag_id=None):
    print("=== 3D Anchor Calibration ===")
    print("Make sure the ANL is running and the calibration tag is reporting ranges.")
    print()

    if tag_id is None:
        tag_id = input("Calibration tag UWB ID (0-9): ").strip()
        if not tag_id.isdigit():
            print("Invalid tag ID")
            sys.exit(1)
        tag_id = int(tag_id)

    print(f"\nSending CAL,START to {ip}:{port} ...")
    reply, _ = send_cmd(ip, port, "CAL,START")
    print(f"  {reply or '(no reply)'}")
    if reply and reply.startswith("ERR"):
        sys.exit(1)

    points = []
    while True:
        raw = input(
            f"\nKnown point #{len(points)+1} as x,y,z cm (blank to solve): ").strip()
        if not raw:
            break
        try:
            parts = [p.strip() for p in raw.replace(" ", "").split(",")]
            if len(parts) != 3:
                raise ValueError
            x, y, z = map(float, parts)
        except Exception:
            print("  Expected format: x,y,z")
            continue

        cmd = f"CAL,POINT,{tag_id},{x:.2f},{y:.2f},{z:.2f}"
        print(f"  -> {cmd}")
        reply, _ = send_cmd(ip, port, cmd)
        print(f"  {reply or '(no reply)'}")
        if not reply or not reply.startswith("ACK,CAL,POINT"):
            print("  Point was not accepted by the ANL; not counting it.")
            continue

        points.append((x, y, z))
        # The ANL collects for CAL3D_COLLECT_MS (default 15s).
        print("  Wait for the collection window to finish before moving the tag.")

    if len(points) < 4:
        print(f"\nNeed at least 4 points for 3D solving; got {len(points)}.")
        print("Cancelling calibration on ANL.")
        send_cmd(ip, port, "CAL,CANCEL")
        sys.exit(1)

    # Make sure the last point's collection window has closed before solving.
    print(f"\nWaiting {CAL3D_COLLECT_MS}ms for the last point's collection window ...")
    time.sleep(CAL3D_COLLECT_MS / 1000.0)

    print("\nSending CAL,SOLVE ...")
    reply, _ = send_cmd(ip, port, "CAL,SOLVE")
    print(f"  {reply or '(no reply)'}")
    if reply and reply.startswith("ACK,CAL,SOLVED"):
        print("Calibration complete. Anchor positions are now stored on the ANL.")
    else:
        print("Solve failed. Check ANL serial log for details.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Drive ANL 3D anchor calibration")
    parser.add_argument("--ip", default=ANL_IP, help="ANL IP address")
    parser.add_argument("--port", type=int, default=UDP_PORT, help="UDP port")
    parser.add_argument("--tag", type=int, help="Calibration tag UWB ID")
    parser.add_argument("--start", action="store_true", help="Send CAL,START")
    parser.add_argument("--point", help="Send CAL,POINT,tid,x,y,z (format x,y,z)")
    parser.add_argument("--solve", action="store_true", help="Send CAL,SOLVE")
    parser.add_argument("--cancel", action="store_true", help="Send CAL,CANCEL")
    parser.add_argument("--status", action="store_true", help="Send CAL,STATUS")
    args = parser.parse_args()

    if args.start:
        print(send_cmd(args.ip, args.port, "CAL,START")[0] or "(no reply)")
        return
    if args.cancel:
        print(send_cmd(args.ip, args.port, "CAL,CANCEL")[0] or "(no reply)")
        return
    if args.status:
        print(send_cmd(args.ip, args.port, "CAL,STATUS")[0] or "(no reply)")
        return
    if args.solve:
        print(send_cmd(args.ip, args.port, "CAL,SOLVE")[0] or "(no reply)")
        return
    if args.point:
        if args.tag is None:
            print("--point requires --tag")
            sys.exit(1)
        try:
            x, y, z = map(float, args.point.split(","))
        except Exception:
            print("--point format: x,y,z")
            sys.exit(1)
        cmd = f"CAL,POINT,{args.tag},{x:.2f},{y:.2f},{z:.2f}"
        print(send_cmd(args.ip, args.port, cmd)[0] or "(no reply)")
        return

    interactive(args.ip, args.port, args.tag)


if __name__ == "__main__":
    main()
