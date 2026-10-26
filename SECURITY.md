# Security policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Report privately. Do not open a public issue.

Use GitHub Security Advisories: open the repository's **Security** tab and choose **Report a vulnerability** (`https://github.com/J3sussh/OpenMacros/security/advisories/new`).

Please include:

- affected version or commit;
- steps to reproduce, or a proof of concept;
- the impact you expect;
- your distro and session type (X11 or Wayland), if relevant.

Expect an acknowledgement in a few days. This is a volunteer project, so there is no fixed response SLA. We will agree on a disclosure date with you after a fix is ready.

## Scope

In scope:

- **The D-Bus daemon** (`io.github.openmacros`): authorization (same-uid check, read-only access for Flatpak callers), input validation, size limits.
- **uinput**: the daemon can inject keyboard and mouse events. Any way for an unprivileged or other-user caller to trigger this is in scope.
- **Backup import** (`ImportConfig`, `ImportSmartAction`): malformed or malicious files that cause code execution, crashes or state corruption.
- **Command execution**: `command` actions, Smart Actions, and anything that runs programs on the user's behalf.
- **The udev rule and the install/uninstall scripts**: privilege or file-overwrite problems.

Out of scope:

- Actions that a user deliberately configures to run their own commands.
- Weaknesses in the secret detector that only mean it misses a secret. It is heuristic and documented as such.
- Problems in third-party software (GTK, systemd, browsers, AI services) or in device firmware.
- Attacks that require an attacker who already runs code as the same user.
