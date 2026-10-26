# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-26

First public release.

### Added

- Debian package (`openmacros-plus_<version>_all.deb`) built by `packaging/deb/build-deb.sh`: code, launchers, systemd user unit, udev rule, desktop, autostart, icons and AppStream metadata. Dependencies are declared, the udev rule and the service are enabled on install.
- Release workflow: a `v*` tag runs the tests, builds the .deb and publishes it with `SHA256SUMS`; CI builds the .deb as an artifact.
- `openmacros.paths`: icon lookup for installed layouts (`/usr/share/openmacros/icons`) as well as the repository checkout.
- HID++ 2.0 support over hidraw for Bluetooth and USB receivers (Unifying, Bolt, Lightspeed, Nano), with device discovery, hotplug and automatic reapply of the configuration on reconnect.
- User service `openmacrosd`, GTK4/libadwaita GUI `openmacros`, and tray icon `openmacros-tray`, connected over the session D-Bus (`io.github.openmacros`).
- Button remapping and gestures (click plus four directions, adjustable threshold).
- Per-application profiles for button actions and pointer/scroll settings (X11), with a catalog of app suggestions.
- Native actions: media (MPRIS), volume, window control, keyboard shortcuts, key sequences, mouse buttons, commands, open app/URL/file, app control, type text (paste or simulated keys), system actions (lock, screenshot, suspend, show desktop, mute microphone, Do Not Disturb on XFCE, empty trash).
- AI action with privacy defaults: clipboard delivery, optional URL delivery, and a heuristic secret detector that blocks URL delivery.
- Smart Actions ("If... Then..."): device-button, keyboard-shortcut, application and device triggers; up to 32 steps; ready-made templates; key recorder; export and import (imports start disabled).
- Point and scroll: pointer speed, DPI, hi-res scrolling, scroll inversion, SmartShift.
- Easy-Switch from the window and the tray.
- Tray icon with battery level, device menu and active profile.
- Notifications and on-screen messages for low battery, profile change, gestures and connection.
- Preferences dialog; configuration backup (export/import, merge or replace).
- Own vector device art, with an optional local import of device images from an installer the user downloaded.
- User install and uninstall scripts, udev rule (hidraw and uinput), systemd user unit.
- Automatic migration of configuration from the former name (Clique).
- Simulated-device mode (`OPENMACROS_FAKE=1`) and a test suite that runs without hardware.
- GitHub Actions CI.

### Known limitations

- Application focus detection and application/shortcut triggers work only on X11.
- "Simular teclas" text mode supports only the US layout.
- The interface is in Brazilian Portuguese only.
- Only the M720 Triathlon is tested on real hardware.

[Unreleased]: https://github.com/J3sussh/OpenMacros/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/J3sussh/OpenMacros/releases/tag/v0.1.0
