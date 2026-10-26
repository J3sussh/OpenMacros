# OpenMacros+ — arquitetura

Configurador open source (GPL-3.0-or-later) para mouses e teclados Logitech HID++ 2.0 no Linux.
Python 3.12+, GTK4 + libadwaita (PyGObject), python-evdev.

**Regra de sala limpa:** nenhum código, imagem, fonte ou texto da Logitech entra no repositório.
O protocolo vem de documentação pública HID++ 2.0, de projetos livres (Solaar, libratbag, logiops) e de
testes de caixa-preta com hardware do autor; a especificação está em [HIDPP-PROTOCOL.md](HIDPP-PROTOCOL.md)
(em inglês). Arte dos dispositivos: SVGs próprios.

## Processos

```
┌──────────────────┐                     ┌─────────────────────────────────────┐   hidraw   ┌────────┐
│ openmacros       │   D-Bus (sessão)    │ openmacrosd (serviço systemd --user)│ ◀────────▶ │ mouse/ │
│ GUI GTK4/Adw     │ ◀────────────────▶ │  hidpp/   protocolo HID++           │            │ teclado│
└──────────────────┘                     │  daemon/  gerenciador, config,      │            └────────┘
┌──────────────────┐                     │           perfis, gestos, ações,    │   uinput   ┌────────┐
│ openmacros-tray  │ ◀────────────────▶ │           Smart Actions, D-Bus      │ ─────────▶ │ kernel │
│ GTK3+AppIndicator│                     └─────────────────────────────────────┘            └────────┘
└──────────────────┘                        X11 (python-xlib): app em foco, atalhos globais, janelas
```

A GUI (GTK4) e a bandeja (GTK3, processo separado — as duas versões de GTK não convivem num processo)
só conversam com o serviço via D-Bus. O serviço é o único que abre `/dev/hidraw*` e `/dev/uinput`.

## Layout do código

```
pyproject.toml              entry points: openmacrosd (serviço), openmacros (GUI), openmacros-tray (bandeja)
src/openmacros/
  __init__.py
  migrate.py                migração única de diretórios do nome antigo do projeto (Clique)
  vendor_assets.py          importador local e opcional de imagens de dispositivos (ver README)
  hidpp/                    BACKEND — sem dependência de GTK
    transport.py            descoberta /dev/hidraw* (046d) + leitura/escrita; HidrawTransport e FakeTransport p/ testes
    messages.py             HID++ 1.0 (receptor) e 2.0: short 0x10 (7 B), long 0x11 (20 B), very long 0x12 (64 B)
    channel.py              canal de requisição/resposta sobre um transporte
    receiver.py             Unifying, Bolt, Nano/Lightspeed; enumera dispositivos pareados (registro 0xB5)
    device.py               dispositivo: ping/versão, root 0x0000, featureset 0x0001, 0x0003 (unitId), cache de features
    cids.py                 nomes legíveis de CIDs (tabela própria)
    fake.py                 dispositivo HID++ simulado (testes)
    features/               um módulo por feature:
      names.py 0x0005 · battery.py 0x1000/0x1004 · hosts.py 0x1814/0x1815
      reprog.py 0x1B04 · wheel.py 0x2121 · dpi.py 0x2201 · pointer.py 0x2205 · smartshift.py 0x2110/0x2111
  daemon/                   BACKEND
    main.py                 ponto de entrada openmacrosd: loop GLib, D-Bus, hotplug (pyudev opcional; senão rescan periódico)
    manager.py              dispositivos online, aplica config ao conectar/reconectar, API do serviço
    hidpp_backend.py        dispositivos reais via hidraw (RealDevice, HidppBackend)
    fake.py                 dispositivos simulados (OPENMACROS_FAKE=1)
    config.py               ~/.config/openmacros/config.json (escrita atômica; migra ~/.config/clique, cópia única)
    profiles.py             resolução de perfis por aplicativo (puro)
    focus.py                aplicativo em foco (X11; Null em Wayland/sem DISPLAY)
    gestures.py             máquina de estados de gestos e roteamento de botões desviados (puro)
    actions.py              validação e execução de ações (uinput via evdev, subprocess, MPRIS, EWMH, Smart Actions)
    integrations.py         backends das ações nativas (MPRIS, volume, abrir, janelas, seleção/clipboard, IA)
    smart.py                Smart Actions v2: formato, migração, gatilhos (puro)
    triggers.py             gatilhos das Smart Actions (atalho global, aplicativo, dispositivo)
    xtriggers.py            parte X11 dos gatilhos (XGrabKey, _NET_CLIENT_LIST)
    secrets.py              detector de segredos (puro) usado por ai_prompt e avisos de Smart Actions
    labels.py               rótulos legíveis de ações (OSD e sinal ActionTriggered)
    notify.py               notificações/OSD (org.freedesktop.Notifications) e alertas de bateria
    preferences.py          preferências globais: padrões e validação
    backup.py               exportação/importação da configuração
    session_env.py          adoção tardia de DISPLAY/XAUTHORITY (serviço sobe antes do login gráfico)
    timers.py               agendamento (GLib; ManualScheduler nos testes)
    dbus_service.py         interface D-Bus abaixo
  gui/                      FRONTEND — só fala com o serviço via D-Bus
    app.py, __main__.py     Adw.Application (io.github.openmacros.App)
    window.py, context.py, dbus_client.py, toasts.py, apps.py
    logic.py                lógica pura (ações, atalhos, layouts, textos), testável sem display
    pages/                  devices.py (tela inicial), device.py, buttons.py, pointer.py, easyswitch.py,
                            about.py, smart.py (Smart Actions)
    widgets/                action_panel.py, app_picker.py, device_art.py, fileio.py, imaging.py,
                            import_dialog.py, key_capture.py, key_recorder.py, preferences.py,
                            profile_bar.py, risk_dialog.py, smart_dialogs.py
    data/                   style.css, apps.json (catálogo de apps), art/*.svg, layouts/*.json
  tray/                     bandeja (GTK3 + AyatanaAppIndicator3), processo separado
    main.py, __main__.py    executável openmacros-tray
    client.py               cliente D-Bus mínimo (Gio)
    model.py                lógica pura (ícone, rótulos, menor bateria)
data/
  udev/70-openmacros.rules              acesso (uaccess) ao nó hidraw HID++ da Logitech e a /dev/uinput
  systemd/openmacrosd.service           serviço de usuário
  io.github.openmacros.App.desktop      lançador da GUI
  io.github.openmacros.Tray.desktop     autostart da bandeja
  io.github.openmacros.Session.desktop  autostart que entrega DISPLAY/XAUTHORITY ao serviço
  icons/io.github.openmacros.App{,-symbolic}.svg
scripts/install.sh, scripts/uninstall.sh   instalação de usuário (sem sudo; a regra udev é só impressa)
tests/                      testes (tests/gui: lógica e telas da GUI)
docs/design/                contratos de design: INTEGRATIONS.md, SMART_ACTIONS.md, V2.md
```

## Contrato D-Bus

Barramento de sessão · nome `io.github.openmacros` · objeto `/io/github/openmacros`
· interface `io.github.openmacros.Manager1`. Estruturas complexas trafegam como **JSON em `s`**.
Detalhes de cada grupo nos contratos de design: [INTEGRATIONS.md](design/INTEGRATIONS.md) §5,
[SMART_ACTIONS.md](design/SMART_ACTIONS.md) §4 e [V2.md](design/V2.md) B6.

**Dispositivos**

| Membro | Assinatura | Descrição |
|---|---|---|
| `GetDevices()` | `→ s` | lista JSON de `Device` |
| `GetDevice(s id)` | `→ s` | um `Device` |
| `SetAssignment(s id, q cid, s action)` | `→ b` | grava e aplica `Action` em um botão (perfil global) |
| `SetSetting(s id, s key, s value_json)` | `→ b` | ver chaves abaixo |
| `ChangeHost(s id, y host)` | `→ b` | Easy-Switch (0-based) |
| `ResetDevice(s id)` | `→ b` | remove config e volta botões ao padrão (0x1B04 fn5) |
| `Rescan()` | `→ ()` | força nova varredura |

**Perfis por aplicativo**

| Membro | Assinatura | Descrição |
|---|---|---|
| `GetActiveApp()` | `→ s` | `ActiveApp` JSON do app em foco |
| `GetRecentApps()` | `→ s` | lista JSON de `ActiveApp` vistos nesta sessão |
| `GetRunningApps()` | `→ s` | lista JSON de `ActiveApp` com janela aberta |
| `SetProfileAssignment(s id, s app_id, q cid, s action)` | `→ b` | `app_id == ""` = global; `action == "null"` remove a sobreposição |
| `SetProfileSetting(s id, s app_id, s key, s value_json)` | `→ b` | idem para settings |
| `RemoveProfile(s id, s app_id)` | `→ b` | apaga o perfil do app (`false` se não existia) |

**Ações e Smart Actions**

| Membro | Assinatura | Descrição |
|---|---|---|
| `RunAction(s action)` | `→ b` | executa uma ação já (botão "Testar") |
| `GetSmartActions()` | `→ s` | objeto JSON `{id: SmartAction}` |
| `SaveSmartAction(s json)` | `→ s` | cria/atualiza; devolve `{"id":…,"warnings":[…]}` |
| `SetSmartActionEnabled(s id, b enabled)` | `→ b` | liga/desliga |
| `DeleteSmartAction(s id)` | `→ b` | remove; atribuições que apontam para ela viram `default` |
| `ExportSmartAction(s id)` | `→ s` | JSON portátil (sem id/estatísticas) |
| `ImportSmartAction(s json)` | `→ s` | valida, cria com id novo, devolve o id |

**Preferências e backup**

| Membro | Assinatura | Descrição |
|---|---|---|
| `GetPreferences()` | `→ s` | preferências globais (com padrões) |
| `SetPreference(s key, s value_json)` | `→ b` | valida tipo/faixa |
| `ExportConfig()` | `→ s` | backup JSON |
| `ImportConfig(s json, b merge)` | `→ b` | restaura (mescla ou substitui); limite 512 KiB |

**Sinais**

| Sinal | Assinatura | Quando |
|---|---|---|
| `DevicesChanged` | `()` | conectou/desconectou |
| `DeviceUpdated` | `(s id, s device_json)` | bateria, host, config mudaram |
| `Error` | `(s id, s message)` | erro legível para toast |
| `ActiveAppChanged` | `(s app_json)` | app em foco mudou |
| `SmartActionsChanged` | `()` | Smart Actions criadas/alteradas/removidas |
| `SmartActionTriggered` | `(s id, s trigger_json)` | um gatilho disparou uma Smart Action |
| `ActionTriggered` | `(s id, q cid, s label)` | botão/gesto executou uma ação (rótulo legível) |
| `PreferencesChanged` | `(s prefs_json)` | preferências mudaram |

Só com `OPENMACROS_FAKE=1` existe também `DebugSetActiveApp(s app_id) → ()` (não aparece na
introspecção em modo real).

Erros de D-Bus: `io.github.openmacros.Error.NotFound`, `.Unsupported`, `.DeviceOffline`, `.InvalidArgument`,
`org.freedesktop.DBus.Error.AccessDenied` e `org.freedesktop.DBus.Error.Failed` (erro interno).

Segurança: o serviço consulta `GetConnectionCredentials` do remetente e rejeita uid diferente do seu;
chamadores em sandbox Flatpak (`/proc/<pid>/root/.flatpak-info`) só podem usar métodos de leitura
(todo método que grava, executa ou importa é de escrita). JSON de entrada limitado a 64 KiB (512 KiB em
`ImportConfig`); ações `command` exigem `argv[0]` absoluto ou resolvível no PATH.
Código de saída 73 = nome D-Bus já ocupado (o systemd não reinicia).

### Device (JSON)
```json
{
  "id": "logi:1A2B3C4D",               // "logi:" + unitId (0x0003). Estável entre Bluetooth e receptor.
                                       // Fallback (unitId ausente/zerado): "logi:" + serial do receptor (0xB5) + índice,
                                       // ou "logi:" + PID + índice
  "name": "M720 Triathlon",
  "model_id": "405e",                  // PID do dispositivo no modo atual: wpid (registro 0xB5 / notificação 0x41)
                                       // atrás de receptor; PID do hidraw em BT/USB. Nunca o PID do receptor.
  "kind": "mouse",                     // mouse | keyboard | trackball | touchpad | other
  "connection": "receiver",            // receiver | bluetooth | usb
  "online": true,
  "battery": {"level": 80, "status": "discharging", "approximate": true}, // ou null
  "features": ["0x0000", "0x0001", "0x1b04", "..."],
  "controls": [
    {"cid": 208, "name": "Botão de gestos", "remappable": true, "divertable": true,
     "raw_xy": true, "default_task": 156}   // raw_xy: só botões de gestos conhecidos (0xC3/0xD0) E capazes de rawXY
  ],
  "settings": {
    "pointer_speed": {"value": 256, "min": 1, "max": 512},              // 0x2205, opcional
    "dpi":           {"value": 1000, "choices": [400, 800, 1000]},     // 0x2201, opcional
    "hires_scroll":  {"value": true},                                   // 0x2121, opcional
    "scroll_invert": {"value": false},                                  // 0x2121, opcional
    "smartshift":    {"enabled": true, "threshold": 30}                 // 0x2110/2111, opcional
  },
  "hosts": {"count": 3, "current": 0, "names": ["..."]},                // 0x1814, opcional; "names" só se o firmware informar
  "assignments": {"208": {"type": "gestures", "...": "..."}},          // chaves = CID em texto
  "layout": "m720",                                                      // m720 | generic-mouse | generic-keyboard
  "profiles": {"firefox": {"assignments": {...}, "settings": {...}}},   // perfis por aplicativo
  "active_profile": "firefox"                                            // app_id do perfil valendo agora, ou ""
}
```
Configuração ausente na feature = chave omitida (a GUI esconde o controle).

### Action (JSON)
```json
{"type": "default"}                                   // comportamento de fábrica (sem divert)
{"type": "disabled"}
{"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}   // nomes evdev, pressionados em ordem
{"type": "mouse_button", "button": "BTN_MIDDLE"}
{"type": "remap", "cid": 82}                          // remap nativo no firmware (0x1B04 remap)
{"type": "command", "argv": ["xdg-open", "https://..."]}
{"type": "change_host", "host": 1}
{"type": "gestures", "click": Action, "up": Action, "down": Action, "left": Action, "right": Action,
 "threshold": 50}                                     // só p/ controles com raw_xy
```
Ações nativas (`media`, `volume`, `open`, `type_text`, `window`, `ai_prompt`, `smart_action`) estão em
[INTEGRATIONS.md](design/INTEGRATIONS.md) §3; `app`, `key_sequence` e `system` em
[SMART_ACTIONS.md](design/SMART_ACTIONS.md) §3.
Presets de alto nível que a GUI oferece (traduz para `keys`): copiar, colar, desfazer, refazer,
volume ±, mudo, play/pause, próxima/anterior faixa, área de trabalho anterior/próxima,
mostrar janelas, mostrar área de trabalho, captura de tela, voltar/avançar no navegador.

### Chaves de `SetSetting`
`pointer_speed` (int) · `dpi` (int) · `hires_scroll` (bool) · `scroll_invert` (bool)
· `smartshift` (`{"enabled":bool,"threshold":int}`)

## Gestos
Detalhes do protocolo em [HIDPP-PROTOCOL.md](HIDPP-PROTOCOL.md#10-gesture-engine). Ao atribuir `gestures` a um CID: 0x1B04 fn3 com divert + rawXY (flags1 = 0x33).
- KeyReport (evento 0) com o CID → início; acumula dx/dy de RawXYReport (evento 1).
- |dx| ou |dy| ≥ threshold e o ângulo dentro de ±30° de um eixo → dispara `left/right/up/down` uma vez
  por pressão.
- Soltou sem disparar → `click`.
- Ações `default` em botões desviados re-emitem o botão original via uinput.

## Persistência
`~/.config/openmacros/config.json` (ou `$OPENMACROS_CONFIG`) →
`{"version":1,"devices":{"<id>":{"assignments":{...},"settings":{...},"profiles":{...}}},"smart_actions":{...},"preferences":{...}}`.
Na primeira execução, se existir `~/.config/clique/` (nome antigo do projeto) e ainda não existir
`~/.config/openmacros/`, o diretório é copiado (o antigo é mantido).
Ao reconectar (inclusive após Easy-Switch ou suspensão), o serviço reaplica tudo; os diverts não
persistem no firmware.

## Testes
`FakeTransport` reproduz respostas HID++ gravadas; testes cobrem codec, descoberta de features,
0x1B04, gestos (sequência de eventos → ações) e o serviço D-Bus com o gerenciador simulado.
GUI: `OPENMACROS_FAKE=1` sobe o serviço com dispositivos simulados para desenvolver e testar sem
hardware (config só em memória; ações apenas registradas em log). `OPENMACROS_LOG` define o nível de log.
