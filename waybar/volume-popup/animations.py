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
from gi.repository import GLib


def _ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def fade_slide_in(window, panel, target_top_margin, slide_px=8, duration_ms=150, fps=60):
    """Animate window opacity 0->1 and the panel widget's own top margin
    (target - slide_px)->target over duration_ms. Animates the panel's
    widget margin rather than a layer-shell surface margin because the
    window itself is now a static, full-screen click-catching surface (see
    ui.py) - only the visible panel inside it should appear to slide."""
    start_time = GLib.get_monotonic_time()
    duration_us = duration_ms * 1000
    start_margin = target_top_margin - slide_px

    window.set_opacity(0.0)
    panel.set_margin_top(start_margin)

    def _tick():
        elapsed = GLib.get_monotonic_time() - start_time
        t = min(1.0, elapsed / duration_us)
        eased = _ease_out_cubic(t)

        window.set_opacity(eased)
        margin = round(start_margin + (target_top_margin - start_margin) * eased)
        panel.set_margin_top(margin)

        if t >= 1.0:
            window.set_opacity(1.0)
            panel.set_margin_top(target_top_margin)
            return False
        return True

    GLib.timeout_add(int(1000 / fps), _tick)
