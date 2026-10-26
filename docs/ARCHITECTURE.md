# Clique — arquitetura

Configurador open source (GPL-3.0-or-later) para mouses e teclados Logitech HID++ 2.0 no Linux.
Python 3.12+, GTK4 + libadwaita (PyGObject), python-evdev.

**Regra de sala limpa:** nenhum código, imagem, fonte ou texto da Logitech entra no repositório.
O protocolo vem de documentação pública HID++ 2.0 e de `~/re/logi-options/docs/m720-protocol.md`
(nossas próprias notas). Arte dos dispositivos: SVGs próprios.

## Processos

```
┌──────────────┐   D-Bus (sessão)   ┌────────────────────────────────────┐   hidraw   ┌────────┐
│ clique (GUI) │ ◀───────────────▶ │ cliqued (serviço de usuário)        │ ◀────────▶ │ mouse  │
│ GTK4/Adw     │                    │  hidpp/   protocolo                 │            └────────┘
└──────────────┘                    │  devices/ gerenciador + config      │   uinput   ┌────────┐
                                    │  actions/ gestos + atalhos (evdev)  │ ─────────▶ │ kernel │
                                    └────────────────────────────────────┘            └────────┘
```

## Layout do código

```
clique/
  pyproject.toml            entry points: clique (GUI), cliqued (serviço)
  src/clique/
    hidpp/                  BACKEND — sem dependência de GTK
      transport.py          descoberta /dev/hidraw* (046d) + leitura/escrita; HidrawTransport e FakeTransport p/ testes
      messages.py           HID++ 1.0 (receptor) e 2.0: short 0x10 (7 B), long 0x11 (20 B), very long 0x12 (64 B)
      receiver.py           Unifying (c52b), Bolt (c548), Nano/Lightspeed; enumera dispositivos pareados (registros 0xB5)
      device.py             dispositivo: ping/versão, root 0x0000, featureset 0x0001, cache de features
      features/             um módulo por feature:
        names.py 0x0005 · battery.py 0x1000/0x1004 · hosts.py 0x1814/0x1815
        reprog.py 0x1B04 · wheel.py 0x2121 · dpi.py 0x2201 · pointer.py 0x2205 · smartshift.py 0x2110/0x2111
      cids.py               nomes legíveis de CIDs (tabela própria)
    daemon/                 BACKEND
      main.py               loop GLib, D-Bus, hotplug (pyudev opcional; senão GLib timeout + rescan)
      manager.py            dispositivos online, aplica config ao conectar/reconectar
      config.py             ~/.config/clique/config.json (atômico)
      gestures.py           máquina de estados de gestos (seção "Gestos")
      actions.py            executa ações via uinput (evdev.UInput) e subprocess
      dbus_service.py       interface abaixo
    gui/                    FRONTEND — só fala com o serviço via D-Bus
      app.py, window.py, dbus_client.py
      pages/ devices.py, buttons.py, pointer.py, easyswitch.py, about.py
      widgets/ device_art.py (SVG + marcadores clicáveis), action_picker.py, key_capture.py
      data/art/*.svg, data/layouts/*.json (posições dos botões por modelo; fallback genérico)
  data/
    udev/70-clique.rules            acesso hidraw 046d p/ grupo plugdev / uaccess
    systemd/cliqued.service         serviço de usuário
    io.github.clique.desktop
  tests/
```

## Contrato D-Bus

Barramento de sessão · nome `io.github.clique` · objeto `/io/github/clique`
· interface `io.github.clique.Manager1`. Estruturas complexas trafegam como **JSON em `s`**.

| Membro | Assinatura | Descrição |
|---|---|---|
| `GetDevices()` | `→ s` | lista JSON de `Device` |
| `GetDevice(s id)` | `→ s` | um `Device` |
| `SetAssignment(s id, q cid, s action)` | `→ b` | grava e aplica `Action` em um botão |
| `SetSetting(s id, s key, s value_json)` | `→ b` | ver chaves abaixo |
| `ChangeHost(s id, y host)` | `→ b` | Easy-Switch (0-based) |
| `ResetDevice(s id)` | `→ b` | remove config e volta botões ao padrão (0x1B04 fn5) |
| `Rescan()` | `→ ()` | força nova varredura |
| `DevicesChanged()` | sinal | conectou/desconectou |
| `DeviceUpdated(s id, s device_json)` | sinal | bateria, host, config mudaram |
| `Error(s id, s message)` | sinal | erro legível para toast |

Erros de D-Bus: `io.github.clique.Error.NotFound`, `.Unsupported`, `.DeviceOffline`, `.InvalidArgument`
e `org.freedesktop.DBus.Error.AccessDenied`.

Segurança: o serviço consulta `GetConnectionCredentials` do remetente e rejeita uid diferente do seu;
chamadores em sandbox Flatpak (`/proc/<pid>/root/.flatpak-info`) só podem usar métodos de leitura.
JSON de entrada limitado a 64 KiB; ações `command` exigem `argv[0]` absoluto ou resolvível no PATH.
Código de saída 73 = nome D-Bus já ocupado (o systemd não reinicia).

### Device (JSON)
```json
{
  "id": "logi:FE90581C",               // "logi:" + unitId (0x0003). Estável entre Bluetooth e receptor.
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
  "layout": "m720"                                                       // nome do layout de arte, ou "generic-mouse"
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
Presets de alto nível que a GUI oferece (traduz para `keys`): copiar, colar, desfazer, refazer,
volume ±, mudo, play/pause, próxima/anterior faixa, área de trabalho anterior/próxima,
mostrar janelas, mostrar área de trabalho, captura de tela, voltar/avançar no navegador.

### Chaves de `SetSetting`
`pointer_speed` (int) · `dpi` (int) · `hires_scroll` (bool) · `scroll_invert` (bool)
· `smartshift` (`{"enabled":bool,"threshold":int}`)

## Gestos
Ao atribuir `gestures` a um CID: 0x1B04 fn3 com divert + rawXY (flags1 = 0x33).
- KeyReport (evento 0) com o CID → início; acumula dx/dy de RawXYReport (evento 1).
- |dx| ou |dy| ≥ threshold e o ângulo dentro de ±30° de um eixo → dispara `left/right/up/down` uma vez
  por pressão.
- Soltou sem disparar → `click`.
- Ações `default` em botões desviados re-emitem o botão original via uinput.

## Persistência
`~/.config/clique/config.json` → `{"version":1,"devices":{"<id>":{"assignments":{...},"settings":{...}}}}`.
Ao reconectar (inclusive após Easy-Switch ou suspensão), o serviço reaplica tudo; os diverts não
persistem no firmware.

## Testes
`FakeTransport` reproduz respostas HID++ gravadas; testes cobrem codec, descoberta de features,
0x1B04, gestos (sequência de eventos → ações) e o serviço D-Bus com o gerenciador simulado.
GUI: `CLIQUE_FAKE=1` sobe o serviço com dispositivos simulados (M720 e um genérico) para
desenvolver e testar sem hardware.
