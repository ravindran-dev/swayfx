import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

import config
import animations

BAR_HEIGHT = 34 + 8 + 6  # waybar height + its margin-top + a small macOS-like gap
# Same fixed-anchor reasoning as wifi-popup/ui.py: Wayland blocks querying
# click/cursor position, so this targets a fixed spot instead of tracking
# the actual clicked button. Measured against the pulseaudio module's pill
# specifically (it sits well left of the Network+Bluetooth cluster that
# GAP=300 in the other two popups was calibrated for - confirmed via pixel
# crops of the live bar: pulseaudio's pill right edge sits around x=1275
# on this 1920px output, vs. network's around x=1470+).
GAP = 460


def _label(text, css_class=None, xalign=0.0, hexpand=False):
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(xalign)
    if css_class:
        lbl.get_style_context().add_class(css_class)
    if hexpand:
        lbl.set_hexpand(True)
    return lbl


class VolumePopup(Gtk.Window):
    def __init__(self, audio, on_closed=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.audio = audio
        self.on_closed = on_closed

        # Reuses the Wi-Fi popup's CSS classes verbatim - same stylesheet
        # file, see config.py's note on why.
        self.get_style_context().add_class("wifi-popup")
        self.set_decorated(False)
        self.set_resizable(False)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        # Reuses the Wi-Fi popup's namespace on purpose: the swayfx rule
        #   layer_effects "wifi-popup" blur enable; shadows enable; corner_radius 14
        # then applies to this surface too, with no separate sway/config
        # entry needed for a third namespace.
        GtkLayerShell.set_namespace(self, "wifi-popup")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        # Full-screen anchor + real click hit-testing, not sway's
        # window-focus IPC - see wifi-popup/ui.py for why that mechanism
        # closed the popup on mere cursor movement and on its own internal
        # keyboard/gesture grabs, not just genuine outside clicks.
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self._on_outside_click)
        self.connect("key-press-event", self._on_key_press)
        self.connect("realize", self._load_css)

        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._root.get_style_context().add_class("wifi-popup-panel")
        self._root.set_halign(Gtk.Align.END)
        self._root.set_valign(Gtk.Align.START)
        self._root.set_margin_end(GAP)
        self._root.set_size_request(config.POPUP_MIN_WIDTH, -1)
        self.add(self._root)

        self._build_content()

        self._suppress_scale_signal = False
        audio.connect("changed", lambda *_: GLib.idle_add(self.refresh))
        self.refresh()

    # ---- chrome -----------------------------------------------------

    def _load_css(self, *_a):
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(config.STYLE_CSS_PATH)
        except GLib.Error as e:
            print(f"styles.css failed to load: {e}", file=sys.stderr)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_content(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.get_style_context().add_class("wifi-header")
        title = _label("Volume", css_class="title", hexpand=True)
        self._pct_label = _label("", css_class="secondary")
        header.pack_start(title, True, True, 0)
        header.pack_end(self._pct_label, False, False, 0)
        self._root.pack_start(header, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_margin_start(16)
        row.set_margin_end(16)
        row.set_margin_bottom(16)
        row.set_margin_top(2)

        self._mute_btn = Gtk.Button()
        self._mute_btn.get_style_context().add_class("wifi-flat")
        self._mute_btn.get_style_context().add_class("volume-mute-btn")
        self._mute_btn.connect("clicked", lambda _b: self.audio.toggle_mute())
        row.pack_start(self._mute_btn, False, False, 0)

        self._scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self._scale.set_draw_value(False)
        self._scale.set_hexpand(True)
        self._scale.get_style_context().add_class("volume-scale")
        self._scale_handler = self._scale.connect("value-changed", self._on_scale_changed)
        row.pack_start(self._scale, True, True, 0)

        self._root.pack_start(row, False, False, 0)

    def show_animated(self):
        self.show_all()
        animations.fade_slide_in(self, self._root, BAR_HEIGHT, config.ANIM_SLIDE_PX, config.ANIM_DURATION_MS)

    # ---- events -----------------------------------------------------

    def _on_outside_click(self, _widget, event):
        # Gtk.get_event_widget() only tells you which widget owns the
        # event's *GdkWindow* - for any windowless widget (confirmed live:
        # Gtk.Scale, Gtk.Switch, Gtk.Label, and this popup's own root Box
        # are ALL windowless, sharing the toplevel's single GdkWindow), that
        # resolves to the toplevel itself, not the specific widget visually
        # under the cursor. An ancestry walk from that resolved widget can
        # then never reach self._root (a descendant, not an ancestor) -
        # every click, including ones on the volume slider, was wrongly
        # read as outside. translate_coordinates converts the event's
        # coordinates (relative to whichever widget actually owns the
        # window - the toplevel for most clicks, but e.g. a ScrolledWindow's
        # internal viewport has its own window with a different origin) into
        # the toplevel's coordinate space, then a real bounds check against
        # self._root's allocation works correctly regardless of which case
        # applied for this particular click.
        target = Gtk.get_event_widget(event)
        if target is None:
            return False
        x, y = target.translate_coordinates(self, event.x, event.y)
        if x is None:
            return False
        alloc = self._root.get_allocation()
        inside = (alloc.x <= x < alloc.x + alloc.width
                  and alloc.y <= y < alloc.y + alloc.height)
        if not inside:
            self.close_popup()
        return False

    def _on_key_press(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_popup()
        return False

    def close_popup(self):
        self.audio.stop()
        self.destroy()
        if self.on_closed:
            self.on_closed()

    def _on_scale_changed(self, scale):
        if self._suppress_scale_signal:
            return
        # Dragging the slider implies "I want sound at this level" - auto-
        # unmuting matches every mainstream OS's volume popover instead of
        # leaving the user to separately notice and clear mute afterward.
        if self.audio.is_muted():
            self.audio.set_muted(False)
        self.audio.set_volume(scale.get_value())

    # ---- content ------------------------------------------------------

    def refresh(self):
        pct = self.audio.get_volume()
        muted = self.audio.is_muted()

        self._pct_label.set_text("Muted" if muted else f"{pct}%")

        # Mute is a separate flag from the volume level in pactl - the
        # level itself is preserved underneath while muted, so the slider
        # keeps showing where it really is (dimmed via CSS) rather than
        # snapping to 0, which would look like the level itself got reset.
        self._suppress_scale_signal = True
        self._scale.set_value(pct)
        self._suppress_scale_signal = False

        icon = config.volume_icon(pct, muted)
        self._mute_btn.set_label(icon)
        mute_ctx = self._mute_btn.get_style_context()
        scale_ctx = self._scale.get_style_context()
        if muted:
            mute_ctx.add_class("muted")
            scale_ctx.add_class("muted")
        else:
            mute_ctx.remove_class("muted")
            scale_ctx.remove_class("muted")
