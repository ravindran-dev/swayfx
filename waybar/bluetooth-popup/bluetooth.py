"""
BlueZ access over raw D-Bus (org.bluez has no GObject-Introspection binding
the way NetworkManager has libnm - confirmed, no Bluez.typelib anywhere on
this system). Built on Gio.DBusConnection directly instead: still fully
signal-driven off BlueZ's own ObjectManager/PropertiesChanged D-Bus signals,
so there is no polling here either, matching network.py's approach.
"""
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, GObject

BLUEZ = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
OM_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPS_IFACE = "org.freedesktop.DBus.Properties"


class Bluetooth(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.adapter_path = None
        self.devices = {}  # path -> {Address, Alias, Paired, Connected, ...}
        self._refresh_objects()

        self.bus.signal_subscribe(
            BLUEZ, OM_IFACE, "InterfacesAdded", None, None,
            Gio.DBusSignalFlags.NONE, self._on_interfaces_added,
        )
        self.bus.signal_subscribe(
            BLUEZ, OM_IFACE, "InterfacesRemoved", None, None,
            Gio.DBusSignalFlags.NONE, self._on_interfaces_removed,
        )
        self.bus.signal_subscribe(
            BLUEZ, PROPS_IFACE, "PropertiesChanged", None, None,
            Gio.DBusSignalFlags.NONE, self._on_props_changed,
        )

    def _refresh_objects(self):
        proxy = Gio.DBusProxy.new_sync(
            self.bus, Gio.DBusProxyFlags.NONE, None, BLUEZ, "/", OM_IFACE, None
        )
        result = proxy.call_sync("GetManagedObjects", None, Gio.DBusCallFlags.NONE, -1, None)
        objects = result.unpack()[0]
        self.devices = {}
        for path, ifaces in objects.items():
            if ADAPTER_IFACE in ifaces:
                self.adapter_path = path
            if DEVICE_IFACE in ifaces:
                self.devices[path] = ifaces[DEVICE_IFACE]

    def _emit(self, *_a):
        self.emit("changed")

    def _on_interfaces_added(self, _conn, _sender, _path, _iface, _signal, params, *_a):
        obj_path, ifaces = params.unpack()
        if ADAPTER_IFACE in ifaces:
            self.adapter_path = obj_path
        if DEVICE_IFACE in ifaces:
            self.devices[obj_path] = ifaces[DEVICE_IFACE]
        self._emit()

    def _on_interfaces_removed(self, _conn, _sender, _path, _iface, _signal, params, *_a):
        obj_path, removed_ifaces = params.unpack()
        if DEVICE_IFACE in removed_ifaces:
            self.devices.pop(obj_path, None)
        self._emit()

    def _on_props_changed(self, _conn, _sender, path, _iface, _signal, params, *_a):
        changed_iface, changed_props, _invalidated = params.unpack()
        if changed_iface == DEVICE_IFACE and path in self.devices:
            self.devices[path].update(changed_props)
            self._emit()
        elif changed_iface == ADAPTER_IFACE and path == self.adapter_path:
            self._emit()

    # ---- low-level D-Bus helpers -----------------------------------

    def _get_prop(self, path, iface, name, default=None):
        try:
            result = self.bus.call_sync(
                BLUEZ, path, PROPS_IFACE, "Get",
                GLib.Variant("(ss)", (iface, name)),
                GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, -1, None,
            )
            return result.unpack()[0]
        except GLib.Error:
            return default

    def _set_prop(self, path, iface, name, variant):
        self.bus.call_sync(
            BLUEZ, path, PROPS_IFACE, "Set",
            GLib.Variant("(ssv)", (iface, name, variant)),
            None, Gio.DBusCallFlags.NONE, -1, None,
        )

    def _call_async(self, path, iface, method, args, on_done):
        def _cb(conn, res, _u=None):
            try:
                conn.call_finish(res)
                if on_done:
                    on_done(True, None)
            except GLib.Error as e:
                if on_done:
                    on_done(False, e.message)

        self.bus.call(
            BLUEZ, path, iface, method, args, None,
            Gio.DBusCallFlags.NONE, 15000, None, _cb,
        )

    # ---- state -----------------------------------------------------

    def has_adapter(self):
        return self.adapter_path is not None

    def is_enabled(self):
        if not self.adapter_path:
            return False
        return bool(self._get_prop(self.adapter_path, ADAPTER_IFACE, "Powered", False))

    def set_enabled(self, enabled):
        if self.adapter_path:
            self._set_prop(self.adapter_path, ADAPTER_IFACE, "Powered", GLib.Variant("b", enabled))

    def get_devices(self):
        out = []
        for path, props in self.devices.items():
            name = props.get("Alias") or props.get("Name") or props.get("Address", "Unknown device")
            out.append({
                "path": path,
                "name": name,
                "address": props.get("Address", ""),
                "paired": bool(props.get("Paired", False)),
                "connected": bool(props.get("Connected", False)),
                "trusted": bool(props.get("Trusted", False)),
            })
        # Connected first, then paired, then alphabetical - same ordering
        # philosophy as network.py's "connected first" sort.
        out.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
        return out

    # ---- actions -----------------------------------------------------

    def connect_device(self, path, on_done=None):
        self._call_async(path, DEVICE_IFACE, "Connect", None, on_done)

    def disconnect_device(self, path, on_done=None):
        self._call_async(path, DEVICE_IFACE, "Disconnect", None, on_done)

    def pair_device(self, path, on_done=None):
        # No Agent1 registered: works for "Just Works"-style devices (most
        # modern earbuds/mice/keyboards with no PIN), fails cleanly with a
        # D-Bus error for devices that require an on-screen PIN confirmation.
        def _after_pair(ok, err):
            if ok:
                self._call_async(path, DEVICE_IFACE, "Trust", None, None)
                self.connect_device(path, on_done)
            elif on_done:
                on_done(False, err)

        self._call_async(path, DEVICE_IFACE, "Pair", None, _after_pair)

    def forget_device(self, path, on_done=None):
        if self.adapter_path:
            self._call_async(
                self.adapter_path, ADAPTER_IFACE, "RemoveDevice",
                GLib.Variant("(o)", (path,)), on_done,
            )

    def start_discovery(self):
        if self.adapter_path:
            self._call_async(self.adapter_path, ADAPTER_IFACE, "StartDiscovery", None, None)

    def stop_discovery(self):
        if self.adapter_path:
            self._call_async(self.adapter_path, ADAPTER_IFACE, "StopDiscovery", None, None)
