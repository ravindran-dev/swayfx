"""
PulseAudio/PipeWire volume control via pactl - same situation as
bluetooth.py had (no GI-introspectable binding like libnm exists for audio
on this system), so this shells out rather than pretending a native
binding is available. Signal-driven via `pactl subscribe` (confirmed live:
reliably emits "Event 'change' on sink #N" for every volume/mute change,
regardless of source - media keys, this popup, or any other app) instead
of polling.
"""
import re
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject

SINK = "@DEFAULT_SINK@"


class Audio(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self._subscribe_proc = None
        self._start_subscribe_watch()

    def _start_subscribe_watch(self):
        try:
            self._subscribe_proc = subprocess.Popen(
                ["pactl", "subscribe"],
                stdout=subprocess.PIPE, text=True, bufsize=1,
            )
        except FileNotFoundError:
            return

        def _on_line(source, condition):
            if condition & (GLib.IO_HUP | GLib.IO_ERR):
                return False
            line = source.readline()
            if not line:
                return False
            if "sink" in line or "server" in line:
                self.emit("changed")
            return True

        GLib.io_add_watch(
            self._subscribe_proc.stdout, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, _on_line
        )

    def stop(self):
        if self._subscribe_proc is not None:
            self._subscribe_proc.terminate()
            self._subscribe_proc = None

    # ---- state -----------------------------------------------------

    def get_volume(self):
        """0-100, read from the first channel - this system's sinks aren't
        independently panned, all channels track together in practice."""
        try:
            out = subprocess.run(
                ["pactl", "get-sink-volume", SINK],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout
            m = re.search(r"(\d+)%", out)
            return int(m.group(1)) if m else 0
        except Exception:
            return 0

    def is_muted(self):
        try:
            out = subprocess.run(
                ["pactl", "get-sink-mute", SINK],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout
            return "yes" in out
        except Exception:
            return False

    # ---- actions -----------------------------------------------------
    # Synchronous, deliberately: a slider needs to feel instant as it's
    # dragged, and `pactl set-sink-volume` is a fast local call (no network,
    # no slow hardware negotiation like the hotspot's nmcli calls) - the
    # async-with-callback pattern used elsewhere in these popups exists to
    # keep the UI thread free during genuinely slow operations, which this
    # isn't.

    def set_volume(self, pct):
        pct = max(0, min(100, int(pct)))
        subprocess.run(["pactl", "set-sink-volume", SINK, f"{pct}%"],
                        capture_output=True, timeout=5)

    def set_muted(self, muted):
        subprocess.run(["pactl", "set-sink-mute", SINK, "1" if muted else "0"],
                        capture_output=True, timeout=5)

    def toggle_mute(self):
        subprocess.run(["pactl", "set-sink-mute", SINK, "toggle"],
                        capture_output=True, timeout=5)
