"""Janela principal."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .context import PageContext  # noqa: E402
from .dbus_client import CliqueClient  # noqa: E402
from .pages.device import DevicePage  # noqa: E402
from .pages.devices import DevicesPage  # noqa: E402
from .pages.smart import SmartActionsPage, SmartEditorPage  # noqa: E402
from .widgets.import_dialog import ImportDialog  # noqa: E402


class CliqueWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, client: CliqueClient | None = None):
        super().__init__(application=app, title="Clique", default_width=1120, default_height=780)
        self.set_size_request(360, 400)
        self.client = client or CliqueClient()
        self.devices: dict[str, dict] = {}
        self.device_page: DevicePage | None = None
        self.ctx = PageContext(self.client, self.toast)

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.root_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.toasts.set_child(self.root_stack)

        self.nav = Adw.NavigationView()
        self.devices_page = DevicesPage()
        self.devices_page.connect("device-activated", self._open_device)
        self.devices_page.connect("rescan", lambda *_: self.client.rescan(self.ctx.reporter()))
        self.devices_page.connect("add-device", lambda *_: self.show_add_device())
        self.devices_page.connect("smart-actions", lambda *_: self.show_smart_actions())
        self.smart_page: SmartActionsPage | None = None
        self.ctx.open_smart_editor = self.open_smart_editor
        for name, cb in (("import-art", lambda *_: self.show_import()),
                         ("rescan", lambda *_: self.client.rescan(self.ctx.reporter()))):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
        toast = Gio.SimpleAction.new("toast", GLib.VariantType.new("s"))
        toast.connect("activate", lambda _a, v: self.toast(v.get_string()))
        self.add_action(toast)
        self.nav.add(self.devices_page)
        self.nav.connect("popped", self._on_popped)
        self.root_stack.add_named(self.nav, "main")
        self.root_stack.add_named(self._build_unavailable(), "unavailable")
        self.root_stack.set_visible_child_name("unavailable")  # até o cliente confirmar

        self.client.connect("availability-changed", self._on_availability)
        self.client.connect("devices-changed", lambda *_: self.refresh())
        self.client.connect("device-updated", self._on_device_updated)
        self.client.connect("error", self._on_error)
        self.client.connect("active-app-changed", self._on_active_app)
        self.client.connect("smart-actions-changed", lambda *_: self.refresh_smart())
        self.connect("close-request", self._on_close)
        self.client.start()

    # ---- estado "serviço fora do ar"
    def _build_unavailable(self) -> Gtk.Widget:
        page = Adw.StatusPage(
            icon_name="network-offline-symbolic", title="Serviço do Clique não está em execução",
            description="A interface precisa do serviço <b>cliqued</b> para falar com os dispositivos.\n"
                        "Inicie-o com <tt>systemctl --user start cliqued</tt> ou execute <tt>cliqued</tt> em um terminal.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        btn = Gtk.Button(label="Tentar novamente", halign=Gtk.Align.CENTER)
        btn.add_css_class("pill")
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: self.refresh())
        box.append(btn)
        page.set_child(box)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(page)
        return view

    # ---- diálogos
    def show_add_device(self) -> None:
        dlg = Adw.Dialog(title="Adicionar dispositivo", content_width=460)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=12, margin_bottom=20,
                      margin_start=20, margin_end=20)
        for title, text in (
            ("Receptor Unifying ou Bolt", "Conecte o receptor a uma porta USB e ligue o dispositivo. Para parear um "
             "novo dispositivo ao receptor, use as ferramentas do sistema (por exemplo, Solaar) e volte aqui."),
            ("Bluetooth", "Coloque o dispositivo em modo de pareamento (segure o botão Easy-Switch por 3 segundos) "
             "e pareie nas configurações de Bluetooth do sistema."),
            ("Cabo USB", "Conecte o cabo; teclados e mouses com fio aparecem automaticamente."),
        ):
            t = Gtk.Label(label=title, xalign=0)
            t.add_css_class("card-title")
            d = Gtk.Label(label=text, xalign=0, wrap=True)
            d.add_css_class("dim-label")
            box.append(t)
            box.append(d)
        btn = Gtk.Button(label="PROCURAR NOVAMENTE", halign=Gtk.Align.CENTER, margin_top=6)
        btn.add_css_class("outline-pill")

        def go(*_a):
            self.client.rescan(self.ctx.reporter())
            dlg.close()
        btn.connect("clicked", go)
        box.append(btn)
        view.set_content(box)
        dlg.set_child(view)
        dlg.present(self)

    def show_import(self) -> None:
        pids = sorted({str(d.get("model_id", "")).lower() for d in self.devices.values() if d.get("model_id")})
        ImportDialog(pids, self.on_art_changed).present(self)

    def on_art_changed(self) -> None:
        """Arte importada/removida: atualiza a tela inicial e a página aberta."""
        for d in self.devices.values():
            self.devices_page.update_device(d)
        if self.device_page and self.device_page.dev_id in self.devices:
            self.device_page.update(self.devices[self.device_page.dev_id])

    def toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=message, timeout=4))

    def _on_close(self, *_a) -> bool:
        self.client.stop()
        return False

    # ---- sinais
    def _on_availability(self, _c, available: bool) -> None:
        if available:
            self.root_stack.set_visible_child_name("main")
            self.devices_page.set_loading()
            self.refresh()
            self.refresh_smart()
            self.client.get_active_app(lambda app, err: app is not None and self._on_active_app(None, app))
        else:
            self.root_stack.set_visible_child_name("unavailable")

    def refresh(self) -> None:
        if not self.client.available:
            return

        def done(devices, error):
            if error:
                self.toast(error)
                return
            self.devices = {d["id"]: d for d in devices}
            self.devices_page.set_devices(devices)
            if self.device_page and self.device_page.dev_id in self.devices:
                self.device_page.update(self.devices[self.device_page.dev_id])
            elif self.device_page:
                self.nav.pop_to_tag("devices")
                self.toast("O dispositivo foi removido")
        self.client.get_devices(done)

    # ---- apps em foco e Smart Actions
    def _on_active_app(self, _c, app: dict) -> None:
        self.ctx.active_app = app
        if self.device_page:
            self.device_page.set_active_app(app)

    def refresh_smart(self) -> None:
        def done(sas, error):
            if error or sas is None:
                return  # daemon sem suporte a Smart Actions
            self.ctx.smart_actions = sas
            if self.smart_page:
                self.smart_page.refresh()
            if self.device_page:
                self.device_page.update(self.device_page.device)
        self.client.get_smart_actions(done)

    def show_smart_actions(self) -> None:
        self.smart_page = SmartActionsPage(self.ctx)
        self.nav.push(self.smart_page)

    def open_smart_editor(self, draft: dict | None, sid: str | None) -> None:
        page = SmartEditorPage(self.ctx, draft, sid, lambda: self.nav.pop())
        self.nav.push(page)

    def _on_device_updated(self, _c, dev_id: str, device: dict) -> None:
        self.devices[dev_id] = device
        self.devices_page.update_device(device)
        if self.device_page and self.device_page.dev_id == dev_id:
            self.device_page.update(device)

    def _on_error(self, _c, dev_id: str, message: str) -> None:
        self.toast(message)

    def _open_device(self, _p, dev_id: str) -> None:
        dev = self.devices.get(dev_id)
        if dev is None:
            return
        self.device_page = DevicePage(dev, self.ctx)
        self.device_page.set_active_app(self.ctx.active_app)
        self.nav.push(self.device_page)

    def _on_popped(self, _nav, page) -> None:
        if page is self.device_page:
            self.device_page = None
        if page is self.smart_page:
            self.smart_page = None
