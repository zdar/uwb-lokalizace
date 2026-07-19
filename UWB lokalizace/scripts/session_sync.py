"""Session CSV sync tool.

Copies session CSV files from the local sessions/ folder to a user-selected
backup folder (e.g. a cloud-synced disk) every N minutes.

This is a standalone Tkinter GUI that can be launched alongside pc_anl.py.
"""

import os
import shutil
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(PROJECT_ROOT, "sessions")
DEFAULT_INTERVAL_MIN = 3
CONFIG_FILE = os.path.join(PROJECT_ROOT, "session_sync_config.txt")


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------
def sync_now(source_dir, dest_dir, log_func):
    """Copy all session CSVs from source to dest that are new or changed."""
    if not os.path.isdir(source_dir):
        log_func(f"Source folder does not exist: {source_dir}")
        return 0
    if not os.path.isdir(dest_dir):
        log_func(f"Destination folder does not exist: {dest_dir}")
        return 0

    copied = 0
    for name in os.listdir(source_dir):
        if not name.lower().endswith(".csv"):
            continue
        src_path = os.path.join(source_dir, name)
        dst_path = os.path.join(dest_dir, name)

        try:
            src_stat = os.stat(src_path)
            if os.path.exists(dst_path):
                dst_stat = os.stat(dst_path)
                if src_stat.st_size == dst_stat.st_size and src_stat.st_mtime <= dst_stat.st_mtime:
                    continue
            shutil.copy2(src_path, dst_path)
            copied += 1
            log_func(f"Copied {name}")
        except Exception as e:
            log_func(f"Failed to copy {name}: {e}")

    if copied == 0:
        log_func("No new or changed session files")
    return copied


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class SessionSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title("UWB Session Sync")
        self.root.geometry("600x400")
        self.root.minsize(500, 300)

        self.dest_dir = tk.StringVar()
        self.interval_min = tk.IntVar(value=DEFAULT_INTERVAL_MIN)
        self.running = False
        self.timer_thread = None
        self.stop_event = threading.Event()

        self._build_ui()
        self._load_config()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        tk.Label(self.root, text="Backup destination folder:", anchor="w").pack(fill="x", **pad)

        dest_frame = tk.Frame(self.root)
        dest_frame.pack(fill="x", **pad)
        tk.Entry(dest_frame, textvariable=self.dest_dir).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(dest_frame, text="Browse...", command=self._browse).pack(side="right")

        interval_frame = tk.Frame(self.root)
        interval_frame.pack(fill="x", **pad)
        tk.Label(interval_frame, text="Sync interval (minutes):").pack(side="left", padx=(0, 6))
        tk.Spinbox(interval_frame, from_=1, to=60, textvariable=self.interval_min, width=6).pack(side="left")

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill="x", **pad)
        self.start_btn = tk.Button(btn_frame, text="Start sync", command=self._start, bg="green", fg="white")
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = tk.Button(btn_frame, text="Stop sync", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 6))
        tk.Button(btn_frame, text="Sync now", command=self._sync_now).pack(side="left")

        tk.Label(self.root, text="Log:", anchor="w").pack(fill="x", **pad)

        log_frame = tk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, **pad)
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        self.log_box = tk.Text(log_frame, height=10, yscrollcommand=scrollbar.set, state="disabled")
        self.log_box.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log_box.yview)

        status_frame = tk.Frame(self.root)
        status_frame.pack(fill="x", side="bottom", **pad)
        self.status_label = tk.Label(status_frame, text="Ready", anchor="w")
        self.status_label.pack(side="left")

    def _browse(self):
        folder = filedialog.askdirectory(title="Select backup destination folder")
        if folder:
            self.dest_dir.set(folder)
            self._save_config()

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self.log_box.config(state="normal")
        self.log_box.insert("end", line)
        self.log_box.see("end")
        self.log_box.config(state="disabled")
        print(line.strip())

    def _sync_now(self):
        dest = self.dest_dir.get().strip()
        if not dest:
            messagebox.showwarning("No destination", "Please select a destination folder first.")
            return
        self._log("Manual sync started")
        sync_now(SESSIONS_DIR, dest, self._log)

    def _run_timer(self):
        while not self.stop_event.is_set():
            dest = self.dest_dir.get().strip()
            if dest and os.path.isdir(dest):
                self._log("Scheduled sync started")
                sync_now(SESSIONS_DIR, dest, self._log)
            else:
                self._log("Destination not set, skipping scheduled sync")

            # Wait for the configured interval, checking stop_event frequently.
            minutes = max(1, self.interval_min.get())
            for _ in range(minutes * 60):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

    def _start(self):
        dest = self.dest_dir.get().strip()
        if not dest:
            messagebox.showwarning("No destination", "Please select a destination folder first.")
            return
        if not os.path.isdir(SESSIONS_DIR):
            messagebox.showwarning("No sessions", f"Session folder not found:\n{SESSIONS_DIR}")
            return

        self.stop_event.clear()
        self.running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_label.config(text=f"Running (every {self.interval_min.get()} min)")
        self._save_config()

        # Run an initial sync immediately.
        self._sync_now()

        self.timer_thread = threading.Thread(target=self._run_timer, daemon=True)
        self.timer_thread.start()

    def _stop(self):
        self.stop_event.set()
        self.running = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_label.config(text="Stopped")
        self._log("Sync stopped")

    def _load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    lines = f.read().strip().splitlines()
                if lines:
                    self.dest_dir.set(lines[0].strip())
                if len(lines) > 1:
                    try:
                        self.interval_min.set(int(lines[1].strip()))
                    except Exception:
                        pass
        except Exception as e:
            self._log(f"Could not load config: {e}")

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(f"{self.dest_dir.get().strip()}\n")
                f.write(f"{self.interval_min.get()}\n")
        except Exception as e:
            self._log(f"Could not save config: {e}")


def main():
    root = tk.Tk()
    app = SessionSyncApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
