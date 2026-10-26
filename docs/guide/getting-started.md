# Getting started

## 1. Install

Follow [Install](../../README.md#install) in the README. On Debian, Ubuntu, Kali or Mint the easiest way is the `.deb` from the Releases page:

```sh
sudo apt install ./openmacros-plus_<version>_all.deb
```

Dependencies come with it, and the udev rule and the `openmacrosd` service are already active. Log out and back in, then go to step 2. If you used `scripts/install.sh` before, run `scripts/uninstall.sh` first.

From source instead:

```sh
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  python3-evdev python3-pyudev python3-xlib xclip xsel \
  gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
git clone https://github.com/<user>/openmacros-plus.git
cd openmacros-plus
scripts/install.sh
```

With the source install, run the two `sudo` commands that the script prints (the udev rule), and reconnect your receiver or mouse. Without the rule the service cannot open the device or `/dev/uinput`.

## 2. Check the service

```sh
systemctl --user status openmacrosd
```

It should be `active (running)`. If not, see [Troubleshooting](troubleshooting.md).

## 3. Open the app

```sh
openmacros
```

The interface is in Brazilian Portuguese for now. The home screen lists your connected devices. If none appear, use the menu "Procurar dispositivos".

Click a device to open it. It has four tabs:

| Tab | What it does |
|---|---|
| BOTÕES | Remap buttons and set gestures. Per-app profiles live here too. |
| APONTAR E ROLAR | Pointer speed, DPI, scrolling, SmartShift (what the device supports). |
| EASY-SWITCH | Switch the device to another computer. |
| SOBRE | Model, connection, battery, IDs, and "Restaurar padrões". |

The Smart Actions screen is the button in the top-left of the home screen. Preferences, backup and the "Procurar dispositivos" command are in the menu at the top right.

## 4. Your first remap

1. Open the BOTÕES tab.
2. Click a point on the device image.
3. Pick an action in the side panel, for example "Reproduzir / pausar" (Mídia).
4. Use "Testar" to try it. The change is saved and applied immediately.

To go back, choose "Padrão" for that button.

## 5. The tray icon

`openmacros-tray` starts at login after installation. It shows the lowest battery level, and its menu lists devices, the active profile and Easy-Switch. If you do not see it, see [Troubleshooting](troubleshooting.md#the-tray-icon-does-not-appear).

## No hardware?

```sh
OPENMACROS_FAKE=1 openmacrosd
openmacros
```

This runs simulated devices. Actions are only logged. Stop the real service first with `systemctl --user stop openmacrosd`, because only one instance can own the D-Bus name.

## Next

- [Buttons and gestures](buttons-and-gestures.md)
- [Per-app profiles](app-profiles.md)
- [Smart Actions](smart-actions.md)
