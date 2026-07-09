#!/usr/bin/env python3
"""Entry point: toggles the Volume popup (2nd click/invocation closes it).
Mirrors wifi_popup.py's structure, including its hard-won shutdown fix - see
the comment on quit_app() below before touching the close sequence."""
import fcntl
import os
import signal
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

import audio
import ui

LOCK_PATH = "/run/user/{}/volume-popup.lock".format(os.getuid())
PID_PATH = "/run/user/{}/volume-popup.pid".format(os.getuid())
WIFI_PID_PATH = "/run/user/{}/wifi-popup.pid".format(os.getuid())
BLUETOOTH_PID_PATH = "/run/user/{}/bluetooth-popup.pid".format(os.getuid())


def _already_running_pid():
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return None


def _close_other_waybar_popups():
    # Mirrors wifi_popup.py/bluetooth_popup.py's own version of this -
    # without it, opening this popup while Wi-Fi or Bluetooth is open
    # leaves multiple stacked in the same corner (confirmed live when this
    # was first built for those two).
    try:
        # timeout=: see the matching comment in wifi_popup.py - `pkill -f`
        # confirmed live to sometimes take far longer than expected to
        # return on this system, which without a timeout could block this
        # popup from ever opening.
        subprocess.run(["pkill", "-u", os.environ.get("USER", ""), "-f", "wofi.*--prompt"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    for pid_path in (WIFI_PID_PATH, BLUETOOTH_PID_PATH):
        try:
            with open(pid_path) as f:
                other_pid = int(f.read().strip())
            os.kill(other_pid, 0)
            os.kill(other_pid, signal.SIGUSR1)
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            pass


def main():
    existing = _already_running_pid()
    if existing:
        os.kill(existing, signal.SIGUSR1)
        return

    _close_other_waybar_popups()

    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return

    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    aud = audio.Audio()

    def quit_app():
        # NOT Gtk.main_quit(): confirmed live on the Wi-Fi popup (stack
        # trace showed 10 threads blocked in futex_do_wait) that Gtk.main()
        # can simply never return even after main_quit() succeeds - a
        # native worker thread the loop/interpreter shutdown ends up
        # waiting on, for up to 2+ minutes. Do our own cleanup directly and
        # hard-exit instead; no GTK teardown needed since the whole process
        # is about to disappear regardless. Applied here from the start
        # rather than re-discovering the same bug independently.
        try:
            os.remove(PID_PATH)
        except FileNotFoundError:
            pass
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        os._exit(0)

    popup = ui.VolumePopup(aud, on_closed=quit_app)

    def _on_sigusr1():
        popup.close_popup()
        return GLib.SOURCE_REMOVE

    # NOT signal.signal(): see wifi_popup.py for why (Gtk.main() blocks in
    # C; a plain Python signal handler would sit pending indefinitely).
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, _on_sigusr1)
    popup.show_animated()

    Gtk.main()


if __name__ == "__main__":
    main()
