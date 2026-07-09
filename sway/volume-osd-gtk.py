#!/usr/bin/env python3
"""
Volume OSD bar - replaces wob.

wob has zero rounded-corner support (confirmed directly in its source,
src/wob.c: it draws a plain rectangle, no radius concept anywhere in the
codebase), and swayfx's own `layer_effects ... corner_radius` for
layer-shell surfaces only shapes the drop-shadow's clip region
(sway/desktop/layer_shell.c: corner_radius is only ever read by
wlr_scene_shadow_set_clipped_region) - unlike regular app windows
(sway/tree/container.c), which get a real corner-clipped background via a
dedicated fx_corner_radii struct. There's no swayfx-side way to round a
layer-shell surface's own rendered content, which is why the Wi-Fi/
Bluetooth/Volume popups only *look* rounded: their own GTK CSS
(border-radius) draws the rounded shape, swayfx's layer_effects for them
is just for blur/shadow on top of that. Same fix applies here: a small
GTK layer-shell overlay that rounds itself via ordinary CSS.

Reads 0-100 integer values from stdin, one per line (fed by
`tail -f $FIFO | this script`, launched from volume-osd-daemon.sh - the
same `tail -f | consumer` pattern wob itself used) - a single long-lived
process and window, not one spawned per keypress, so rapid key repeats
update the same bar and reset its fade timer instead of stacking windows.
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

TIMEOUT_MS = 1200
WIDTH = 320
HEIGHT = 26
MARGIN_BOTTOM = 90

CSS = b"""
window.volume-osd {
  background: transparent;
}
box.volume-osd-panel {
  background-color: rgba(14, 18, 24, 0.91);
  border: 2px solid rgba(0, 255, 255, 0.75);
  border-radius: 999px;
  box-shadow: 0 0 14px rgba(0, 255, 255, 0.25);
}
box.volume-osd-fill {
  background-color: #00ffff;
  border-radius: 999px;
  min-height: 18px;
  margin: 4px;
}
"""


class VolumeOSD(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.get_style_context().add_class("volume-osd")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WIDTH, HEIGHT)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        # Own namespace (not "wob" - nothing named "wob" runs anymore) so
        # swayfx's blur/shadow effects (real, unlike corner_radius here -
        # see module docstring) can still target it specifically.
        GtkLayerShell.set_namespace(self, "volume-osd")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, MARGIN_BOTTOM)
        # No keyboard focus at all - this is a passive, transient
        # indicator, never meant to be clicked or typed into.
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        self.connect("realize", self._load_css)

        panel = Gtk.Box()
        panel.get_style_context().add_class("volume-osd-panel")
        panel.set_size_request(WIDTH, HEIGHT)
        self._fill = Gtk.Box()
        self._fill.get_style_context().add_class("volume-osd-fill")
        self._fill.set_halign(Gtk.Align.START)
        self._fill.set_valign(Gtk.Align.FILL)
        panel.pack_start(self._fill, False, False, 0)
        self.add(panel)
        self._panel_width = WIDTH

        self._hide_timer = None
        self.set_opacity(0.0)

    def _load_css(self, *_a):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def show_value(self, pct):
        pct = max(0, min(100, pct))
        # Fixed-width fill box rather than a real progress bar widget -
        # GtkProgressBar's own trough/progress CSS nodes fight the
        # border-radius rounding in ways a plain Box sized by hand doesn't.
        fill_width = max(0, int((self._panel_width - 8) * pct / 100))
        self._fill.set_size_request(fill_width, -1)

        if not self.get_visible():
            self.show_all()
        self.set_opacity(1.0)

        if self._hide_timer is not None:
            GLib.source_remove(self._hide_timer)
        self._hide_timer = GLib.timeout_add(TIMEOUT_MS, self._hide)

    def _hide(self):
        self.set_opacity(0.0)
        self._hide_timer = None
        return False


def watch_stdin(osd):
    def _on_line(source, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            return False
        line = source.readline()
        if not line:
            return False
        line = line.strip()
        if line.isdigit():
            osd.show_value(int(line))
        return True

    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, _on_line)


def main():
    osd = VolumeOSD()
    watch_stdin(osd)
    Gtk.main()


if __name__ == "__main__":
    main()
