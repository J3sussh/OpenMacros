# Troubleshooting

First collect facts:

```sh
systemctl --user status openmacrosd
journalctl --user -u openmacrosd -b --no-pager | tail -n 100
busctl --user call io.github.openmacros /io/github/openmacros io.github.openmacros.Manager1 GetDevices
```

For verbose logs, stop the service and run it in a terminal:

```sh
systemctl --user stop openmacrosd
OPENMACROS_LOG=DEBUG openmacrosd
```

## The window says the service is not running

```sh
systemctl --user status openmacrosd
systemctl --user enable --now openmacrosd
```

Common causes:

- **Not installed or not started.** Run `scripts/install.sh` again (without `--no-start`).
- **The repository was moved or deleted.** In the default install mode the launchers in `~/.local/bin` run the code from the repository. Run `scripts/install.sh` from the new location.
- **Another instance owns the D-Bus name.** The service exits with code 73 and systemd does not restart it. Make sure you are not running `openmacrosd` by hand (or with `OPENMACROS_FAKE=1`) at the same time.
- **`~/.local/bin` is not in your PATH.** The installer warns about this.
- **Missing X variables.** The service waits for `DISPLAY`. The login autostart (`io.github.openmacros.Session.desktop`) hands it to systemd. You can do it by hand:

  ```sh
  systemctl --user import-environment DISPLAY XAUTHORITY
  systemctl --user restart openmacrosd
  ```

## No device is listed, or "permission denied"

The service reads the device through `/dev/hidraw*`. This needs the udev rule.

```sh
ls /etc/udev/rules.d/70-openmacros.rules
```

If the file is missing:

```sh
sudo install -m 644 data/udev/70-openmacros.rules /etc/udev/rules.d/70-openmacros.rules
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=misc
```

Then unplug and replug the receiver, or turn the mouse off and on, or log out and in. The rule gives access to the logged-in user (`uaccess`). If you are connected over SSH or without a graphical seat, `uaccess` does not apply.

Wired USB devices are not covered by the rule. See the comments in `data/udev/70-openmacros.rules`.

If your device still does not appear, open a "Device support" issue with the output of `GetDevices`.

## Buttons or gestures do nothing (uinput)

Actions that press keys or mouse buttons use `/dev/uinput`.

```sh
ls -l /dev/uinput
getfacl /dev/uinput
```

You should see an ACL entry for your user. If not, install the udev rule (above) and run:

```sh
sudo udevadm trigger --subsystem-match=misc
```

If `/dev/uinput` does not exist, load the module: `sudo modprobe uinput`. To load it at boot, add `uinput` to a file in `/etc/modules-load.d/`.

## Per-app profiles or app triggers do not work

- You are probably on **Wayland**. Focus detection, shortcut triggers and app triggers need X11. Check with `echo $XDG_SESSION_TYPE`. Choose an X11 session at login, or use only the global profile.
- The service needs `DISPLAY`. See "Missing X variables" above.
- The app name may differ from what you expect. Use the "+" list in the profile bar, which shows the real app ids.

## Shortcut trigger shows a warning

Another program already uses that combination, or you are on Wayland. Pick another combination.

## The tray icon does not appear

The tray uses the StatusNotifier / AppIndicator protocol.

- **XFCE 4.16 and later:** the panel's built-in "Status Tray Plugin" (`systray`; "Plug-in da bandeja de status" in Portuguese) shows StatusNotifier/AppIndicator icons, so no extra package is needed. Make sure it is on your panel: right-click the panel, Panel, Add New Items, and choose it. On older XFCE releases the "Notification Area" plugin does not show these icons; there you need the separate Status Notifier plugin, if your distribution still ships it.
- **GNOME:** install the "AppIndicator and KStatusNotifierItem Support" extension.
- Make sure `gir1.2-ayatanaappindicator3-0.1` and `gir1.2-gtk-3.0` are installed.
- Start it by hand to see errors: `openmacros-tray`.

## Notifications do not show

Notifications use `org.freedesktop.Notifications` (for example `xfce4-notifyd`). If no notification service runs, the service only logs. Check Preferences to see which notifications are enabled.

## "Digitar texto" pastes the wrong thing or nothing

The default mode needs `xclip` or `xsel`. Install one: `sudo apt install xclip xsel`.

## Reset a device

Open the SOBRE tab and use "Restaurar padrões". It removes saved configuration for that device, including app profiles.

## Still stuck

Open a bug report and include the `GetDevices` output and logs. See [CONTRIBUTING.md](../../CONTRIBUTING.md#reporting-bugs). Remove serial numbers and the device `id` first.
