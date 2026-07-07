import json
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

import config
import animations

BAR_HEIGHT = 34 + 8 + 6  # waybar height + its margin-top + a small macOS-like gap
GAP = 10


def _row(children, css_class="wifi-row"):
    row = Gtk.ListBoxRow()
    row.get_style_context().add_class(css_class)
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    box.set_margin_top(6)
    box.set_margin_bottom(6)
    for child in children:
        # Read each label's own hexpand (set via _label(..., hexpand=True))
        # rather than hardcoding expand=False - Gtk.Box.pack_start's expand
        # arg doesn't auto-honor widget-level hexpand, so this has to be
        # explicit or the SSID column never grows to push icons/% right.
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


class WifiPopup(Gtk.Window):
    def __init__(self, net, on_closed=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.net = net
        self.on_closed = on_closed
        self._password_ssid = None

        self.get_style_context().add_class("wifi-popup")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(config.POPUP_MIN_WIDTH, -1)
        self._shown_at = None
        # A newly-mapped layer-shell surface reliably fires focus-in then an
        # immediate spurious focus-out on this compositor (confirmed via
        # signal tracing). Harmless since real close-on-click-outside doesn't
        # depend on this signal at all (see _start_sway_focus_watch) - this
        # grace flag just stops that one spurious event from self-closing.
        self._focus_grace_us = 400_000
        self._sway_watch_proc = None
        self._sway_watch_tag = None

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        # Namespace ties this surface to the swayfx rule in sway/config:
        #   layer_effects "wifi-popup" blur enable; shadows enable; corner_radius 14
        # which is what gives the panel real compositor blur + rounded clip -
        # GTK CSS alone can't blur what's behind a layer surface.
        GtkLayerShell.set_namespace(self, "wifi-popup")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, GAP)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, BAR_HEIGHT)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        # focus-out-event is unreliable for this: confirmed via signal tracing
        # that it fires once spuriously right after mapping, then never again
        # even when a real window elsewhere genuinely takes focus - GTK just
        # doesn't get a second focus-leave for an ON_DEMAND layer-shell
        # surface on this compositor. Real click-outside-to-close instead
        # watches sway's own IPC window-focus events (_start_sway_focus_watch),
        # the exact mechanism already proven to work for the bash/wofi
        # network popup earlier this session.
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("key-press-event", self._on_key_press)
        self.connect("realize", self._load_css)

        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # Panel chrome (bg/border/radius) is styled on this box, not the
        # window - see the comment on box.wifi-popup-panel in styles.css.
        self._root.get_style_context().add_class("wifi-popup-panel")
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

        # Settings pinned OUTSIDE the scroller (macOS keeps "Wi-Fi Settings…"
        # visible at the bottom no matter how long the network list is -
        # previously it scrolled away below 14 networks).
        self._footer = Gtk.ListBox()
        self._footer.set_selection_mode(Gtk.SelectionMode.NONE)
        self._footer.connect("row-activated", self._on_row_activated)
        self._footer.add(self._separator())
        settings_row = _row([_label("Wi-Fi Settings…")], css_class="wifi-settings-row")
        settings_row._action = ("settings",)
        self._footer.add(settings_row)
        self._root.pack_end(self._footer, False, False, 0)

        net.connect("changed", lambda *_: GLib.idle_add(self.refresh))
        self.refresh()

    # ---- chrome -----------------------------------------------------

    def _load_css(self, *_a):
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(config.STYLE_CSS_PATH)
        except GLib.Error as e:
            # A bad rule anywhere in the stylesheet raises here rather than
            # just being skipped - don't let a CSS typo take down the popup.
            print(f"styles.css failed to load: {e}", file=sys.stderr)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.get_style_context().add_class("wifi-header")
        title = _label("Wi-Fi", css_class="title", hexpand=True)
        self._switch = Gtk.Switch()
        self._switch.set_valign(Gtk.Align.CENTER)
        self._switch_handler = self._switch.connect("state-set", self._on_toggle)
        header.pack_start(title, True, True, 0)
        header.pack_end(self._switch, False, False, 0)
        self._root.pack_start(header, False, False, 0)

    def show_animated(self):
        self.show_all()
        self._shown_at = GLib.get_monotonic_time()
        animations.fade_slide_in(self, BAR_HEIGHT, config.ANIM_SLIDE_PX, config.ANIM_DURATION_MS)
        self._start_sway_focus_watch()

    # ---- events -----------------------------------------------------

    def _on_focus_out(self, *_a):
        if self._shown_at is not None:
            elapsed = GLib.get_monotonic_time() - self._shown_at
            if elapsed < self._focus_grace_us:
                return False
        self.close_popup()
        return False

    def _start_sway_focus_watch(self):
        """Any regular window gaining focus while we're open means the user
        clicked away - close. Popen (not subprocess.run) so nothing here
        blocks waiting on the child; GLib.io_add_watch reads lines only when
        the pipe actually has data, same async/no-polling philosophy as
        network.py's D-Bus signals."""
        try:
            self._sway_watch_proc = subprocess.Popen(
                ["swaymsg", "-t", "subscribe", "-m", '["window"]'],
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
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return True
            if event.get("change") == "focus":
                if self._shown_at is not None and \
                        GLib.get_monotonic_time() - self._shown_at >= self._focus_grace_us:
                    # Null the tag first: we're about to return False, which
                    # tells GLib to remove this same source itself - calling
                    # GLib.source_remove on it too (via close_popup ->
                    # _stop_sway_focus_watch) would double-remove it.
                    self._sway_watch_tag = None
                    self.close_popup()
                    return False
            return True

        self._sway_watch_tag = GLib.io_add_watch(
            self._sway_watch_proc.stdout, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, _on_line
        )

    def _stop_sway_focus_watch(self):
        if self._sway_watch_tag is not None:
            GLib.source_remove(self._sway_watch_tag)
            self._sway_watch_tag = None
        if self._sway_watch_proc is not None:
            self._sway_watch_proc.terminate()
            self._sway_watch_proc = None

    def _on_key_press(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_popup()
        return False

    def close_popup(self):
        self._stop_sway_focus_watch()
        self.destroy()
        if self.on_closed:
            self.on_closed()

    def _on_toggle(self, switch, state):
        self.net.set_enabled(state)
        return False

    def _on_row_activated(self, _list, row):
        action = getattr(row, "_action", None)
        if action is None:
            return
        kind = action[0]
        if kind == "connect":
            self._start_connect(action[1], action[2])
        elif kind == "disconnect":
            self.net.disconnect()
        elif kind == "settings":
            GLib.spawn_async_with_pipes(
                None, ["nm-connection-editor"], None,
                GLib.SpawnFlags.SEARCH_PATH, None,
            )
            self.close_popup()

    # ---- content ------------------------------------------------------

    def refresh(self):
        for child in self._list.get_children():
            self._list.remove(child)

        self._switch.handler_block(self._switch_handler)
        self._switch.set_active(self.net.is_enabled())
        self._switch.handler_unblock(self._switch_handler)

        if not self.net.has_wifi_device():
            self._list.add(_row([_label("No Wi-Fi device found", "secondary")]))
            self._list.show_all()
            return

        if self._password_ssid:
            self._build_password_view(self._password_ssid)
            self._list.show_all()
            return

        if not self.net.is_enabled():
            row = _row([_label("Turn Wi-Fi on to see networks", "secondary")])
            self._list.add(row)
            self._list.show_all()
            return

        nets = self.net.get_networks()
        connected = [n for n in nets if n["in_use"]]
        known = [n for n in nets if n["saved"] and not n["in_use"]]
        other = [n for n in nets if not n["saved"] and not n["in_use"]]

        if connected or known:
            self._list.add(self._section_label("Known Network" if len(known) <= 1 else "Known Networks"))
            for n in connected:
                self._list.add(self._network_row(n, connected=True))
            for n in known:
                self._list.add(self._network_row(n, connected=False))
            self._list.add(self._separator())

        self._list.add(self._section_label("Other Networks"))
        if other:
            for n in other:
                self._list.add(self._network_row(n, connected=False))
        else:
            self._list.add(_row([_label("No other networks in range", "secondary")]))

        self._list.show_all()

    def _section_label(self, text):
        # GTK3 CSS has no text-transform (that's a browser-CSS property, not
        # part of GTK's supported subset - confirmed by a hard GError when
        # it was in styles.css) - so the uppercasing happens here instead.
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

    def _network_row(self, n, connected):
        # macOS row anatomy: [✓] SSID ........... [lock] [signal bars]
        # - lock + signal sit at the RIGHT edge, no numeric percentage
        #   (strength number lives in the tooltip instead)
        ssid_class = "ssid connected" if connected else "ssid"
        ssid = _label(n["ssid"], css_class=ssid_class, hexpand=True)
        parts = []
        if connected:
            parts.append(_label(config.ICON_CHECK, css_class="check"))
        parts.append(ssid)
        if n["security"]:
            parts.append(_label(config.ICON_LOCK, css_class="secondary"))
        parts.append(_label(config.signal_icon(n["strength"]), css_class="secondary"))

        row = _row(parts)
        row.set_tooltip_text(f'{n["strength"]}% · {n["security"] or "Open"}')
        if connected:
            row._action = ("disconnect",)
        else:
            row._action = ("connect", n["ssid"], n["saved"] or not n["security"])

        # Right-click a saved network to forget it (spec requirement) - not
        # offered for "Other Networks" rows since those have no saved
        # connection profile to delete in the first place.
        if n["saved"]:
            row.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            row.connect("button-press-event", self._on_row_button_press, n["ssid"])
        return row

    def _on_row_button_press(self, _row, event, ssid):
        if event.button == 3:  # right click
            self.net.forget(ssid)
            return True
        return False

    def _build_password_view(self, ssid):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.pack_start(_label(f"Enter password for “{ssid}”"), False, False, 0)

        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.get_style_context().add_class("wifi-password")
        entry.connect("activate", lambda _e: self._start_connect(ssid, entry.get_text(), force=True))
        box.pack_start(entry, False, False, 0)

        self._password_error = _label("", css_class="secondary")
        box.pack_start(self._password_error, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cancel = Gtk.Button(label="Cancel")
        cancel.get_style_context().add_class("wifi-flat")
        cancel.connect("clicked", lambda _b: (setattr(self, "_password_ssid", None), self.refresh()))
        connect = Gtk.Button(label="Connect")
        connect.get_style_context().add_class("wifi-flat")
        connect.connect("clicked", lambda _b: self._start_connect(ssid, entry.get_text(), force=True))
        btn_row.pack_end(connect, False, False, 0)
        btn_row.pack_end(cancel, False, False, 0)
        box.pack_start(btn_row, False, False, 0)

        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.add(box)
        self._list.add(row)
        GLib.idle_add(entry.grab_focus)

    def _start_connect(self, ssid, secondarg, force=False):
        if not force and isinstance(secondarg, bool) and not secondarg:
            # secondarg False here means "not saved and secured" -> need a password
            self._password_ssid = ssid
            self.refresh()
            return

        password = secondarg if isinstance(secondarg, str) else None

        def _done(ok, err):
            def _apply():
                if ok:
                    self._password_ssid = None
                    self.close_popup()
                else:
                    self._password_error.set_text(err or "Couldn't connect")
            GLib.idle_add(_apply)

        self.net.connect_to(ssid, password, _done)
