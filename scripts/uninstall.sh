#!/usr/bin/env bash
# Remove a instalação de usuário do OpenMacros+ (somente o que scripts/install.sh gerou).
set -euo pipefail

usage() {
  cat <<'EOF2'
Remove a instalação de usuário do OpenMacros+ (arquivos de scripts/install.sh).

  scripts/uninstall.sh [--purge] [--legacy] [-h|--help]

Só remove o que tem a marca do instalador (ou a assinatura de versões antigas); arquivos alheios com
os mesmos nomes ficam onde estão. O pacote pipx `openmacros-plus` só é desinstalado se apontar para este
repositório. Não toca em ~/.config/openmacros/config.json (--purge o remove) nem em regras udev (sudo).
Também reconhece e remove os artefatos antigos do projeto quando se chamava Clique (clique, cliqued,
clique-tray, cliqued.service, io.github.clique.*.desktop, ícone), só se tiverem a marca do instalador.
--legacy: remove SOMENTE esses artefatos antigos e não mexe na instalação atual.
Variável: OPENMACROS_SKIP_SYSTEMCTL=1 pula systemctl.
EOF2
}

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PURGE=0
LEGACY_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    --legacy) LEGACY_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "opção desconhecida: $arg" >&2; exit 2 ;;
  esac
done

: "${HOME:?HOME não definido}"
xdg() { case "${!1:-}" in /*) printf '%s' "${!1}" ;; *) printf '%s' "$2" ;; esac; }
BIN="$HOME/.local/bin"
DATA="$(xdg XDG_DATA_HOME "$HOME/.local/share")"
CONF="$(xdg XDG_CONFIG_HOME "$HOME/.config")"
SKIP_SYSTEMCTL="${OPENMACROS_SKIP_SYSTEMCTL:-0}"

warn() { printf 'aviso: %s\n' "$*" >&2; }
is_ours() {
  [ -f "$1" ] && [ ! -L "$1" ] && grep -qE 'scripts/install\.sh|^(Description|Name)=OpenMacros\+|^Icon=io\.github\.openmacros\.' "$1" 2>/dev/null
}
# É nosso, de quando o projeto se chamava Clique? (marca do instalador ou assinatura do nome antigo)
is_legacy_ours() {
  [ -f "$1" ] && [ ! -L "$1" ] && grep -qE 'scripts/install\.sh|^(Description|Name)=Clique|^Icon=io\.github\.clique\.' "$1" 2>/dev/null
}
has_mark() { [ -f "$1" ] && [ ! -L "$1" ] && grep -q 'scripts/install\.sh' "$1" 2>/dev/null; }
remove_ours() { # arquivo
  if [ -e "$1" ] || [ -L "$1" ]; then
    if is_ours "$1"; then rm -f -- "$1"; else warn "$1 não é do OpenMacros+; mantido"; fi
  fi
}

# --- artefatos antigos (projeto chamado Clique) ---
remove_legacy() { # arquivo
  if [ -e "$1" ] || [ -L "$1" ]; then
    if is_legacy_ours "$1"; then rm -f -- "$1"; echo "removido (antigo): $1"; else warn "$1 não é nosso; mantido"; fi
  fi
}
OLD_UNIT="$CONF/systemd/user/cliqued.service"
if [ "$SKIP_SYSTEMCTL" != 1 ] && command -v systemctl >/dev/null && is_legacy_ours "$OLD_UNIT"; then
  systemctl --user disable --now cliqued.service 2>/dev/null || true
fi
for n in clique cliqued clique-tray; do
  if [ -e "$BIN/$n" ] || [ -L "$BIN/$n" ]; then
    if has_mark "$BIN/$n"; then rm -f -- "$BIN/$n"; echo "removido (antigo): $BIN/$n"; else warn "$BIN/$n não tem a marca do instalador; mantido"; fi
  fi
done
remove_legacy "$OLD_UNIT"
remove_legacy "$DATA/applications/io.github.clique.App.desktop"
remove_legacy "$CONF/autostart/io.github.clique.Tray.desktop"
remove_legacy "$CONF/autostart/io.github.clique.Session.desktop"
OLD_ICON="$DATA/icons/hicolor/scalable/apps/io.github.clique.App.svg"
if [ -f "$OLD_ICON" ] && [ ! -L "$OLD_ICON" ]; then
  if cmp -s "$OLD_ICON" "$REPO/data/icons/io.github.openmacros.App.svg"; then rm -f -- "$OLD_ICON"; echo "removido (antigo): $OLD_ICON"
  else warn "$OLD_ICON difere do ícone deste repositório; mantido"; fi
fi
if [ "$LEGACY_ONLY" = 1 ]; then
  if [ "$SKIP_SYSTEMCTL" != 1 ] && command -v systemctl >/dev/null; then systemctl --user daemon-reload || true; fi
  echo "artefatos antigos tratados (a instalação atual não foi tocada)."
  exit 0
fi

UNIT="$CONF/systemd/user/openmacrosd.service"
if [ "$SKIP_SYSTEMCTL" != 1 ] && command -v systemctl >/dev/null && is_ours "$UNIT"; then
  systemctl --user disable --now openmacrosd.service 2>/dev/null || true
fi

# lançadores: só os gerados por nós (modo dev); no modo pipx, via pipx
for n in openmacrosd openmacros openmacros-tray; do
  if [ -e "$BIN/$n" ] || [ -L "$BIN/$n" ]; then
    if has_mark "$BIN/$n"; then rm -f -- "$BIN/$n"; fi
  fi
done

# pipx: só se o pacote instalado (openmacros-plus; ou o antigo `clique`) vier DESTE repositório
pipx_points_here() { # nome do venv
  local pkg="$1"
  command -v pipx >/dev/null && command -v python3 >/dev/null || return 1
  pipx list --json 2>/dev/null | REPO="$REPO" PKG="$pkg" python3 -I -c '
import json, os, sys
try:
    d = json.load(sys.stdin)
    src = d["venvs"][os.environ["PKG"]]["metadata"]["main_package"]["package_or_url"]
except Exception:
    sys.exit(1)
src = str(src)
if src.startswith("file://"):
    src = src[7:]
sys.exit(0 if src and os.path.realpath(src) == os.path.realpath(os.environ["REPO"]) else 1)'
}
for PKG in openmacros-plus clique; do
  if pipx_points_here "$PKG"; then
    pipx uninstall "$PKG" || true
  elif command -v pipx >/dev/null && pipx list --short 2>/dev/null | grep -q "^$PKG "; then
    warn "o pacote pipx '$PKG' não aponta para este repositório; mantido"
  fi
done

remove_ours "$UNIT"
remove_ours "$DATA/applications/io.github.openmacros.App.desktop"
remove_ours "$CONF/autostart/io.github.openmacros.Tray.desktop"
remove_ours "$CONF/autostart/io.github.openmacros.Session.desktop"
ICON="$DATA/icons/hicolor/scalable/apps/io.github.openmacros.App.svg"
if [ -f "$ICON" ]; then
  if cmp -s "$ICON" "$REPO/data/icons/io.github.openmacros.App.svg"; then rm -f -- "$ICON"
  else warn "$ICON difere do ícone deste repositório; mantido"; fi
fi

if [ "$SKIP_SYSTEMCTL" != 1 ] && command -v systemctl >/dev/null; then
  systemctl --user daemon-reload || true
fi
[ "$PURGE" = 1 ] && rm -rf "$CONF/openmacros" "$CONF/clique"   # o diretório antigo também: senão o daemon o copiaria de volta

echo "OpenMacros+ removido do usuário."
UDEV_DIR="${OPENMACROS_UDEV_DIR:-/etc/udev/rules.d}"
if [ -e "$UDEV_DIR/70-openmacros.rules" ]; then
  printf 'Regra udev (opcional, exige sudo): sudo rm %q && sudo udevadm control --reload-rules\n' "$UDEV_DIR/70-openmacros.rules"
fi
