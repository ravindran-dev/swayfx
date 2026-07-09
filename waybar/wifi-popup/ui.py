import secrets
import socket
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

import config
import animations

BAR_HEIGHT = 34 + 8 + 6  # waybar height + its margin-top + a small macOS-like gap
# Deliberately a fixed anchor, not "under whichever button was clicked":
# Wayland's security model blocks clients from ever querying click/cursor
# position (confirmed - GDK's global pointer query returns 0,0 by design,
# and waybar's on-click exec gets no coordinate env vars either), so a
# popup can't dynamically follow a button's position. This value instead
# targets a fixed, consistent spot near the Network+Bluetooth cluster in
# the bar (measured directly, not guessed) - same anchor every time
# regardless of what else in the bar changes width.
GAP = 300


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
        self._hotspot_setup = False
        self._hotspot_error = None
        self._hotspot_ssid = None
        self._hotspot_password = None
        self._hotspot_password_pending = False
        self._hotspot_editing = False

        self.get_style_context().add_class("wifi-popup")
        self.set_decorated(False)
        self.set_resizable(False)
        self._scan_timer_id = None

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
        # Anchored to all 4 edges - the surface now covers the whole output,
        # not just the panel's own footprint. This used to be a small
        # top-right-anchored surface with click-outside detected by
        # watching sway's own window-focus IPC events, but that mechanism
        # was fundamentally the wrong signal: sway's default
        # focus_follows_mouse means merely moving the cursor onto another
        # window emits a genuine focus event indistinguishable from an
        # actual click there (confirmed live), so the popup closed on mere
        # cursor movement, and separately, this popup's own on-demand
        # keyboard grabs (for the password/hotspot entry fields) generated
        # spurious focus churn that closed it on interactions *inside* it
        # too. A full-screen transparent surface with real click
        # hit-testing (_on_outside_click below) sidesteps focus semantics
        # entirely and only reacts to an actual button press.
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
        # Panel chrome (bg/border/radius) is styled on this box, not the
        # window - see the comment on box.wifi-popup-panel in styles.css.
        # Positioned within the now-full-screen window via alignment +
        # margins (GAP/BAR_HEIGHT) instead of layer-shell surface margins,
        # since the surface itself is no longer sized to the panel.
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

        # Settings pinned OUTSIDE the scroller (macOS keeps "Wi-Fi Settings…"
        # visible at the bottom no matter how long the network list is -
        # previously it scrolled away below 14 networks).
        self._footer = Gtk.ListBox()
        self._footer.set_selection_mode(Gtk.SelectionMode.NONE)
        self._footer.connect("row-activated", self._on_row_activated)
        settings_row = _row([_label("Wi-Fi Settings…")], css_class="wifi-settings-row")
        settings_row._action = ("settings",)
        self._footer.add(settings_row)

        self._build_hotspot_section()
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

    def _build_hotspot_section(self):
        # Same visual language as the Wi-Fi header switch on purpose - the
        # first hotspot design was a plain text row ("Turn On Hotspot") that
        # didn't read as a toggle at all, confirmed confusing in practice.
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sep = Gtk.Box()
        sep.get_style_context().add_class("wifi-separator")
        wrap.pack_start(sep, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row.get_style_context().add_class("wifi-header")
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = _label("Hotspot", css_class="title")
        title_box.pack_start(title, False, False, 0)
        self._hotspot_name_label = _label("", css_class="secondary")
        title_box.pack_start(self._hotspot_name_label, False, False, 0)
        # Selectable so the password can be click-dragged and Ctrl+C'd
        # straight out of the popup - the only place it's ever shown again
        # after setup, since it's masked in the entry field at creation
        # time and NetworkManager doesn't surface it anywhere else in the UI.
        password_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._hotspot_password_label = _label("", css_class="secondary")
        self._hotspot_password_label.set_selectable(True)
        password_row.pack_start(self._hotspot_password_label, False, False, 0)
        self._hotspot_change_btn = Gtk.Button(label="Change")
        self._hotspot_change_btn.get_style_context().add_class("wifi-flat")
        self._hotspot_change_btn.get_style_context().add_class("wifi-hotspot-change")
        self._hotspot_change_btn.connect("clicked", self._on_hotspot_change_clicked)
        self._hotspot_change_btn.set_no_show_all(True)
        password_row.pack_start(self._hotspot_change_btn, False, False, 0)
        password_row.set_no_show_all(True)
        title_box.pack_start(password_row, False, False, 0)
        self._hotspot_password_row = password_row
        title_box.set_hexpand(True)

        self._hotspot_switch = Gtk.Switch()
        self._hotspot_switch.set_valign(Gtk.Align.CENTER)
        self._hotspot_switch_handler = self._hotspot_switch.connect(
            "state-set", self._on_hotspot_switch
        )
        row.pack_start(title_box, True, True, 0)
        row.pack_end(self._hotspot_switch, False, False, 0)
        wrap.pack_start(row, False, False, 0)

        self._hotspot_form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.pack_start(self._hotspot_form_box, False, False, 0)

        self._root.pack_end(wrap, False, False, 0)

    def show_animated(self):
        self.show_all()
        animations.fade_slide_in(self, self._root, BAR_HEIGHT, config.ANIM_SLIDE_PX, config.ANIM_DURATION_MS)
        self._start_periodic_scan()

    def _start_periodic_scan(self):
        # net.request_scan() existed in network.py but nothing ever called
        # it - confirmed live that NM's own background scan cache is nearly
        # empty between user-initiated scans (get_networks() returned just
        # the one connected AP right after `nmcli device wifi list` showed
        # 8 nearby networks in the same instant), so "Other Networks" was
        # usually near-empty or stale, which is why clicking one often did
        # nothing useful - a stale AP record can be missing its security
        # flags too. One scan on open plus a light repeat while the popup
        # stays open keeps the list honest without polling anything else.
        self.net.request_scan()
        self._scan_timer_id = GLib.timeout_add_seconds(10, self._on_scan_tick)

    def _on_scan_tick(self):
        self.net.request_scan()
        return GLib.SOURCE_CONTINUE

    def _stop_periodic_scan(self):
        if self._scan_timer_id is not None:
            GLib.source_remove(self._scan_timer_id)
            self._scan_timer_id = None

    # ---- events -----------------------------------------------------

    def _on_outside_click(self, _widget, event):
        # The window now covers the whole output (see the anchor comment in
        # __init__). This has been broken twice already, in two different
        # ways - both confirmed live with real synthesized Gdk.Events, not
        # guessed:
        #   1st attempt compared event.x/event.y directly against
        #   self._root's allocation. GtkEntry and a few others own their
        #   own GdkWindow, so their event coordinates come back local to
        #   THAT widget, not the toplevel - comparing them against the
        #   toplevel-relative panel allocation was comparing two different
        #   coordinate spaces.
        #   2nd attempt (ancestry walk from Gtk.get_event_widget()) assumed
        #   that function returns the specific widget under the cursor. It
        #   doesn't - it only returns whichever widget owns the event's
        #   GdkWindow via gdk_window_set_user_data(), and confirmed live
        #   that GtkScale, GtkSwitch, GtkLabel and this popup's own root Box
        #   are ALL windowless, sharing the toplevel's single GdkWindow -
        #   so it resolved to the toplevel itself for most clicks, and an
        #   ancestry walk from the toplevel can never reach self._root (a
        #   descendant, not an ancestor). Every click was misread as
        #   outside.
        # The actual fix needs both pieces together: resolve whichever
        # widget really owns the event's window, then translate_coordinates
        # from THAT widget's space into the toplevel's space (a no-op when
        # it's already the toplevel, a real conversion when it's e.g. a
        # ScrolledWindow's internal viewport with its own window/origin),
        # THEN compare against self._root's allocation - now an
        # apples-to-apples comparison regardless of which widget actually
        # owned the window for this particular click.
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
        self._stop_periodic_scan()
        self.destroy()
        if self.on_closed:
            self.on_closed()

    def _on_toggle(self, switch, state):
        self.net.set_enabled(state)
        return False

    def _on_hotspot_switch(self, switch, state):
        if state:
            if self.net.has_saved_hotspot():
                # Repeat use: reactivate the saved profile directly, no form -
                # this is the actual "just flip it like Wi-Fi" behavior asked for.
                self.net.activate_saved_hotspot(self._on_hotspot_activated)
            else:
                # First time: need a name+password before we can turn it on -
                # intercept the switch (return True) so it doesn't visually
                # flip until Start actually succeeds. refresh() (called below)
                # ends up calling self._hotspot_switch.set_active() on this
                # very switch - doing that *synchronously*, still inside this
                # switch's own state-set handler, re-enters GtkSwitch's
                # gesture/animation code while it's mid-transition and
                # reliably killed the process outright (confirmed live: the
                # whole popup silently vanished, no error, no crash dialog -
                # exactly what a hard segfault looks like from the outside).
                # Deferring to the next mainloop iteration via idle_add lets
                # this handler fully return and the switch's internal state
                # settle first, same safe pattern _on_hotspot_activated below
                # already uses.
                self._hotspot_setup = True
                GLib.idle_add(self.refresh)
                return True
        else:
            self.net.stop_hotspot(self._on_hotspot_activated)
        return False

    def _on_hotspot_activated(self, ok, err):
        def _apply():
            if not ok:
                self._hotspot_error = err or "Hotspot action failed"
            self.refresh()
        GLib.idle_add(_apply)

    def _on_hotspot_change_clicked(self, _btn):
        # Reuses the same setup-form UI as first-time creation, but in
        # "editing" mode: prefills the CURRENT password (already fetched by
        # refresh() by the time this button is even shown, see there)
        # instead of generating a fresh random one, and saves via
        # net.update_hotspot() (nmcli connection modify - edits the
        # existing profile in place) rather than net.start_hotspot()
        # (nmcli device wifi hotspot - the first-time creation path).
        self._hotspot_editing = True
        self._hotspot_setup = True
        self.refresh()

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

    def _on_hotspot_password_fetched(self, password):
        self._hotspot_password_pending = False
        if password:
            self._hotspot_password = password
            self.refresh()

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

        hotspot_active = self.net.is_hotspot_active()
        self._hotspot_switch.handler_block(self._hotspot_switch_handler)
        self._hotspot_switch.set_active(hotspot_active)
        self._hotspot_switch.handler_unblock(self._hotspot_switch_handler)

        hotspot_name = self._hotspot_ssid or self.net.get_saved_hotspot_ssid()
        if hotspot_active and hotspot_name:
            self._hotspot_name_label.set_text(f"Sharing internet as “{hotspot_name}”")
        elif hotspot_name:
            self._hotspot_name_label.set_text(hotspot_name)
        else:
            self._hotspot_name_label.set_text("Not configured")

        if hotspot_name and self._hotspot_password:
            self._hotspot_password_label.set_text(f"Password: {self._hotspot_password}")
            self._hotspot_password_row.show()
            self._hotspot_change_btn.show()
        elif hotspot_name and self.net.has_saved_hotspot():
            # Password isn't known in this process yet (fresh popup, or a
            # profile set up in an earlier session) - fetch it once from
            # NetworkManager's own stored secret rather than leaving it
            # permanently unreadable. Guarded by the pending flag since
            # refresh() fires often (every net.changed signal) and would
            # otherwise spawn a fresh nmcli lookup on every single one.
            self._hotspot_password_label.set_text("Password: …")
            self._hotspot_password_row.show()
            # "Change" needs the current password in hand to prefill the
            # edit form (see _on_hotspot_change_clicked) - hide it until
            # the fetch above actually lands rather than letting a click
            # during that brief window open an edit form with an empty field.
            self._hotspot_change_btn.hide()
            if not self._hotspot_password_pending:
                self._hotspot_password_pending = True
                self.net.get_saved_hotspot_password(self._on_hotspot_password_fetched)
        else:
            self._hotspot_password_row.hide()

        for child in self._hotspot_form_box.get_children():
            self._hotspot_form_box.remove(child)
        if self._hotspot_setup:
            self._build_hotspot_setup_view()

        if self._password_ssid:
            self._build_password_view(self._password_ssid)
            self._list.show_all()
            return

        if hotspot_active:
            self._list.add(self._section_label("Hotspot Active"))
            self._list.add(_row([_label(
                "Wi-Fi scanning is paused while the hotspot is on", "secondary")]))
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

    # ---- hotspot -----------------------------------------------------

    def _build_hotspot_setup_view(self):
        # Lives in self._hotspot_form_box (a plain Box right under the
        # switch row), not self._list - this is a one-time setup step, not
        # part of the scrollable network list.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(4)
        box.set_margin_bottom(10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.pack_start(_label("Hotspot name"), False, False, 0)

        ssid_entry = Gtk.Entry()
        ssid_entry.set_text(self.net.get_saved_hotspot_ssid() or f"{socket.gethostname()}-hotspot")
        ssid_entry.get_style_context().add_class("wifi-password")
        box.pack_start(ssid_entry, False, False, 0)

        box.pack_start(_label("Password (min 8 characters)"), False, False, 0)
        pass_entry = Gtk.Entry()
        pass_entry.set_visibility(False)
        # Editing an existing hotspot prefills its current password (known
        # by now - the Change button that got us here is only ever shown
        # once refresh() has already fetched it, see there) so the user can
        # see what it currently is, not just overwrite it blind. First-time
        # setup has no current password yet, so it still gets a fresh
        # random one, same as before.
        pass_entry.set_text(
            self._hotspot_password if self._hotspot_editing and self._hotspot_password
            else secrets.token_urlsafe(9)
        )
        pass_entry.get_style_context().add_class("wifi-password")
        pass_entry.set_hexpand(True)
        pass_entry.connect("activate", lambda _e: self._submit_hotspot_form(
            ssid_entry.get_text(), pass_entry.get_text()))
        # The generated password is masked by default same as any password
        # field, but this one is also the ONLY place it's ever shown before
        # being handed off to other devices to type in manually - confirmed
        # this bit the user directly (hotspot connected fine, but the
        # random password was never actually seen so there was no way to
        # give it to another device). A visibility toggle here fixes the
        # problem at its source, on top of surfacing the saved password
        # again later in the header (see refresh()).
        pass_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        pass_row.pack_start(pass_entry, True, True, 0)
        reveal = Gtk.ToggleButton(label="Show")
        reveal.get_style_context().add_class("wifi-flat")
        reveal.connect("toggled", lambda b: (
            pass_entry.set_visibility(b.get_active()),
            b.set_label("Hide" if b.get_active() else "Show"),
        ))
        pass_row.pack_start(reveal, False, False, 0)
        box.pack_start(pass_row, False, False, 0)

        self._hotspot_error_label = _label(self._hotspot_error or "", css_class="secondary")
        self._hotspot_error = None
        box.pack_start(self._hotspot_error_label, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cancel = Gtk.Button(label="Cancel")
        cancel.get_style_context().add_class("wifi-flat")
        cancel.connect("clicked", lambda _b: (
            setattr(self, "_hotspot_setup", False),
            setattr(self, "_hotspot_editing", False),
            self.refresh(),
        ))
        submit = Gtk.Button(label="Save" if self._hotspot_editing else "Start")
        submit.get_style_context().add_class("wifi-flat")
        submit.connect("clicked", lambda _b: self._submit_hotspot_form(
            ssid_entry.get_text(), pass_entry.get_text()))
        btn_row.pack_end(submit, False, False, 0)
        btn_row.pack_end(cancel, False, False, 0)
        box.pack_start(btn_row, False, False, 0)

        self._hotspot_form_box.pack_start(box, False, False, 0)
        self._hotspot_form_box.show_all()
        GLib.idle_add(ssid_entry.grab_focus)

    def _submit_hotspot_form(self, ssid, password):
        if self._hotspot_editing:
            self._save_hotspot_edit(ssid, password)
        else:
            self._start_hotspot(ssid, password)

    def _save_hotspot_edit(self, ssid, password):
        if len(password) < 8:
            self._hotspot_error = "Password must be at least 8 characters"
            self.refresh()
            return

        def _done(ok, err):
            def _apply():
                if ok:
                    self._hotspot_ssid = ssid
                    self._hotspot_password = password
                    self._hotspot_setup = False
                    self._hotspot_editing = False
                else:
                    self._hotspot_error = err or "Couldn't update hotspot"
                self.refresh()
            GLib.idle_add(_apply)

        self.net.update_hotspot(ssid, password, _done)

    def _start_hotspot(self, ssid, password):
        if len(password) < 8:
            self._hotspot_error = "Password must be at least 8 characters"
            self.refresh()
            return

        def _done(ok, err):
            def _apply():
                if ok:
                    self._hotspot_ssid = ssid
                    self._hotspot_password = password
                    self._hotspot_setup = False
                else:
                    self._hotspot_error = err or "Couldn't start hotspot"
                self.refresh()
            GLib.idle_add(_apply)

        self.net.start_hotspot(ssid, password, _done)
