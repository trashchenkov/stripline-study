#!/usr/bin/env python3
"""pty-транспорт для CLI-харнессов.

Один адаптер на все CLI: запуск, стартовые шаги, отправка текста,
экран через pyte, ожидание приглашения и затишья, raw-лог, kill по pgid.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

import pyte
from capture import render

W, H = 160, 48
KEYS = {"ENTER": b"\r", "DOWN": b"\x1b[B", "UP": b"\x1b[A", "ESC": b"\x1b", "TAB": b"\t", "CTRL_C": b"\x03"}
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]|\r")


class PtySession:
    def __init__(self, profile: dict, workspace: str, out_dir: str, capture_dir: str | None = None):
        self.profile = profile
        self.workspace = workspace
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.screen = pyte.Screen(W, H)
        self.stream = pyte.Stream(self.screen)
        self.proc: subprocess.Popen | None = None
        self.master: int | None = None
        self.raw = open(os.path.join(out_dir, "raw.ansi"), "wb")
        self.events = open(os.path.join(out_dir, "events.jsonl"), "a", encoding="utf-8")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_change = time.monotonic()
        self.lock = threading.RLock()
        self.capture_dir = capture_dir
        self._cap_no = 0
        self._cap_stop = threading.Event()

    def _emit(self, **kw):
        if self.events.closed:
            return
        self.events.write(json.dumps({"ts": time.time(), **kw}, ensure_ascii=False) + "\n")
        self.events.flush()

    def start(self):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", H, W, 0, 0))
        env = {**os.environ, "TERM": "xterm-256color", "PWD": self.workspace, "WINEDLLOVERRIDES": "winedbg.exe=d", **(self.profile.get("env") or {})}
        cmd = [self.profile["command"], *(self.profile.get("args") or [])]
        self.proc = subprocess.Popen(
            cmd, stdin=slave, stdout=slave, stderr=slave, cwd=self.workspace, env=env,
            start_new_session=True, close_fds=True,
        )
        os.close(slave)
        self.master = master
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self._emit(event="start", pid=self.proc.pid, cmd=cmd)
        for step in self.profile.get("startup_steps") or []:
            wait = step.get("wait")
            if wait:
                ok = self.wait_for(wait, step.get("timeout_s", 20))
                if not ok and not step.get("optional"):
                    raise RuntimeError(f"стартовый шаг {step.get('id')}: не найден текст {wait!r}")
                if not ok:
                    continue
            if step.get("delay_ms"):
                time.sleep(step["delay_ms"] / 1000)
            for k in step.get("keys") or []:
                self.send_keys(k)
            time.sleep(0.3)

    def _read_loop(self):
        assert self.master is not None
        while not self._stop.is_set():
            try:
                r, _, _ = select.select([self.master], [], [], 0.1)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                data = os.read(self.master, 65536)
            except OSError:
                break
            if not data:
                break
            self.raw.write(data)
            self.raw.flush()
            try:
                with self.lock:
                    self.stream.feed(data.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                pass
            self._last_change = time.monotonic()

    def screen_text(self) -> str:
        with self.lock:
            return "\n".join(line.rstrip() for line in self.screen.display)

    def bottom_text(self, n=8) -> str:
        lines = [x.rstrip() for x in self.screen.display if x.strip()]
        return "\n".join(lines[-n:])

    def wait_for(self, needle: str, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if needle in self.screen_text():
                return True
            time.sleep(0.1)
        return False

    def send_keys(self, key: str):
        assert self.master is not None
        seq = KEYS.get(key, key.encode() if len(key) == 1 else b"")
        os.write(self.master, seq)
        self._emit(event="key", key=key)

    def send_text(self, text: str):
        assert self.master is not None
        if self.profile.get("bracketed_paste"):
            os.write(self.master, f"\x1b[200~{text}\x1b[201~".encode())
        else:
            os.write(self.master, text.encode())
        time.sleep(0.2)
        os.write(self.master, b"\r")
        if self.profile.get("double_enter"):
            time.sleep(0.8)
            os.write(self.master, b"\r")
        self._emit(event="send", text=text)

    def _cap_loop(self, settle: float):
        while not self._cap_stop.wait(settle):
            self.snapshot()

    def snapshot(self, caption: str = ""):
        if not self.capture_dir:
            return
        with self.lock:
            self._cap_no += 1
            render(self.screen, os.path.join(self.capture_dir, f"{self._cap_no:04d}.png"), caption)

    def wait_turn(self, timeout: float = 180) -> dict:
        self._cap_stop.clear()
        if self.capture_dir:
            self.snapshot("начало хода")
            threading.Thread(target=self._cap_loop, args=(2.0,), daemon=True).start()
        prompt = self.profile.get("prompt") or ""
        settle = (self.profile.get("settle_ms") or 1500) / 1000
        end = time.monotonic() + timeout
        seen = False
        last = ""
        stable_since = None
        while time.monotonic() < end:
            now = self.screen_text()
            if now != last:
                last, stable_since = now, time.monotonic()
            bottom = self.bottom_text(8)
            ready = prompt in self.bottom_text(4)
            busy = any(x in bottom for x in (self.profile.get("busy") or []))
            if ready and seen and not busy and stable_since and time.monotonic() - stable_since >= settle:
                self._cap_stop.set()
                self.snapshot("конец хода")
                return {"status": "ok", "screen": now}
            if ready:
                seen = True
            time.sleep(0.2)
        self._cap_stop.set()
        self.snapshot("таймаут хода")
        return {"status": "timeout", "screen": self.screen_text()}

    def stop(self):
        self._stop.set()
        if self.proc:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    self.proc.terminate()
                except ProcessLookupError:
                    pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            subprocess.run(["pkill", "-TERM", "-P", str(self.proc.pid)], capture_output=True)
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass
        self.raw.close()
        self._emit(event="stop")
        self.events.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--capture-dir")
    a = ap.parse_args()
    profile = json.load(open(a.profile))
    s = PtySession(profile, os.path.abspath(a.workspace), os.path.abspath(a.out), a.capture_dir)
    t0 = time.time()
    try:
        s.start()
        s.send_text(a.prompt)
        res = s.wait_turn(a.timeout)
    finally:
        s.stop()
    res["seconds"] = round(time.time() - t0, 1)
    open(os.path.join(a.out, "screen.txt"), "w").write(res.get("screen", ""))
    print(json.dumps({k: v for k, v in res.items() if k != "screen"}, ensure_ascii=False))
    print(res.get("screen", "")[-4000:])


if __name__ == "__main__":
    main()
