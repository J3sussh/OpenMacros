# Per-app profiles

A profile lets a button do something different depending on the focused application.

> Requires X11. On Wayland the focused app is not detected, so only the global profile ("Todos os aplicativos") applies.

## How profiles work

- "Todos os aplicativos" is the global profile. Everything starts here.
- An app profile overrides only what you set. Buttons and settings you leave alone are inherited from the global profile (shown dimmed with "(Todos os apps)").
- The app is identified by its window class in lowercase (for example `firefox`, `code`, `xfce4-terminal`).
- A profile with no assignments and no settings removes itself.

## Create a profile

1. Open the BOTÕES tab.
2. Above the device image, click "+".
3. Search and pick an installed or recently used app. A chip for the app appears.
4. Select the chip, then click a button on the image and choose its action.

To go back to the global behavior for one button, select it and choose "Usar o padrão de Todos os aplicativos".

If the app has a built-in suggestion, "Usar sugestão do catálogo" applies it. Suggestions are examples (for browsers, editors, terminals and more). They are applied only when you click.

## Pointer and scroll per app

With an app chip selected, the APONTAR E ROLAR tab edits that app's overrides. "Usar o padrão" removes an override. The values are written to the device when you switch to that app, and the previous values are restored when you leave.

## Good to know

- Switching windows does not rewrite button settings in the device firmware, so it is fast.
- A button that is "Padrão" in the focused app but remapped elsewhere still sends its original click.
- "remap" (firmware-level) actions apply only in the global profile.
- You can show a message when the profile changes. See Preferences ("Mostrar o perfil ao trocar de aplicativo").
