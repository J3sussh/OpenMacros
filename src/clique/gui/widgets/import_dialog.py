"""Diálogo para importar imagens de dispositivos do Logi Options+ (opcional, uso local)."""

from __future__ import annotations

import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ... import vendor_assets as va  # noqa: E402

LEGAL = ("As imagens dos dispositivos pertencem à Logitech. O Clique não as distribui: elas são lidas de um "
         "arquivo que você mesmo baixou (o instalador offline do Logi Options+ ou o depots.zip) e ficam "
         "gravadas apenas neste computador, em %s. Este recurso é opcional.")


class ImportDialog(Adw.Dialog):
    def __init__(self, connected_pids: list[str], on_done: Callable[[], None]):
        super().__init__(title="Importar imagens do Logi Options+", content_width=480, content_height=520)
        self._pids = connected_pids
        self._on_done = on_done
        self._path: str | None = va.saved_source()
        self._cancel = threading.Event()
        self._busy = False

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=12, margin_bottom=18,
                      margin_start=18, margin_end=18)
        legal = Gtk.Label(label=LEGAL % va.vendor_dir(), wrap=True, xalign=0)
        legal.add_css_class("dim-label")
        box.append(legal)

        group = Adw.PreferencesGroup()
        self.file_row = Adw.ActionRow(title="Arquivo de origem", subtitle=self._path or "Nenhum arquivo escolhido")
        choose = Gtk.Button(label="Escolher…", valign=Gtk.Align.CENTER)
        choose.connect("clicked", self._choose)
        self.file_row.add_suffix(choose)
        group.add(self.file_row)
        self.status_row = Adw.ActionRow(title="Já importadas", subtitle=self._summary())
        group.add(self.status_row)
        box.append(group)

        self.progress = Gtk.ProgressBar(show_text=True, visible=False)
        self.message = Gtk.Label(xalign=0, wrap=True)
        box.append(self.progress)
        box.append(self.message)

        self.btn_connected = Gtk.Button(label="Importar para os dispositivos conectados")
        self.btn_connected.add_css_class("suggested-action")
        self.btn_connected.add_css_class("pill")
        self.btn_connected.connect("clicked", lambda *_: self._start(self._pids))
        self.btn_all = Gtk.Button(label="Importar todos os dispositivos")
        self.btn_all.add_css_class("pill")
        self.btn_all.connect("clicked", lambda *_: self._start(None))
        self.btn_remove = Gtk.Button(label="Remover imagens importadas")
        self.btn_remove.add_css_class("destructive-action")
        self.btn_remove.add_css_class("flat")
        self.btn_remove.connect("clicked", self._remove)
        for b in (self.btn_connected, self.btn_all, self.btn_remove):
            b.set_halign(Gtk.Align.CENTER)
            box.append(b)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=box)
        view.set_content(sw)
        self.set_child(view)
        self._update_sensitivity()
        self.connect("closed", lambda *_: self._cancel.set())

    def _summary(self) -> str:
        n = len(va.imported_pids())
        return f"{n} dispositivo(s)" if n else "Nenhuma"

    def _update_sensitivity(self) -> None:
        ok = bool(self._path) and not self._busy
        self.btn_connected.set_sensitive(ok and bool(self._pids))
        self.btn_all.set_sensitive(ok)
        self.btn_remove.set_sensitive(not self._busy and bool(va.imported_pids()))

    def _choose(self, *_a) -> None:
        dlg = Gtk.FileDialog(title="Escolha o instalador offline ou depots.zip")
        flt = Gtk.FileFilter(name="Instalador / ZIP")
        for pat in ("*.exe", "*.zip"):
            flt.add_pattern(pat)
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(flt)
        dlg.set_filters(store)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            self._path = f.get_path()
            self.file_row.set_subtitle(self._path or "")
            self._update_sensitivity()
        dlg.open(self.get_root(), None, done)

    def _start(self, pids: list[str] | None) -> None:
        if not self._path or self._busy:
            return
        self._busy = True
        self._cancel.clear()
        self.progress.set_visible(True)
        self.progress.set_fraction(0)
        self.message.set_label("Iniciando…")
        self.message.remove_css_class("error")
        self._update_sensitivity()
        path = self._path

        def progress(done: int, total: int, msg: str) -> None:
            GLib.idle_add(self._on_progress, done, total, msg)

        def work() -> None:
            try:
                res = va.import_assets(path, pids, progress=progress, cancel=self._cancel.is_set)
                GLib.idle_add(self._finished, res, None)
            except Exception as e:  # noqa: BLE001 - mostrado ao usuário
                GLib.idle_add(self._finished, None, str(e))
        threading.Thread(target=work, daemon=True, name="clique-import").start()

    def _on_progress(self, done: int, total: int, msg: str) -> bool:
        self.progress.set_fraction(done / total if total else 0)
        self.progress.set_text(f"{done}/{total}" if total > 1 else "")
        self.message.set_label(msg)
        return False

    def _finished(self, res, error: str | None) -> bool:
        self._busy = False
        if error:
            self.message.set_label(error)
            self.message.add_css_class("error")
        else:
            txt = f"{len(res.imported)} importado(s)."
            if res.missing:
                txt += f" Sem arte no arquivo para: {', '.join(sorted(set(res.missing)))}."
            self.message.set_label(txt)
            self.progress.set_fraction(1)
        self.status_row.set_subtitle(self._summary())
        self._update_sensitivity()
        if not error:
            self._on_done()
        return False

    def _remove(self, *_a) -> None:
        va.remove_all()
        self.status_row.set_subtitle(self._summary())
        self.message.set_label("Imagens importadas removidas.")
        self._update_sensitivity()
        self._on_done()
