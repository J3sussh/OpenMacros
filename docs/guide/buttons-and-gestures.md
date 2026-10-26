# Buttons and gestures

## Remapping a button

On the BOTÕES tab, click a marker on the device image. The side panel lists actions in sections:

| Section | Examples |
|---|---|
| Recomendadas | Padrão, Gestos (gesture button only), show windows |
| Navegação | Browser back/forward, previous/next desktop |
| Mídia | Play/pause, next, previous, stop |
| Edição | Copy, paste, undo, redo |
| Sistema | Volume, window control, open app/site/file, control an app, type text, screenshot, lock, suspend, mic mute, Do Not Disturb (XFCE only), empty trash |
| IA | Ask AI about the selection |
| Smart Actions | Your Smart Actions, plus "Criar Smart Action…" |
| Avançado | Keyboard shortcut, record a key sequence, mouse button, run a command, switch computer, disable |

Every item with parameters has a "Testar" button so you can try it before relying on it.

"Padrão" restores the factory behavior of the button. "Desativar" makes it do nothing.

## Gestures

The gesture button (on the M720 it is the thumb button) can act as five inputs: click, up, down, left and right.

1. Click the gesture button's marker.
2. Choose "Gestos".
3. Assign an action to each direction and to the click.
4. Adjust "SENSIBILIDADE" (how far you move the mouse before a direction fires).

How it works: hold the button and move the mouse. When the movement reaches the threshold along an axis, the matching direction fires once per press. If you release without moving far enough, it counts as a click.

When a gesture fires you can get an on-screen message such as "Gesto ↑ — Nova aba". Turn this on or off in Preferences.

## Typing text

"Digitar texto" types text up to 2000 characters. The default mode pastes the text, so any Unicode works. It temporarily uses the clipboard and restores it afterward (if it held text). In terminals it uses Ctrl+Shift+V.

The advanced option "Simular teclas (layout US)" sends key presses instead. It works only with the US layout.

## Asking AI about the selection

"Perguntar à IA sobre a seleção" reads your current selection, builds a prompt from your template (use `{selection}` where the text goes) and opens the chosen service. By default the prompt is copied to the clipboard and you paste it with Ctrl+V. Nothing goes in the URL. If the selection looks like a secret, the prompt is never put in a URL. The detector is heuristic: do not rely on it for sensitive text.

## Point and scroll

The APONTAR E ROLAR tab shows only what the device supports: pointer speed, DPI, hi-res scrolling, scroll inversion and SmartShift. Per-app overrides are covered in [Per-app profiles](app-profiles.md).
