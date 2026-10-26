## What and why

<!-- Describe the change and the problem it solves. Link issues: "Fixes #123". -->

## How it was tested

<!-- Tests added or changed. Hardware used, if any. -->

## Checklist

- [ ] `xvfb-run -a dbus-run-session -- python3 -m pytest -q` passes
- [ ] Tests cover the new or fixed behavior
- [ ] Docs and `CHANGELOG.md` (`[Unreleased]`) updated if behavior changed
- [ ] Commits are small and focused
- [ ] No code, images or text from Logitech, and nothing obtained by disassembling their binaries (clean-room policy in `CONTRIBUTING.md`)
- [ ] No secrets, serial numbers or personal device IDs in the diff
