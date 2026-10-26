#!/usr/bin/env bash
# Teste de fumaça do .deb SEM instalar: extrai com dpkg-deb -x e roda daemon, GUI e bandeja a partir da
# árvore extraída (fora do repositório), com dispositivo simulado e D-Bus de sessão descartável.
# Uso: packaging/deb/smoke-test.sh arquivo.deb     (precisa de xvfb-run e dbus-run-session)
set -euo pipefail

DEB="$(readlink -f "${1:?uso: smoke-test.sh arquivo.deb}")"
for c in dpkg-deb xvfb-run dbus-run-session; do command -v "$c" >/dev/null || { echo "erro: $c ausente" >&2; exit 1; }; done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ROOT="$WORK/root"
mkdir -p "$ROOT" "$WORK/home"
dpkg-deb -x "$DEB" "$ROOT"

export HOME="$WORK/home" XDG_CONFIG_HOME="$WORK/home/.config" XDG_DATA_HOME="$WORK/home/.local/share" \
       XDG_CACHE_HOME="$WORK/home/.cache" XDG_RUNTIME_DIR="$WORK/run"
mkdir -p "$XDG_RUNTIME_DIR"; chmod 700 "$XDG_RUNTIME_DIR"
export XDG_DATA_DIRS="$ROOT/usr/share:/usr/local/share:/usr/share"
export PYTHONPATH="$ROOT/usr/lib/python3/dist-packages" OPENMACROS_FAKE=1 ROOT
export NO_AT_BRIDGE=1 GTK_A11Y=none GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1

cat >"$WORK/inner.sh" <<'INNER'
set -u
cd "$HOME"   # fora do repositório
"$ROOT/usr/bin/openmacrosd" >"$HOME/daemon.log" 2>&1 &
DPID=$!
sleep 4
kill -0 "$DPID" 2>/dev/null || { echo "FALHA: daemon saiu"; cat "$HOME/daemon.log"; exit 1; }
echo "daemon: ativo após 4 s"

python3 - <<'PY' || exit 1
import os, sys
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk
import openmacros
from openmacros.gui import logic
from openmacros.gui.app import OpenMacrosApp, ICON_NAME

root = os.environ["ROOT"]
assert openmacros.__file__.startswith(root), openmacros.__file__
for rel in ("style.css", "apps.json", "art/generic-mouse.svg", "art/m720.svg", "layouts/m720.json"):
    assert (logic.DATA_DIR / rel).is_file(), rel
assert logic.load_layout("m720") is not None if hasattr(logic, "load_layout") else True

app = OpenMacrosApp()
result = {}
def check():
    win = app.props.active_window
    from gi.repository import Gdk
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    result["icon"] = theme.has_icon(ICON_NAME)
    result["win"] = win is not None
    app.quit()
    return False
app.connect("activate", lambda a: GLib.timeout_add(1500, check))
app.run([])
assert result.get("win"), "janela não foi criada"
assert result.get("icon"), f"ícone {ICON_NAME} não encontrado no tema"
print("GUI: janela criada, dados em", logic.DATA_DIR, "e ícone encontrado no tema")
PY

timeout 3 "$ROOT/usr/bin/openmacros-tray" >"$HOME/tray.log" 2>&1
rc=$?
if [ "$rc" != 124 ] && [ "$rc" != 0 ]; then echo "FALHA: bandeja saiu com $rc"; cat "$HOME/tray.log"; exit 1; fi
echo "bandeja: ok (rc=$rc)"
kill "$DPID" 2>/dev/null; wait "$DPID" 2>/dev/null
grep -qi traceback "$HOME/daemon.log" && { echo "FALHA: traceback no daemon"; cat "$HOME/daemon.log"; exit 1; }
echo "OK"
INNER
exec xvfb-run -a dbus-run-session -- bash "$WORK/inner.sh"
