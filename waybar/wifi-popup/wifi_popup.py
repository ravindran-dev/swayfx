#!/usr/bin/env python3
"""Entry point: toggles the Wi-Fi popup (2nd click/invocation closes it),
matching waybar's usual click-to-toggle module behavior."""
import fcntl
import os
import signal
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

import network
import ui

LOCK_PATH = "/run/user/{}/wifi-popup.lock".format(os.getuid())
PID_PATH = "/run/user/{}/wifi-popup.pid".format(os.getuid())


def _already_running_pid():
    """Returns the running instance's PID if one holds the lock, else None."""
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # raises if not running
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return None


BLUETOOTH_PID_PATH = "/run/user/{}/bluetooth-popup.pid".format(os.getuid())
VOLUME_PID_PATH = "/run/user/{}/volume-popup.pid".format(os.getuid())


def _close_other_waybar_popups():
    # Without this, opening the Wi-Fi popup while the Bluetooth or Volume
    # one (or any other waybar popup) is open leaves both stacked in the
    # same corner - confirmed live, not hypothetical. Each popup script
    # closes the others on open so only one is ever visible at a time.
    try:
        # timeout=: confirmed live on this system that `pkill -f <pattern>`
        # can take far longer than expected to return (isolated the exact
        # same call hanging well past 10s, both here and independently in
        # sway's own exec_always) - `-f` has to read and regex-match every
        # process's full cmdline, and with this many heavyweight processes
        # running (browser content processes, several JVMs, ...) that scan
        # isn't as cheap as it looks. Without a timeout this could block
        # the popup from ever opening; with one, worst case is just a stale
        # wofi window staying open an extra moment.
        subprocess.run(["pkill", "-u", os.environ.get("USER", ""), "-f", "wofi.*--prompt"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    for pid_path in (BLUETOOTH_PID_PATH, VOLUME_PID_PATH):
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
        # Second click: ask the running instance to close itself and exit -
        # matches the old wofi script's "invoke again to dismiss" behavior.
        os.kill(existing, signal.SIGUSR1)
        return

    _close_other_waybar_popups()

    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another instance won the race

    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    net = network.Network()

    def quit_app():
        # NOT Gtk.main_quit(): confirmed live (repeatedly, with a stack
        # trace showing 10 threads blocked in futex_do_wait) that Gtk.main()
        # can simply never return even after main_quit() succeeds - some
        # libnm/GDBus-internal native worker thread that the GLib main loop
        # or Python's interpreter shutdown ends up waiting on. Observed
        # hangs ranged from a few seconds to 2+ minutes. This is the single
        # callback every close path (Escape, click-outside, selecting a
        # network, the SIGUSR1 second-click toggle) already funnels through
        # via popup.close_popup() -> on_closed - fixing it once here covers
        # all of them, rather than special-casing the signal path alone.
        try:
            os.remove(PID_PATH)
        except FileNotFoundError:
            pass
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        os._exit(0)

    popup = ui.WifiPopup(net, on_closed=quit_app)

    def _on_sigusr1():
        popup.close_popup()
        return GLib.SOURCE_REMOVE

    # NOT signal.signal(): CPython only runs those handlers between bytecode
    # instructions, and Gtk.main() blocks in C - the signal would sit pending
    # until some unrelated Python callback fired (observed as zombie instances
    # whose window was gone but whose process never exited). unix_signal_add
    # registers it as a GLib main-loop source, so it fires immediately.
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, _on_sigusr1)
    popup.show_animated()

    Gtk.main()


if __name__ == "__main__":
    main()
