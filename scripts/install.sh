#!/usr/bin/env bash
# Instalação de usuário do OpenMacros+ (sem sudo).
set -euo pipefail

usage() {
  cat <<'EOF'
Instalação de usuário do OpenMacros+ (sem sudo).

  scripts/install.sh [--pipx] [--no-start] [-h|--help]

Modo padrão ("dev"): lançadores em ~/.local/bin que executam o código deste repositório com os
pacotes do sistema (gi, evdev, pyudev, xlib). --pipx: `pipx install --system-site-packages`.
--no-start: habilita o serviço mas não o inicia agora.

O serviço sobe com o default.target do systemd --user (o graphical-session.target não fica ativo no
XFCE); o autostart io.github.openmacros.Session.desktop entrega DISPLAY/XAUTHORITY ao serviço no login.

Arquivos que não foram gerados por este script nunca são sobrescritos: um lançador alheio é pulado
(com aviso); unidade/.desktop diferentes ganham uma cópia .bak antes de serem trocados.

Variáveis (testes): OPENMACROS_SKIP_SYSTEMCTL=1 pula systemctl e update-*-database;
OPENMACROS_UDEV_DIR muda onde procurar as regras udev (padrão /etc/udev/rules.d).
EOF
}

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USE_PIPX=0
NO_START=0
for arg in "$@"; do
  case "$arg" in
    --pipx) USE_PIPX=1 ;;
    --no-start) NO_START=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "opção desconhecida: $arg" >&2; exit 2 ;;
  esac
done

: "${HOME:?HOME não definido}"
# a spec XDG manda ignorar valores relativos
xdg() { case "${!1:-}" in /*) printf '%s' "${!1}" ;; *) printf '%s' "$2" ;; esac; }
BIN="$HOME/.local/bin"
DATA="$(xdg XDG_DATA_HOME "$HOME/.local/share")"
CONF="$(xdg XDG_CONFIG_HOME "$HOME/.config")"
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor/scalable/apps"
UNITDIR="$CONF/systemd/user"
AUTOSTART="$CONF/autostart"
SKIP_SYSTEMCTL="${OPENMACROS_SKIP_SYSTEMCTL:-0}"
MARK="Gerado por scripts/install.sh"

say() { printf '%s\n' "$*"; }
warn() { printf 'aviso: %s\n' "$*" >&2; }
die() { printf 'erro: %s\n' "$*" >&2; exit 1; }

# caminhos com quebra de linha não cabem em .desktop/unit/lançador
for v in REPO HOME BIN DATA CONF; do
  case "${!v}" in *$'\n'*|*$'\r'*) die "$v contém quebra de linha" ;; esac
done

# --- escapes ---
# aspas simples de shell
shq() { printf "'%s'" "${1//\'/\'\\\'\'}"; }
# argumento entre aspas duplas para Exec= de .desktop (escapes do Exec + escapes de string do arquivo)
desktop_arg() {
  local s=$1
  s=${s//\\/\\\\\\\\}   # \  -> \\\\ (vira \\ no Exec e \ no argumento)
  s=${s//\"/\\\\\"}     # "  -> \\"
  s=${s//\`/\\\\\`}     # `  -> \\`
  s=${s//\$/\\\\\$}     # $  -> \\$
  s=${s//%/%%}          # %  -> %% (códigos de campo)
  printf '"%s"' "$s"
}
# argumento entre aspas duplas para ExecStart= do systemd (\ " % e $ são especiais)
unit_arg() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//%/%%}
  s=${s//\$/\$\$}
  printf '"%s"' "$s"
}

# --- escrita segura ---
# É nosso? (marca do instalador, ou assinatura de versões anteriores que não tinham a marca)
is_ours() {
  [ -f "$1" ] && [ ! -L "$1" ] && grep -qE 'scripts/install\.sh|^(Description|Name)=OpenMacros\+|^Icon=io\.github\.openmacros\.' "$1" 2>/dev/null
}
# É nosso, de quando o projeto se chamava Clique? (marca do instalador ou assinatura do nome antigo)
is_legacy_ours() {
  [ -f "$1" ] && [ ! -L "$1" ] && grep -qE 'scripts/install\.sh|^(Description|Name)=Clique|^Icon=io\.github\.clique\.' "$1" 2>/dev/null
}
has_mark() { [ -f "$1" ] && [ ! -L "$1" ] && grep -q 'scripts/install\.sh' "$1" 2>/dev/null; }

backup_name() {
  local b="$1.bak"
  [ -e "$b" ] || [ -L "$b" ] && b="$1.bak.$(date +%Y%m%d%H%M%S)"
  printf '%s' "$b"
}

# install_file DESTINO MODO ESTRITO < conteúdo
# Idempotente e atômico. ESTRITO=1: arquivo existente que não é nosso é mantido (retorna 1).
# ESTRITO=0: arquivo existente diferente que não é nosso vai para .bak e é trocado.
# ESTRITO=2: troca sem perguntar (ícone: o nome io.github.openmacros.App é nosso e o SVG não tem como levar marca).
install_file() {
  local dest="$1" mode="$2" strict="$3" tmp bak
  mkdir -p "$(dirname "$dest")"
  tmp="$(mktemp "$dest.XXXXXX")"
  cat >"$tmp"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if [ ! -L "$dest" ] && cmp -s "$tmp" "$dest"; then
      rm -f "$tmp"
      chmod "$mode" "$dest"
      return 0
    fi
    if [ "$strict" = 1 ] && ! has_mark "$dest"; then
      rm -f "$tmp"
      warn "$dest já existe e não foi gerado pelo OpenMacros+; mantido (nada foi sobrescrito)"
      return 1
    fi
    if [ "$strict" = 0 ] && ! is_ours "$dest"; then
      bak="$(backup_name "$dest")"
      mv -f "$dest" "$bak"
      warn "$dest era diferente e não é do OpenMacros+; cópia salva em $bak"
    fi
  fi
  chmod "$mode" "$tmp"
  mv -f "$tmp" "$dest"
}

PYTHON=python3
[ -x /usr/bin/python3 ] && PYTHON=/usr/bin/python3  # pacotes do sistema, mesmo dentro de um venv

launcher() { # nome, módulo
  install_file "$BIN/$1" 755 1 <<LAUNCH || SKIPPED=1
#!/bin/sh
# $MARK (modo dev). Remova com scripts/uninstall.sh.
exec env PYTHONPATH=$(shq "$REPO/src")"\${PYTHONPATH:+:\$PYTHONPATH}" $(shq "$PYTHON") -m $2 "\$@"
LAUNCH
}

# --- artefatos de quando o projeto se chamava Clique: só avisa, não remove ---
LEGACY=()
for n in clique cliqued clique-tray; do
  has_mark "$BIN/$n" && LEGACY+=("$BIN/$n")
done
for f in "$UNITDIR/cliqued.service" "$APPS/io.github.clique.App.desktop" \
         "$AUTOSTART/io.github.clique.Tray.desktop" "$AUTOSTART/io.github.clique.Session.desktop"; do
  is_legacy_ours "$f" && LEGACY+=("$f")
done
if [ ${#LEGACY[@]} -gt 0 ]; then
  warn "encontrei artefatos da instalação antiga (Clique):"
  for f in "${LEGACY[@]}"; do warn "  $f"; done
  warn "remova-os com: scripts/uninstall.sh --legacy   (a config antiga em ~/.config/clique é copiada, não apagada)"
fi

SKIPPED=0
if [ "$USE_PIPX" = 1 ]; then
  command -v pipx >/dev/null || die "pipx não encontrado"
  pipx install --system-site-packages --force "$REPO"
  say "instalado com pipx (lançadores em $BIN)"
else
  mkdir -p "$BIN"
  launcher openmacrosd openmacros.daemon.main
  launcher openmacros openmacros.gui
  launcher openmacros-tray openmacros.tray
  say "lançadores em $BIN: openmacrosd, openmacros, openmacros-tray (modo dev: usa $REPO/src)"
  [ "$SKIPPED" = 1 ] && warn "algum lançador existente não é do OpenMacros+ e foi mantido; o serviço/atalhos podem não usar este código"
fi

# --- serviço de usuário ---
unit_content() {
  printf '# %s. Remova com scripts/uninstall.sh.\n' "$MARK"
  case "$BIN" in
    *[[:space:]%\$\"\\]*)  # caminho com caracteres especiais: ExecStart absoluto, com aspas e escapes do systemd
      EXEC="$(unit_arg "$BIN/openmacrosd")" awk '/^ExecStart=/ { print "ExecStart=" ENVIRON["EXEC"]; next } { print }' \
        "$REPO/data/systemd/openmacrosd.service" ;;
    *) cat "$REPO/data/systemd/openmacrosd.service" ;;   # ExecStart=%h/.local/bin/openmacrosd
  esac
}
unit_content | install_file "$UNITDIR/openmacrosd.service" 644 0
say "unidade: $UNITDIR/openmacrosd.service"

# --- desktop, ícone, autostart (bandeja e sessão) ---
desktop() { # origem destino [executável]  (sem executável: Exec= do modelo é mantido)
  local src="$1" dest="$2" exe="${3:-}"
  {
    printf '# %s. Remova com scripts/uninstall.sh.\n' "$MARK"
    if [ -n "$exe" ]; then
      EXEC="$(desktop_arg "$exe")" awk '/^Exec=/ { print "Exec=" ENVIRON["EXEC"]; next } { print }' "$src"
    else
      cat "$src"
    fi
  } | install_file "$dest" 644 0
}
desktop "$REPO/data/io.github.openmacros.App.desktop" "$APPS/io.github.openmacros.App.desktop" "$BIN/openmacros"
desktop "$REPO/data/io.github.openmacros.Tray.desktop" "$AUTOSTART/io.github.openmacros.Tray.desktop" "$BIN/openmacros-tray"
desktop "$REPO/data/io.github.openmacros.Session.desktop" "$AUTOSTART/io.github.openmacros.Session.desktop"
say "desktop: $APPS/io.github.openmacros.App.desktop ; autostart: $AUTOSTART/io.github.openmacros.{Tray,Session}.desktop"

ICON_SRC="$REPO/data/icons/io.github.openmacros.App.svg"
if [ -f "$ICON_SRC" ]; then
  install_file "$ICONS/io.github.openmacros.App.svg" 644 2 <"$ICON_SRC"
  say "ícone: $ICONS/io.github.openmacros.App.svg"
else
  warn "ícone $ICON_SRC não existe; nada copiado"
fi

if [ "$SKIP_SYSTEMCTL" != 1 ]; then
  command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t -f "$DATA/icons/hicolor" 2>/dev/null || true
fi

# --- systemd --user ---
if [ "$SKIP_SYSTEMCTL" = 1 ] || ! command -v systemctl >/dev/null; then
  say "systemctl pulado; ative depois com: systemctl --user daemon-reload && systemctl --user enable --now openmacrosd.service"
else
  systemctl --user daemon-reload
  # versões antigas habilitavam o serviço em graphical-session.target (que não fica ativo no XFCE)
  if [ -e "$UNITDIR/graphical-session.target.wants/openmacrosd.service" ] \
     || [ -L "$UNITDIR/graphical-session.target.wants/openmacrosd.service" ]; then
    systemctl --user disable openmacrosd.service 2>/dev/null || true
  fi
  # o serviço precisa de DISPLAY/XAUTHORITY para ler o app em foco, usar o clipboard e os atalhos
  systemctl --user import-environment DISPLAY XAUTHORITY WAYLAND_DISPLAY XDG_SESSION_TYPE 2>/dev/null || true
  if [ "$NO_START" = 1 ]; then
    systemctl --user enable openmacrosd.service
    say "serviço habilitado (não iniciado: --no-start)"
  else
    systemctl --user enable --now openmacrosd.service
    systemctl --user restart openmacrosd.service  # reinstalação: pega o código/lançador novo
    say "serviço habilitado e iniciado"
  fi
fi

case ":$PATH:" in *":$BIN:"*) ;; *) warn "$BIN não está no PATH desta sessão" ;; esac

# --- udev: só imprime os comandos (exigem sudo) ---
RULES_SRC="$REPO/data/udev/70-openmacros.rules"
UDEV_DIR="${OPENMACROS_UDEV_DIR:-/etc/udev/rules.d}"
RULES_DST="$UDEV_DIR/70-openmacros.rules"
NEED=()
if ! cmp -s "$RULES_SRC" "$RULES_DST" 2>/dev/null; then
  NEED+=("sudo install -m 644 $(shq "$RULES_SRC") $(shq "$RULES_DST")")
fi
if [ ${#NEED[@]} -gt 0 ]; then
  say ""
  say "Regra udev (acesso ao hidraw/uinput) — execute você mesmo, pois exige sudo:"
  for c in "${NEED[@]}"; do say "  $c"; done
  say "  sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=misc"
  say "  (depois reconecte o receptor/mouse ou refaça o login)"
else
  say "regra udev já instalada: $RULES_DST"
fi
