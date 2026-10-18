"""System tray icon via StatusNotifierItem + com.canonical.dbusmenu (pure Gio, no deps).

Works on KDE Plasma natively and on GNOME with the AppIndicator extension.
"""
from __future__ import annotations

import os

from gi.repository import Gio, GLib

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
  </interface>
</node>
"""

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"


class MenuItem:
    def __init__(self, label=None, callback=None, toggle=None, separator=False, enabled=True):
        self.label = label
        self.callback = callback
        self.toggle = toggle          # None, or a callable returning bool (checkbox state)
        self.separator = separator
        self.enabled = enabled


class TrayIcon:
    """tray = TrayIcon(app_id, title, icon_name, icon_dir, on_activate, items)"""

    def __init__(self, app_id, title, icon_name, icon_dir, on_activate, items: list[MenuItem]):
        self.app_id, self.title, self.icon_name, self.icon_dir = app_id, title, icon_name, icon_dir
        self.on_activate = on_activate
        self.items = items
        self.tooltip = title
        self.revision = 1
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._ids = []
        self.available = False

        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._ids.append(self.bus.register_object(ITEM_PATH, sni, self._sni_call, self._sni_prop, None))
        self._ids.append(self.bus.register_object(MENU_PATH, menu, self._menu_call, self._menu_prop, None))
        self._own = Gio.bus_own_name_on_connection(self.bus, self.bus_name,
                                                   Gio.BusNameOwnerFlags.NONE,
                                                   self._name_acquired, None)
        # re-register if the tray host (plasmashell) restarts
        self._watch = Gio.bus_watch_name_on_connection(
            self.bus, "org.kde.StatusNotifierWatcher", Gio.BusNameWatcherFlags.NONE,
            lambda *a: self._register(), lambda *a: setattr(self, "available", False))

    # -- registration -------------------------------------------------------------
    def _name_acquired(self, *a):
        self._register()

    def _register(self):
        def done(bus, res):
            try:
                bus.call_finish(res)
                self.available = True
            except GLib.Error:
                self.available = False
        self.bus.call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                      "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
                      GLib.Variant("(s)", (self.bus_name,)), None, Gio.DBusCallFlags.NONE,
                      2000, None, done)

    @staticmethod
    def host_present() -> bool:
        """True if a tray host (StatusNotifierWatcher) is running."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            r = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "NameHasOwner", GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)),
                              GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 1000, None)
            return r.unpack()[0]
        except GLib.Error:
            return False

    # -- StatusNotifierItem -----------------------------------------------------------
    def _sni_prop(self, conn, sender, path, iface, name):
        v = {
            "Category": ("s", "Hardware"),
            "Id": ("s", self.app_id),
            "Title": ("s", self.title),
            "Status": ("s", "Active"),
            "WindowId": ("i", 0),
            "IconName": ("s", self.icon_name),
            "IconThemePath": ("s", self.icon_dir or ""),
            "OverlayIconName": ("s", ""),
            "AttentionIconName": ("s", ""),
            "ToolTip": ("(sa(iiay)ss)", (self.icon_name, [], self.title, self.tooltip)),
            "ItemIsMenu": ("b", False),
            "Menu": ("o", MENU_PATH),
        }.get(name)
        return GLib.Variant(*v) if v else None

    def _sni_call(self, conn, sender, path, iface, method, params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            GLib.idle_add(self.on_activate)
        invocation.return_value(None)

    def set_tooltip(self, text):
        self.tooltip = text
        self.bus.emit_signal(None, ITEM_PATH, "org.kde.StatusNotifierItem", "NewToolTip", None)

    # -- dbusmenu -------------------------------------------------------------------------
    def _item_props(self, i):
        if i == 0:
            return {"children-display": GLib.Variant("s", "submenu")}
        it = self.items[i - 1]
        if it.separator:
            return {"type": GLib.Variant("s", "separator")}
        p = {"label": GLib.Variant("s", it.label), "enabled": GLib.Variant("b", it.enabled),
             "visible": GLib.Variant("b", True)}
        if it.toggle is not None:
            p["toggle-type"] = GLib.Variant("s", "checkmark")
            p["toggle-state"] = GLib.Variant("i", 1 if it.toggle() else 0)
        return p

    def _layout(self):
        children = [GLib.Variant("(ia{sv}av)", (i, self._item_props(i), []))
                    for i in range(1, len(self.items) + 1)]
        return (0, self._item_props(0), children)

    def refresh(self):
        """Call after toggle states or labels change."""
        self.revision += 1
        self.bus.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated",
                             GLib.Variant("(ui)", (self.revision, 0)))

    def _menu_prop(self, conn, sender, path, iface, name):
        v = {"Version": ("u", 3), "TextDirection": ("s", "ltr"), "Status": ("s", "normal"),
             "IconThemePath": ("as", [self.icon_dir] if self.icon_dir else [])}.get(name)
        return GLib.Variant(*v) if v else None

    def _menu_call(self, conn, sender, path, iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self.revision, self._layout())))
        elif method == "GetGroupProperties":
            ids = args[0] or range(0, len(self.items) + 1)
            out = [(i, self._item_props(i)) for i in ids if 0 <= i <= len(self.items)]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))
        elif method == "GetProperty":
            i, name = args
            props = self._item_props(i) if 0 <= i <= len(self.items) else {}
            invocation.return_value(GLib.Variant("(v)", (props.get(name, GLib.Variant("s", "")),)))
        elif method == "Event":
            self._event(args[0], args[1])
            invocation.return_value(None)
        elif method == "EventGroup":
            for i, ev, _d, _t in args[0]:
                self._event(i, ev)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def _event(self, i, event):
        if event == "clicked" and 1 <= i <= len(self.items):
            cb = self.items[i - 1].callback
            if cb:
                GLib.idle_add(lambda: (cb(), self.refresh(), False)[-1])

    def destroy(self):
        for rid in self._ids:
            self.bus.unregister_object(rid)
        Gio.bus_unown_name(self._own)
        Gio.bus_unwatch_name(self._watch)
