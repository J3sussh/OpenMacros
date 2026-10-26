# Smart Actions

A Smart Action is an automation: when **Se…** (If) something happens, do **Então…** (Then) a list of actions in order.

Open the screen with the button at the top left of the home screen.

## Screen layout

- **Minhas Smart Actions**: your automations as cards, each with an Ativa/Inativa switch and a menu (edit, duplicate, export, delete). You can sort them.
- **Modelos**: ready-made examples (work mode, meeting mode, ask AI about the selection, and others). "Usar modelo" makes an editable copy.
- **Criar** and **Importar…**.

## Triggers (Se…)

A Smart Action can have up to 5 triggers. Any of them starts it.

| Trigger | When it fires |
|---|---|
| Device button | You press a button you assigned to the Smart Action (globally or in an app profile) |
| Shortcut | A global key combination. X11 only. At least one modifier is required, except F13-F24 and media keys. The shortcut is consumed (other apps do not get it). |
| Application | An app opens, closes or gains focus. X11 only. |
| Device | A device connects or disconnects (includes Easy-Switch changes) |

With no triggers, the Smart Action runs only from a button or "Experimentar".

## Steps (Então…)

Up to 32 steps. A step is an action or a delay (10 to 10000 ms). Categories: Aplicativo, Pressionamento de tecla, Texto, Sistema, Mídia, IA, Atraso, Comando. Drag to reorder.

The key recorder ("Gravar sequência de teclas") records real timing or a fixed 50 ms delay. It only captures keys pressed inside its own dialog, not system-wide.

Use **Experimentar** to run everything now.

## Safety limits

- A disabled Smart Action does not fire from any trigger.
- Each Smart Action fires at most once every 2 seconds, and never while it is already running.
- Actions that a Smart Action starts do not retrigger that same Smart Action for 2 seconds.
- Two Smart Actions that trigger each other are cut off after 6 firings in 30 seconds, and you get an error.

## Share and import

"Exportar…" saves one Smart Action as a file. "Importar…" loads one. **Imported Smart Actions start disabled** so a file from someone else cannot run on its own. Read the steps, then turn it on.

Do not store passwords or sensitive data in Smart Actions. They are saved in plain text in `~/.config/openmacros/config.json`.

## Limits and notes

- If a shortcut cannot be registered (another program uses it, or you are on Wayland) the trigger shows a warning.
- The Do Not Disturb actions work on XFCE only. On other desktops they only write a log line.
