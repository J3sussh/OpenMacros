#!/usr/bin/env bash
# Gera openmacros-plus_<versão>_all.deb (Debian/Ubuntu/Kali/Mint) com dpkg-deb. Sem debhelper e sem root.
set -euo pipefail

usage() {
  cat <<'USAGE'
Uso: packaging/deb/build-deb.sh [--version X.Y.Z] [--out DIR]

Monta a árvore do pacote num diretório temporário e gera openmacros-plus_<versão>_all.deb.
  --version  versão do pacote (padrão: a de pyproject.toml)
  --out      diretório de saída (padrão: <repositório>/dist)
Variáveis: SOURCE_DATE_EPOCH (data do changelog e dos arquivos, para build reproduzível).
USAGE
}

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION=""
OUT="$REPO/dist"
while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ $# -ge 2 ] || { echo "erro: --version exige valor" >&2; exit 2; }; VERSION="$2"; shift 2 ;;
    --out) [ $# -ge 2 ] || { echo "erro: --out exige valor" >&2; exit 2; }; OUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v dpkg-deb >/dev/null || { echo "erro: dpkg-deb não encontrado" >&2; exit 1; }

if [ -z "$VERSION" ]; then
  VERSION="$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' "$REPO/pyproject.toml" | head -n1)"
fi
[ -n "$VERSION" ] || { echo "erro: não consegui ler a versão de pyproject.toml" >&2; exit 1; }
# versão Debian: pré-lançamentos PEP 440 (0.2.0rc1) viram 0.2.0~rc1
VERSION="$(printf '%s' "$VERSION" | sed -E 's/([0-9])(a|b|rc|dev)([0-9]*)$/\1~\2\3/')"
[[ "$VERSION" =~ ^[0-9][A-Za-z0-9.+~]*$ ]] || { echo "erro: versão inválida: $VERSION" >&2; exit 1; }

PKG=openmacros-plus
APP_ID=io.github.openmacros.App
MAINTAINER="OpenMacros+ maintainers <contact email>"
HOMEPAGE="https://github.com/<user>/openmacros-plus"
HOMEPAGE_XML="$(printf '%s' "$HOMEPAGE" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g')"
EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"
export SOURCE_DATE_EPOCH="$EPOCH"
RFC_DATE="$(LC_ALL=C date -u -R -d "@$EPOCH")"
ISO_DATE="$(date -u -d "@$EPOCH" +%Y-%m-%d)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ROOT="$WORK/$PKG"
umask 022

inst() { install -D -m "$1" "$2" "$ROOT/$3"; }

# --- código Python (sem __pycache__; testes ficam fora de src/) ---
LIB="$ROOT/usr/lib/python3/dist-packages"
mkdir -p "$LIB"
cp -r "$REPO/src/openmacros" "$LIB/openmacros"
find "$LIB" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$LIB" -name '*.py[co]' -delete
find "$LIB" -type d -exec chmod 755 {} +
find "$LIB" -type f -exec chmod 644 {} +

# --- executáveis ---
mkdir -p "$ROOT/usr/bin"
launcher() { # nome módulo
  cat >"$ROOT/usr/bin/$1" <<LAUNCH
#!/usr/bin/python3
import sys

from $2 import main

sys.exit(main())
LAUNCH
  chmod 755 "$ROOT/usr/bin/$1"
}
launcher openmacrosd openmacros.daemon.main
launcher openmacros openmacros.gui.app
launcher openmacros-tray openmacros.tray.main

# --- unidade systemd de usuário ---
mkdir -p "$ROOT/usr/lib/systemd/user"
sed 's|^ExecStart=.*|ExecStart=/usr/bin/openmacrosd|' "$REPO/data/systemd/openmacrosd.service" \
  >"$ROOT/usr/lib/systemd/user/openmacrosd.service"
chmod 644 "$ROOT/usr/lib/systemd/user/openmacrosd.service"
grep -q '^ExecStart=/usr/bin/openmacrosd$' "$ROOT/usr/lib/systemd/user/openmacrosd.service"

# --- desktop, autostart, ícones, udev ---
inst 644 "$REPO/data/$APP_ID.desktop" "usr/share/applications/$APP_ID.desktop"
inst 644 "$REPO/data/io.github.openmacros.Tray.desktop" "etc/xdg/autostart/io.github.openmacros.Tray.desktop"
inst 644 "$REPO/data/io.github.openmacros.Session.desktop" "etc/xdg/autostart/io.github.openmacros.Session.desktop"
inst 644 "$REPO/data/icons/$APP_ID.svg" "usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
inst 644 "$REPO/data/icons/$APP_ID-symbolic.svg" "usr/share/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
inst 644 "$REPO/data/udev/70-openmacros.rules" "usr/lib/udev/rules.d/70-openmacros.rules"

# --- documentação: copyright (DEP-5), changelog, AppStream ---
DOC="usr/share/doc/$PKG"
mkdir -p "$ROOT/$DOC"
cat >"$ROOT/$DOC/copyright" <<COPYRIGHT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: OpenMacros+
Upstream-Contact: OpenMacros+ maintainers <contact email>
Source: $HOMEPAGE

Files: *
Copyright: OpenMacros+ contributors
License: GPL-3.0+

License: GPL-3.0+
 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.
 .
 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
 .
 On Debian systems, the complete text of the GNU General Public
 License version 3 can be found in "/usr/share/common-licenses/GPL-3".
COPYRIGHT
chmod 644 "$ROOT/$DOC/copyright"

{
  printf '%s (%s) unstable; urgency=medium\n\n' "$PKG" "$VERSION"
  printf '  * Debian package of OpenMacros+ %s. See CHANGELOG.md upstream for details.\n\n' "$VERSION"
  printf ' -- %s  %s\n' "$MAINTAINER" "$RFC_DATE"
} | gzip -9n >"$ROOT/$DOC/changelog.Debian.gz"
chmod 644 "$ROOT/$DOC/changelog.Debian.gz"

mkdir -p "$ROOT/usr/share/metainfo"
cat >"$ROOT/usr/share/metainfo/$APP_ID.metainfo.xml" <<METAINFO
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>$APP_ID</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>OpenMacros+</name>
  <summary>Configure Logitech HID++ 2.0 mice and keyboards on Linux</summary>
  <description>
    <p>OpenMacros+ is an open-source configurator for Logitech mice and keyboards that speak HID++ 2.0. It runs a user service that applies your settings and a GTK4 interface to edit them.</p>
    <p>Features:</p>
    <ul>
      <li>Remap buttons and set gestures</li>
      <li>Per-application profiles (X11)</li>
      <li>Pointer speed, DPI, scrolling and SmartShift</li>
      <li>Easy-Switch between computers</li>
      <li>Smart Actions: If... Then... automations</li>
      <li>Tray icon with battery level</li>
    </ul>
    <p>This is an independent project, not affiliated with Logitech.</p>
  </description>
  <launchable type="desktop-id">$APP_ID.desktop</launchable>
  <url type="homepage">$HOMEPAGE_XML</url>
  <url type="bugtracker">$HOMEPAGE_XML/issues</url>
  <categories>
    <category>Settings</category>
    <category>HardwareSettings</category>
  </categories>
  <provides>
    <binary>openmacros</binary>
    <binary>openmacrosd</binary>
    <binary>openmacros-tray</binary>
  </provides>
  <content_rating type="oars-1.1"/>
  <releases>
    <release version="$VERSION" date="$ISO_DATE"/>
  </releases>
</component>
METAINFO
chmod 644 "$ROOT/usr/share/metainfo/$APP_ID.metainfo.xml"
if command -v appstreamcli >/dev/null; then
  appstreamcli validate --no-net "$ROOT/usr/share/metainfo/$APP_ID.metainfo.xml"
else
  echo "aviso: appstreamcli ausente; metainfo não validado" >&2
fi

# --- DEBIAN/ ---
CTL="$ROOT/DEBIAN"
mkdir -p "$CTL"
chmod 755 "$CTL"
for s in postinst prerm postrm; do
  install -m 755 "$REPO/packaging/deb/$s" "$CTL/$s"
done
printf '/etc/xdg/autostart/io.github.openmacros.Tray.desktop\n/etc/xdg/autostart/io.github.openmacros.Session.desktop\n' >"$CTL/conffiles"
chmod 644 "$CTL/conffiles"

SIZE="$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)"
cat >"$CTL/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: $MAINTAINER
Homepage: $HOMEPAGE
Installed-Size: $SIZE
Depends: python3 (>= 3.12), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), gir1.2-gtk-3.0,
 gir1.2-ayatanaappindicator3-0.1, python3-evdev, python3-pyudev, python3-xlib, xclip | xsel
Recommends: pulseaudio-utils | pipewire-bin, xdg-utils, dbus-user-session, librsvg2-common
Suggests: wl-clipboard
Description: Configurator for Logitech HID++ 2.0 mice and keyboards
 OpenMacros+ configures Logitech mice and keyboards that speak HID++ 2.0
 (Bluetooth and Unifying, Bolt, Lightspeed or Nano receivers) without
 Logitech's software.
 .
 It ships a systemd user service (openmacrosd) that applies the settings, a
 GTK4/libadwaita interface (openmacros) and a tray icon (openmacros-tray).
 Features include button remapping and gestures, per-application profiles
 (X11), pointer and scroll settings, Easy-Switch and Smart Actions.
 .
 The package installs a udev rule granting the logged-in user access to the
 HID++ device and /dev/uinput, and enables the user service for all users.
 Log out and back in after installing. Independent project, not affiliated
 with Logitech.
CONTROL
chmod 644 "$CTL/control"

# md5sums (tudo menos DEBIAN)
( cd "$ROOT" && find . -path ./DEBIAN -prune -o -type f -print0 | sort -z | xargs -0 md5sum | sed 's|  \./|  |' ) >"$CTL/md5sums"
chmod 644 "$CTL/md5sums"

find "$ROOT" -exec touch -h -d "@$EPOCH" {} +

mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
rm -f "$DEB"
dpkg-deb --root-owner-group --build "$ROOT" "$DEB" >/dev/null
echo "$DEB"
