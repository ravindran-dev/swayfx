"""
Manual fade+slide-in, since GTK3 (unlike GTK4/libadwaita) has no built-in
implicit transitions for a window's own show animation. Driven by
GLib.timeout_add on a monotonic clock (not a fixed frame count), so the
150ms duration is accurate regardless of tick jitter, and eased with a
standard ease-out cubic so it decelerates like a native macOS popover
rather than moving linearly.
"""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, GtkLayerShell


def _ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def fade_slide_in(window, target_top_margin, slide_px=8, duration_ms=150, fps=60):
    """Animate window opacity 0->1 and layer-shell top margin
    (target - slide_px)->target over duration_ms."""
    start_time = GLib.get_monotonic_time()
    duration_us = duration_ms * 1000
    start_margin = target_top_margin - slide_px

    window.set_opacity(0.0)
    GtkLayerShell.set_margin(window, GtkLayerShell.Edge.TOP, start_margin)

    def _tick():
        elapsed = GLib.get_monotonic_time() - start_time
        t = min(1.0, elapsed / duration_us)
        eased = _ease_out_cubic(t)

        window.set_opacity(eased)
        margin = round(start_margin + (target_top_margin - start_margin) * eased)
        GtkLayerShell.set_margin(window, GtkLayerShell.Edge.TOP, margin)

        if t >= 1.0:
            window.set_opacity(1.0)
            GtkLayerShell.set_margin(window, GtkLayerShell.Edge.TOP, target_top_margin)
            return False
        return True

    GLib.timeout_add(int(1000 / fps), _tick)
