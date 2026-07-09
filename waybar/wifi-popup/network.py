"""
NetworkManager access via libnm's GObject introspection binding.

Everything here is signal-driven: NM.Client and NM.DeviceWifi emit GObject
signals over the same GLib main loop Gtk.main() already pumps, so there is
no polling anywhere in this module - device/AP/connection changes reach the
UI the moment NetworkManager's own D-Bus signals fire.
"""
import subprocess
import threading

import gi

gi.require_version("NM", "1.0")
from gi.repository import NM, GLib, GObject

HOTSPOT_CON_NAME = "Hotspot"


def _ssid_to_str(ap):
    ssid = ap.get_ssid()
    if ssid is None:
        return ""
    return NM.utils_ssid_to_utf8(ssid.get_data())


# These GI enum names start with a digit ("80211ApFlags"), which isn't a
# legal Python attribute-access token - getattr() is the only way to reach them.
_ApFlags = getattr(NM, "80211ApFlags")
_ApSecurityFlags = getattr(NM, "80211ApSecurityFlags")


def _security_label(ap):
    wpa = ap.get_wpa_flags()
    rsn = ap.get_rsn_flags()
    if not wpa and not rsn:
        flags = ap.get_flags()
        if flags & _ApFlags.PRIVACY:
            return "WEP"
        return ""
    if rsn & _ApSecurityFlags.KEY_MGMT_SAE:
        return "WPA3"
    if rsn:
        return "WPA2"
    return "WPA"


class Network(GObject.Object):
    """Emits 'changed' whenever anything the popup cares about changes."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.client = NM.Client.new(None)
        self._wifi_dev = None
        for dev in self.client.get_devices():
            if dev.get_device_type() == NM.DeviceType.WIFI:
                self._wifi_dev = dev
                break

        self.client.connect("notify::wireless-enabled", self._emit)
        self.client.connect("notify::active-connections", self._emit)
        self.client.connect("connection-added", self._emit)
        self.client.connect("connection-removed", self._emit)
        if self._wifi_dev:
            self._wifi_dev.connect("access-point-added", self._emit)
            self._wifi_dev.connect("access-point-removed", self._emit)
            self._wifi_dev.connect("notify::active-access-point", self._emit)
            self._wifi_dev.connect("state-changed", self._emit)

    def _emit(self, *_a):
        self.emit("changed")

    # ---- state -----------------------------------------------------

    def has_wifi_device(self):
        return self._wifi_dev is not None

    def is_enabled(self):
        return bool(self.client.wireless_get_enabled())

    def set_enabled(self, enabled):
        self.client.wireless_set_enabled(enabled)

    def request_scan(self):
        if not self._wifi_dev:
            return
        try:
            self._wifi_dev.request_scan_async(None, lambda *_: None)
        except Exception:
            pass

    def _active_ap(self):
        if not self._wifi_dev:
            return None
        return self._wifi_dev.get_active_access_point()

    def active_ssid(self):
        ap = self._active_ap()
        return _ssid_to_str(ap) if ap else None

    def active_ip4(self):
        if not self._wifi_dev:
            return None
        cfg = self._wifi_dev.get_ip4_config()
        if not cfg:
            return None
        addrs = cfg.get_addresses()
        if not addrs:
            return None
        return addrs[0].get_address()

    def _saved_ssids(self):
        names = set()
        for c in self.client.get_connections():
            s = c.get_setting_wireless()
            if s:
                ssid = s.get_ssid()
                if ssid:
                    names.add(NM.utils_ssid_to_utf8(ssid.get_data()))
        return names

    def get_networks(self):
        """Returns a de-duplicated, signal-sorted list of nearby networks."""
        if not self._wifi_dev:
            return []
        saved = self._saved_ssids()
        active_ssid = self.active_ssid()
        seen = {}
        for ap in self._wifi_dev.get_access_points():
            ssid = _ssid_to_str(ap)
            if not ssid:
                continue
            strength = ap.get_strength()
            existing = seen.get(ssid)
            if existing and existing["strength"] >= strength:
                continue
            seen[ssid] = {
                "ssid": ssid,
                "strength": strength,
                "security": _security_label(ap),
                "in_use": ssid == active_ssid,
                "saved": ssid in saved,
            }
        nets = list(seen.values())
        nets.sort(key=lambda n: (-n["in_use"], -n["strength"]))
        return nets

    # ---- actions -----------------------------------------------------

    def connect_to(self, ssid, password, on_done):
        """on_done(ok: bool, error: str|None)"""
        saved = ssid in self._saved_ssids()
        if saved:
            conn = None
            for c in self.client.get_connections():
                s = c.get_setting_wireless()
                if s and s.get_ssid() and NM.utils_ssid_to_utf8(s.get_ssid().get_data()) == ssid:
                    conn = c
                    break

            def _cb(client, res, _u=None):
                try:
                    client.activate_connection_finish(res)
                    on_done(True, None)
                except GLib.Error as e:
                    on_done(False, e.message)

            self.client.activate_connection_async(conn, self._wifi_dev, None, None, _cb)
            return

        ap = None
        for a in self._wifi_dev.get_access_points():
            if _ssid_to_str(a) == ssid:
                ap = a
                break

        conn = NM.SimpleConnection.new()
        s_con = NM.SettingConnection.new()
        s_con.set_property(NM.SETTING_CONNECTION_ID, ssid)
        s_con.set_property(NM.SETTING_CONNECTION_TYPE, "802-11-wireless")
        conn.add_setting(s_con)

        s_wifi = NM.SettingWireless.new()
        s_wifi.set_property(NM.SETTING_WIRELESS_SSID, GLib.Bytes.new(ssid.encode("utf-8")))
        conn.add_setting(s_wifi)

        needs_security = bool(ap and _security_label(ap))
        if needs_security:
            s_sec = NM.SettingWirelessSecurity.new()
            s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT, "wpa-psk")
            s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_PSK, password or "")
            conn.add_setting(s_sec)

        def _cb(client, res, _u=None):
            try:
                client.add_and_activate_connection_finish(res)
                on_done(True, None)
            except GLib.Error as e:
                on_done(False, e.message)

        self.client.add_and_activate_connection_async(
            conn, self._wifi_dev, ap.get_path() if ap else None, None, _cb
        )

    def disconnect(self):
        if self._wifi_dev:
            self._wifi_dev.disconnect_async(None, lambda *_: None)

    def forget(self, ssid):
        for c in self.client.get_connections():
            s = c.get_setting_wireless()
            if s and s.get_ssid() and NM.utils_ssid_to_utf8(s.get_ssid().get_data()) == ssid:
                c.delete_async(None, lambda *_: None)

    # ---- hotspot -----------------------------------------------------
    #
    # Deliberately shells out to `nmcli device wifi hotspot` here rather than
    # building the NM.SimpleConnection by hand like connect_to() does: a
    # working hotspot needs AP mode *and* ipv4.method=shared (NAT + DHCP
    # server, so connected devices actually get internet through whatever
    # else is online - confirmed this system's ethernet holds the real
    # default route) *and* correct WPA2 AP-mode security settings all
    # agreeing with each other. nmcli's hotspot command is the well-tested,
    # purpose-built tool for getting that exact combination right - hand-
    # rolling it via raw D-Bus risks a subtly wrong setting (e.g. forgetting
    # "shared") that looks like it worked but leaves clients with no
    # internet. Runs in a background thread (nmcli blocks for a few seconds
    # while the connection activates) so the GTK main loop never stalls.

    def is_hotspot_active(self):
        if not self._wifi_dev:
            return False
        ac = self._wifi_dev.get_active_connection()
        if not ac:
            return False
        remote = self.client.get_connection_by_uuid(ac.get_uuid())
        if not remote:
            return False
        wifi_setting = remote.get_setting_wireless()
        return wifi_setting is not None and wifi_setting.get_mode() == "ap"

    def _run_nmcli_async(self, args, on_done):
        def _run():
            try:
                subprocess.run(args, check=True, capture_output=True, text=True, timeout=20)
                ok, err = True, None
            except subprocess.CalledProcessError as e:
                ok, err = False, (e.stderr or "").strip() or "nmcli failed"
            except Exception as e:
                ok, err = False, str(e)
            if on_done:
                GLib.idle_add(on_done, ok, err)

        threading.Thread(target=_run, daemon=True).start()

    def start_hotspot(self, ssid, password, on_done=None):
        if not self._wifi_dev:
            if on_done:
                on_done(False, "No Wi-Fi device found")
            return
        self._run_nmcli_async(
            ["nmcli", "device", "wifi", "hotspot",
             "ifname", self._wifi_dev.get_iface(),
             "con-name", HOTSPOT_CON_NAME,
             "ssid", ssid, "password", password],
            on_done,
        )

    def stop_hotspot(self, on_done=None):
        self._run_nmcli_async(
            ["nmcli", "connection", "down", HOTSPOT_CON_NAME], on_done
        )

    def update_hotspot(self, ssid, password, on_done=None):
        """Edits the name/password of the already-saved Hotspot profile in
        place via `nmcli connection modify`, rather than recreating it
        through start_hotspot()'s `nmcli device wifi hotspot` path - that
        command is for first-time creation and isn't guaranteed to update
        an existing same-named profile cleanly. If the hotspot is currently
        active, reactivates it afterward so already-connected devices (and
        the popup's own "Sharing internet as ..." state) actually reflect
        the new password immediately instead of it silently only applying
        on the next manual toggle."""
        was_active = self.is_hotspot_active()

        def _after_modify(ok, err):
            if not ok or not was_active:
                if on_done:
                    on_done(ok, err)
                return
            self._run_nmcli_async(["nmcli", "connection", "up", HOTSPOT_CON_NAME], on_done)

        self._run_nmcli_async(
            ["nmcli", "connection", "modify", HOTSPOT_CON_NAME,
             "802-11-wireless.ssid", ssid,
             "wifi-sec.psk", password],
            _after_modify,
        )

    def has_saved_hotspot(self):
        return self.client.get_connection_by_id(HOTSPOT_CON_NAME) is not None

    def get_saved_hotspot_ssid(self):
        """SSID of the saved Hotspot profile, whether or not it's active
        right now - lets the UI show/reuse the last-configured name instead
        of always defaulting back to the hostname."""
        conn = self.client.get_connection_by_id(HOTSPOT_CON_NAME)
        if not conn:
            return None
        s = conn.get_setting_wireless()
        if not s or not s.get_ssid():
            return None
        return NM.utils_ssid_to_utf8(s.get_ssid().get_data())

    def activate_saved_hotspot(self, on_done=None):
        """Re-activates the existing Hotspot profile without asking for the
        name/password again - the "just flip the switch" path for repeat
        use, once it's been set up once via start_hotspot()."""
        self._run_nmcli_async(
            ["nmcli", "connection", "up", HOTSPOT_CON_NAME], on_done
        )

    def _run_nmcli_output_async(self, args, on_done):
        """Like _run_nmcli_async, but hands back stdout on success instead
        of just True/False - _run_nmcli_async's subprocess.run() call
        doesn't even keep its own result, only used for pass/fail state
        changes so far, not reads."""
        def _run():
            try:
                result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=10)
                ok, output = True, result.stdout
            except Exception:
                ok, output = False, None
            GLib.idle_add(on_done, ok, output)

        threading.Thread(target=_run, daemon=True).start()

    def get_saved_hotspot_password(self, on_done):
        """on_done(password: str|None). The popup only holds the hotspot
        password in memory for the process that originally set it up
        (typed by the user or randomly generated) - reopening the popup, or
        needing to type it into a second device, has no way to see it again
        otherwise. NetworkManager still has it: psk-flags=0 means it's
        stored in the system connection, readable by the owning user
        without a secrets-agent prompt - confirmed live via
        `nmcli --show-secrets connection show Hotspot`."""
        def _cb(ok, output):
            on_done(output.strip() if ok and output else None)

        self._run_nmcli_output_async(
            ["nmcli", "-s", "-g", "802-11-wireless-security.psk",
             "connection", "show", HOTSPOT_CON_NAME],
            _cb,
        )
