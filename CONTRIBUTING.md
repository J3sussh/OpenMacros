# Contributing to OpenMacros+

Thanks for helping. This page covers setup, tests, style, new devices and bug reports.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Clean-room policy (read first)

OpenMacros+ is a clean-room project. **Do not contribute:**

- code, images, icons, fonts or text from Logitech software;
- anything obtained by disassembling or decompiling Logitech binaries.

Protocol knowledge must come from public documentation (the HID++ 2.0 documents Logitech publishes), from free projects (Solaar, libratbag, logiops), or from black-box tests and packet captures you made on your own hardware. Device art must be your own work (SVG). See [docs/HIDPP-PROTOCOL.md](docs/HIDPP-PROTOCOL.md#11-sources-and-clean-room-policy).

Pull requests that break this policy will be closed.

## Development setup

Requirements are the same as for users (see the [README](README.md#requirements)), plus `pytest`, `xvfb` and `dbus` for tests:

```sh
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
  gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
  python3-evdev python3-pyudev python3-xlib python3-pytest \
  xvfb dbus dbus-x11 xclip
git clone https://github.com/J3sussh/OpenMacros.git
cd openmacros-plus
```

Use the system Python. PyGObject and the GTK typelibs come from apt and do not work in a plain virtualenv.

Run without hardware, with simulated devices (an M720 and a generic mouse):

```sh
OPENMACROS_FAKE=1 PYTHONPATH=src python3 -m openmacros.daemon.main
PYTHONPATH=src python3 -m openmacros.gui     # in another terminal
```

In this mode actions are only logged and the config stays in memory. Use `OPENMACROS_LOG=DEBUG` for verbose logs.

## Running tests

```sh
xvfb-run -a dbus-run-session -- python3 -m pytest -q
```

This is the command CI runs. Tests use a simulated HID++ transport, so no hardware is needed. CI also runs:

```sh
python3 -m compileall -q src tests
for f in scripts/*.sh; do bash -n "$f"; done
shellcheck scripts/*.sh
```

## Building the .deb package

`packaging/deb/build-deb.sh` builds `openmacros-plus_<version>_all.deb` with plain `dpkg-deb` (no debhelper, no root):

```sh
packaging/deb/build-deb.sh [--version X.Y.Z] [--out DIR]   # defaults: version from pyproject.toml, out=dist/
dpkg-deb -I dist/openmacros-plus_*_all.deb                  # control data
dpkg-deb -c dist/openmacros-plus_*_all.deb                  # contents
packaging/deb/smoke-test.sh dist/openmacros-plus_*_all.deb  # extracts (does not install) and runs daemon, GUI and tray
lintian dist/openmacros-plus_*_all.deb                      # optional
```

Never install the result on a development machine just to test it. The maintainer scripts live in `packaging/deb/{postinst,prerm,postrm}`; keep them best-effort (they must not fail in a chroot or container) and never touch users' home directories. `tests/test_deb.py` covers the build. Pushing a tag `v*` runs `.github/workflows/release.yml`, which tests, builds the .deb and publishes it with `SHA256SUMS` as a GitHub Release.

## Style

- Python 3.12+. Keep the `hidpp/` package free of GTK imports.
- The GUI talks to the service only over D-Bus. The tray must never import `openmacros.gui` (GTK 4) because it uses GTK 3.
- Follow the style of the surrounding code. Keep functions small and logic testable without a display.
- User-visible strings in the GUI are currently in Brazilian Portuguese. Keep that until i18n lands.
- Documentation in `docs/guide/` is in English.
- Do not add dependencies without discussing it in an issue.

## Commits and pull requests

- Small, focused commits. One logical change each.
- Write what changed and why in the commit message.
- Every PR needs tests for the behavior it adds or fixes. If it cannot be tested, say why in the PR.
- Run the full test command above before opening the PR.
- Update the docs and `CHANGELOG.md` (under `[Unreleased]`) when behavior changes.

## Adding a device

See [docs/DEVICES.md](docs/DEVICES.md). In short: run with the device connected, collect the device data with the command below, test each function, optionally add a layout and your own SVG art, then open a "Device support" issue or a PR.

## Reporting bugs

Open an issue with the "Bug report" form. Include:

1. What you did, what you expected, what happened.
2. Your distro, desktop, session type (X11 or Wayland) and how the device is connected.
3. The device data:

   ```sh
   busctl --user call io.github.openmacros /io/github/openmacros io.github.openmacros.Manager1 GetDevices
   ```

   Remove serial numbers and the `id` value (`logi:...`) before posting.
4. Service logs:

   ```sh
   systemctl --user status openmacrosd
   journalctl --user -u openmacrosd -b --no-pager | tail -n 200
   ```

   For more detail, stop the service and run `OPENMACROS_LOG=DEBUG openmacrosd` in a terminal.

Do not post secrets. For security problems use [SECURITY.md](SECURITY.md), not a public issue.
