#!/usr/bin/env python3
"""Entry point: toggles the Wi-Fi popup (2nd click/invocation closes it),
matching waybar's usual click-to-toggle module behavior."""
import fcntl
import os
import signal
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


def main():
    existing = _already_running_pid()
    if existing:
        # Second click: ask the running instance to close itself and exit -
        # matches the old wofi script's "invoke again to dismiss" behavior.
        os.kill(existing, signal.SIGUSR1)
        return

    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another instance won the race

    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    net = network.Network()

    def quit_app():
        Gtk.main_quit()

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

    try:
        Gtk.main()
    finally:
        try:
            os.remove(PID_PATH)
        except FileNotFoundError:
            pass
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


if __name__ == "__main__":
    main()
