import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

import config
import animations

BAR_HEIGHT = 34 + 8 + 6  # waybar height + its margin-top + a small macOS-like gap
# Same fixed-anchor reasoning as wifi-popup/ui.py - see there for why this
# can't track the actual clicked button on Wayland, and why 300 specifically
# (measured position of the Network+Bluetooth cluster in the bar).
GAP = 300


def _row(children, css_class="wifi-row"):
    row = Gtk.ListBoxRow()
    row.get_style_context().add_class(css_class)
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    box.set_margin_top(6)
    box.set_margin_bottom(6)
    for child in children:
        expand = child.get_hexpand()
        box.pack_start(child, expand, expand, 0)
    row.add(box)
    return row


def _label(text, css_class=None, xalign=0.0, hexpand=False):
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(xalign)
    if css_class:
        lbl.get_style_context().add_class(css_class)
    if hexpand:
        lbl.set_hexpand(True)
    return lbl


class BluetoothPopup(Gtk.Window):
    def __init__(self, bt, on_closed=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.bt = bt
        self.on_closed = on_closed
        self._scanning = False

        # Reuses the Wi-Fi popup's CSS classes verbatim ("wifi-popup" etc.) -
        # same stylesheet file, see config.py's note on why.
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
        # entry needed for a second namespace.
        GtkLayerShell.set_namespace(self, "wifi-popup")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        # See wifi-popup/ui.py for the full reasoning: anchored to all 4
        # edges so the surface covers the whole output, with real click
        # hit-testing (_on_outside_click) instead of watching sway's
        # window-focus IPC - that mechanism closed the popup on mere cursor
        # movement (focus_follows_mouse) and on its own internal keyboard
        # grabs, not just genuine outside clicks.
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

        self._build_header()
        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroller.set_max_content_height(config.POPUP_MAX_HEIGHT)
        self._scroller.set_propagate_natural_height(True)
        self._root.pack_start(self._scroller, True, True, 0)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.connect("row-activated", self._on_row_activated)
        self._scroller.add(self._list)

        # "Scan for Devices" pinned outside the scroller, same reasoning as
        # "Wi-Fi Settings…" in the Wi-Fi popup - always reachable regardless
        # of how long the device list gets.
        self._footer = Gtk.ListBox()
        self._footer.set_selection_mode(Gtk.SelectionMode.NONE)
        self._footer.connect("row-activated", self._on_row_activated)
        self._footer.add(self._separator())
        self._scan_row = _row([_label("Scan for Devices")], css_class="wifi-settings-row")
        self._scan_row._action = ("scan",)
        self._footer.add(self._scan_row)
        self._root.pack_end(self._footer, False, False, 0)

        bt.connect("changed", lambda *_: GLib.idle_add(self.refresh))
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

    def _build_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.get_style_context().add_class("wifi-header")
        title = _label("Bluetooth", css_class="title", hexpand=True)
        self._switch = Gtk.Switch()
        self._switch.set_valign(Gtk.Align.CENTER)
        self._switch_handler = self._switch.connect("state-set", self._on_toggle)
        header.pack_start(title, True, True, 0)
        header.pack_end(self._switch, False, False, 0)
        self._root.pack_start(header, False, False, 0)

    def show_animated(self):
        self.show_all()
        animations.fade_slide_in(self, self._root, BAR_HEIGHT, config.ANIM_SLIDE_PX, config.ANIM_DURATION_MS)

    # ---- events (identical to wifi-popup/ui.py - see there for why) -----

    def _on_outside_click(self, _widget, event):
        # See the matching comment in wifi-popup/ui.py for the full story -
        # this went through two broken attempts (raw coordinate comparison,
        # then an ancestry walk from Gtk.get_event_widget()) before landing
        # on translate_coordinates as the piece that was actually missing:
        # get_event_widget() only resolves to whichever widget owns the
        # event's GdkWindow (the toplevel itself, for most windowless
        # widgets like GtkScale/GtkSwitch/GtkLabel - confirmed live), not
        # the specific widget under the cursor, so its coordinates need
        # translating into the toplevel's space before they mean anything
        # next to self._root's allocation.
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
        if self._scanning:
            self.bt.stop_discovery()
        self.destroy()
        if self.on_closed:
            self.on_closed()

    def _on_toggle(self, switch, state):
        self.bt.set_enabled(state)
        return False

    def _on_row_activated(self, _list, row):
        action = getattr(row, "_action", None)
        if action is None:
            return
        kind = action[0]
        if kind == "connect":
            self.bt.connect_device(action[1], self._on_action_done)
        elif kind == "disconnect":
            self.bt.disconnect_device(action[1], self._on_action_done)
        elif kind == "pair":
            self.bt.pair_device(action[1], self._on_action_done)
        elif kind == "scan":
            self._toggle_scan()

    def _on_action_done(self, ok, err):
        def _apply():
            if not ok:
                self._show_error(err or "Bluetooth action failed")
        GLib.idle_add(_apply)

    def _show_error(self, text):
        self._error_text = text
        self.refresh()

    def _toggle_scan(self):
        if self._scanning:
            self.bt.stop_discovery()
            self._scanning = False
        else:
            self.bt.start_discovery()
            self._scanning = True
        self.refresh()

    # ---- content ------------------------------------------------------

    def refresh(self):
        for child in self._list.get_children():
            self._list.remove(child)

        self._switch.handler_block(self._switch_handler)
        self._switch.set_active(self.bt.is_enabled())
        self._switch.handler_unblock(self._switch_handler)

        # _row() wraps its one child label in a Box inside the ListBoxRow -
        # get_child() is that Box, get_children()[0] is the label itself.
        scan_label = self._scan_row.get_child().get_children()[0]
        scan_label.set_text("Scanning…" if self._scanning else "Scan for Devices")

        if not self.bt.has_adapter():
            self._list.add(_row([_label("No Bluetooth adapter found", "secondary")]))
            self._list.show_all()
            return

        if not self.bt.is_enabled():
            self._list.add(_row([_label("Turn Bluetooth on to see devices", "secondary")]))
            self._list.show_all()
            return

        devices = self.bt.get_devices()
        paired = [d for d in devices if d["paired"]]
        other = [d for d in devices if not d["paired"]]

        if hasattr(self, "_error_text") and self._error_text:
            err_row = _row([_label(self._error_text, "secondary")])
            self._list.add(err_row)
            self._error_text = None

        if paired:
            self._list.add(self._section_label("Paired Devices" if len(paired) > 1 else "Paired Device"))
            for d in paired:
                self._list.add(self._device_row(d))
            self._list.add(self._separator())

        self._list.add(self._section_label("Other Devices"))
        if other:
            for d in other:
                self._list.add(self._device_row(d))
        else:
            msg = "Scanning for devices…" if self._scanning else "No other devices found"
            self._list.add(_row([_label(msg, "secondary")]))

        self._list.show_all()

    def _section_label(self, text):
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.add(_label(text.upper(), css_class="wifi-section-label"))
        return row

    def _separator(self):
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        sep = Gtk.Box()
        sep.get_style_context().add_class("wifi-separator")
        row.add(sep)
        return row

    def _device_row(self, d):
        name_class = "ssid connected" if d["connected"] else "ssid"
        name = _label(d["name"], css_class=name_class, hexpand=True)
        parts = []
        if d["connected"]:
            parts.append(_label(config.ICON_CHECK, css_class="check"))
        parts.append(name)
        icon = config.ICON_BT_CONNECTED if d["connected"] else config.ICON_BT_ON
        parts.append(_label(icon, css_class="secondary"))

        row = _row(parts)
        row.set_tooltip_text(d["address"])
        if d["connected"]:
            row._action = ("disconnect", d["path"])
        elif d["paired"]:
            row._action = ("connect", d["path"])
        else:
            row._action = ("pair", d["path"])

        # Right-click a paired device to forget it - same UX as the Wi-Fi
        # popup's right-click-to-forget on known networks.
        if d["paired"]:
            row.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            row.connect("button-press-event", self._on_row_button_press, d["path"])
        return row

    def _on_row_button_press(self, _row, event, path):
        if event.button == 3:  # right click
            self.bt.forget_device(path, self._on_action_done)
            return True
        return False
