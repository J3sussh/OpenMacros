# OpenMacros+ — integrações com aplicativos (extensão do contrato v1)

Quatro recursos: **perfis por aplicativo**, **ações nativas**, **Smart Actions** (macros) e
**ponteiro/rolagem por aplicativo**. Tudo abaixo complementa [ARCHITECTURE.md](../ARCHITECTURE.md); o que não for
citado aqui continua igual.

## 1. Aplicativo em foco (daemon)

`daemon/focus.py` — interface `FocusWatcher` com implementação X11 (python-xlib):
- escuta `PropertyNotify` de `_NET_ACTIVE_WINDOW` na raiz (sem polling); lê `WM_CLASS`
  (instância, classe), `_NET_WM_PID`, `_NET_WM_NAME`; `exe` = basename de `/proc/<pid>/exe`.
- **app_id** = classe do `WM_CLASS` em minúsculas (ex.: `firefox`, `code`, `burp-startburp`,
  `xfce4-terminal`, `qterminal`, `obsidian`, `spotify`). Sem WM_CLASS → `exe`. Sem janela → `""`.
- Debounce de 120 ms; emite só quando o app_id muda.
- Wayland: `NullFocusWatcher` (sempre `""`) + log avisando; a arquitetura fica pronta para
  implementações futuras (GNOME extension / KWin script).
- Toda a lógica de resolução de perfil é pura e testável sem X.

`ActiveApp` (JSON): `{"app_id": "firefox", "wm_class": ["Navigator", "firefox"], "title": "...",
"pid": 1234, "exe": "firefox-esr"}`.

## 2. Perfis por aplicativo

Config por dispositivo:
```json
"devices": {"<id>": {
  "assignments": {...}, "settings": {...},          // perfil global (inalterado)
  "profiles": {
    "firefox": {"assignments": {"83": {...}}, "settings": {"scroll_invert": {"value": true}}}
  }
}}
```
Resolução (pura, `daemon/profiles.py`): para o app em foco, por CID: perfil do app → global →
`default`. Settings: chave do perfil do app sobrepõe a global.

**Sem gravações no firmware ao trocar de janela para botões**: o conjunto de CIDs desviados é a
união dos CIDs com ação ≠ `default`/`remap` em QUALQUER perfil (global ou de app). Num app onde
esse CID é `default`, o daemon re-emite o botão original via uinput (mapa CID → BTN_*/KEY_*: 0x52
BTN_MIDDLE, 0x53 BTN_SIDE, 0x56 BTN_EXTRA, 0x5B/0x5D roda horizontal REL_HWHEEL ±1, 0xD0 sem
equivalente → nada). Ações `remap` só valem no perfil global (são do firmware).
Settings por app (pointer_speed, scroll_invert, hires_scroll, dpi, smartshift) são gravadas no
dispositivo ao trocar de app, com debounce de 300 ms e só se o valor efetivo mudar.

## 3. Ações novas (Action JSON)

```json
{"type": "media",      "op": "play_pause|next|previous|stop", "player": "spotify"}  // MPRIS; player opcional
{"type": "volume",     "op": "up|down|mute", "step": 5}                              // pactl, fallback wpctl
{"type": "open",       "target": "https://… | file:///… | firefox.desktop"}          // URL/arquivo → xdg-open; *.desktop → Gio.DesktopAppInfo
{"type": "type_text",  "text": "…", "method": "paste|keys"}                          // method opcional (padrão paste); máx 2000 chars
{"type": "window",     "op": "close|minimize|maximize|fullscreen|next|previous"}     // EWMH via python-xlib
{"type": "ai_prompt",  "service": "claude|chatgpt|perplexity|gemini", "template": "Explique: {selection}",
                       "delivery": "clipboard|url"}                                  // delivery opcional
{"type": "smart_action", "id": "sa_ab12cd"}
```
- `type_text`: por padrão (`method: "paste"`) cola via área de transferência — põe o texto no
  CLIPBOARD, envia Ctrl+V (Ctrl+Shift+V em terminais) e restaura o CLIPBOARD anterior ~600 ms depois;
  funciona com acentos e qualquer layout. `method: "keys"` digita tecla a tecla via uinput e só
  conhece o layout **US** (não há suporte a ABNT2 nem a outros layouts); caracteres sem mapeamento
  são ignorados com log. Detalhes em [V2.md](V2.md) (B1).
- `ai_prompt`: lê a seleção PRIMARY (python-xlib ou `xclip -o -selection primary`, timeout 300 ms,
  máx 8 KiB) e troca `{selection}` no template (máx 4000 chars). A entrega depende de `delivery`
  (ausente → preferência `ai_delivery_default`, padrão `clipboard`):
  - `clipboard` (padrão): copia o prompt para o CLIPBOARD e abre só a página inicial do serviço
    (`https://claude.ai/new`, `https://chatgpt.com/`, `https://www.perplexity.ai/`,
    `https://gemini.google.com/app`); o usuário cola com Ctrl+V.
  - `url` (opcional): põe o prompt na URL (`https://claude.ai/new?q=…`, `https://chatgpt.com/?q=…`,
    `https://www.perplexity.ai/search?q=…`) — fica no histórico do navegador. `gemini` não tem
    parâmetro de URL e sempre usa a área de transferência.
  - Se o detector de segredos (`daemon/secrets.py`) acusar algo na seleção, a entrega é **forçada**
    para `clipboard` (com notificação), mesmo com `delivery: "url"`.
  Nada é enviado a nenhum serviço sem o usuário ver a página aberta. Detalhes em [V2.md](V2.md) (B2).
- Ações posteriores (`app`, `key_sequence`, `system`) estão em [SMART_ACTIONS.md](SMART_ACTIONS.md) §3.
- Ações que gravam/rodam continuam sujeitas às regras de autorização do D-Bus.

## 4. Smart Actions (macros)

> Substituído. O formato v1 descrito originalmente aqui foi estendido (gatilhos, `enabled`,
> descrição, estatísticas, novas ações); a especificação atual está em
> [SMART_ACTIONS.md](SMART_ACTIONS.md). Entradas v1 continuam aceitas e recebem padrões.

## 5. D-Bus — membros novos em `io.github.openmacros.Manager1`

| Membro | Assinatura | Descrição |
|---|---|---|
| `GetActiveApp()` | `→ s` | ActiveApp JSON |
| `GetRecentApps()` | `→ s` | lista JSON de ActiveApp vistos nesta sessão (máx 30, mais recente primeiro) |
| `SetProfileAssignment(s id, s app_id, q cid, s action)` | `→ b` | `app_id == ""` = global (equivale a SetAssignment) |
| `SetProfileSetting(s id, s app_id, s key, s value_json)` | `→ b` | idem para settings; `value_json == "null"` remove a sobreposição |
| `RemoveProfile(s id, s app_id)` | `→ b` | apaga o perfil do app |
| `GetSmartActions()` | `→ s` | objeto JSON `{id: SmartAction}` |
| `SaveSmartAction(s json)` | `→ s` | cria (sem `id`) ou atualiza; devolvia o id — hoje devolve `{"id","warnings"}` ([SMART_ACTIONS.md](SMART_ACTIONS.md) §4) |
| `DeleteSmartAction(s id)` | `→ b` | remove; atribuições que apontam para ela viram `default` |
| `RunAction(s action)` | `→ b` | executa uma ação já (botão "Testar" da GUI) |
| `ActiveAppChanged(s app_json)` | sinal | |
| `SmartActionsChanged()` | sinal | |

Device JSON ganha:
```json
"profiles": {"firefox": {"assignments": {...}, "settings": {...}}},
"active_profile": "firefox"          // app_id cujo perfil está valendo agora, ou "" (global)
```

## 6. Catálogo de apps (GUI, dados nossos)

`gui/data/apps.json`: app_id → nome, aliases de WM_CLASS/desktop id e **sugestões** de
atribuição (aplicadas só quando o usuário clica "Usar sugestões"). Primeira leva:

| Grupo | Apps (app_id) | Sugestões de exemplo |
|---|---|---|
| Navegador | firefox, firefox-esr, chromium, google-chrome, brave-browser | inclinar roda = aba anterior/próxima (Ctrl+PgUp/PgDn); gestos: ←/→ voltar/avançar, ↑ nova aba, ↓ fechar aba, clique = reabrir aba fechada |
| Editor | code, codium | voltar/avançar = navegar para trás/frente (Ctrl+Alt+-/Ctrl+Shift+-); gestos: ↑ paleta (Ctrl+Shift+P), ↓ terminal (Ctrl+`), ←/→ aba de editor anterior/próxima, clique = ir para definição (F12) |
| Terminal | xfce4-terminal, qterminal, gnome-terminal-server, kitty, alacritty, konsole, terminator | roda = colar seleção (Shift+Insert); voltar/avançar = aba anterior/próxima; gestos: ↑ nova aba, ↓ fechar aba |
| Pentest | burp-startburp (Burp Suite), wireshark, zaproxy | Burp: avançar = enviar ao Repeater (Ctrl+R), voltar = enviar ao Intruder (Ctrl+I), gesto ↑ = Send (Ctrl+Space) |
| Mídia | spotify, vlc, rhythmbox | inclinar roda = faixa anterior/próxima (media), roda = play/pause |
| IA | (navegador com claude.ai/chatgpt) + ação global | gesto ↑ global opcional = "Perguntar à IA sobre a seleção" (ai_prompt) |
| Produtividade | obsidian, libreoffice-writer/calc, thunderbird, slack, discord | Obsidian: voltar/avançar = navegação; Calc: inclinar roda = rolagem horizontal |

Ícones e nomes dos apps vêm do sistema (Gio.AppInfo), não do repositório.

## 7. GUI

- Barra acima da foto na aba BOTÕES: seletor de perfil “Todos os aplicativos” + chips dos apps
  com perfil (ícone do app) + botão “+” que abre a lista de apps instalados/recentes (busca).
- Com um app selecionado, hotspots mostram a ação efetiva; botões herdados do global aparecem
  esmaecidos com “(Todos os apps)”; painel lateral tem “Usar o padrão de Todos os aplicativos”.
- Aba APONTAR E ROLAR também respeita o perfil selecionado (sobreposição por app).
- Painel de ações ganha seções: **Mídia** (MPRIS), **Sistema** (volume, janela, abrir app/URL,
  digitar texto), **IA** (perguntar à IA sobre a seleção, com escolha de serviço e template),
  **Smart Actions** (lista + “Criar Smart Action…”), cada item com botão “Testar”.
- Nova tela **Smart Actions** (ícone no cabeçalho da tela inicial): lista, editor de passos
  (adicionar ação/atraso, reordenar por arrastar, testar), modelos prontos.
- Indicador discreto do app em foco no topo (“Perfil ativo: Firefox”) via `ActiveAppChanged`.

## 8. Notas de implementação do backend (desvios e esclarecimentos)

- **Formato de settings em perfis**: igual ao do Device JSON (`{"value": v}`; smartshift
  `{"enabled","threshold"}`). `SetProfileSetting` recebe o valor cru (como `SetSetting`).
- **Remover sobreposição de botão**: `SetProfileAssignment(id, app, cid, "null")` apaga a ação do CID
  no perfil (volta a herdar do global). `{"type":"default"}` num perfil é um `default` explícito
  (re-emite o botão original mesmo que o global tenha outra ação). `remap` em perfil de app é rejeitado.
- **Baseline de settings**: ao entrar num perfil que sobrepõe uma chave sem valor global, o valor atual
  do dispositivo é guardado em `devices.<id>.baseline` e restaurado ao sair do perfil.
- **`RemoveProfile`** devolve `false` se o perfil não existia; `DeleteSmartAction` devolve `false` se o id não existia.
- **`RunAction`** não aceita `gestures`, `change_host`, `remap`, `default`, `disabled`.
- **Smart Action em `SaveSmartAction`**: com `id` inexistente → `NotFound`; o objeto devolvido por
  `GetSmartActions` inclui `id` em cada entrada.
- **`type_text`** com `method: "keys"`: só layout US (ABNT2 não implementado); caracteres sem mapeamento são
  ignorados com log. O padrão `paste` não depende de layout.
- **`window`**: `minimize` usa `WM_CHANGE_STATE` (ICCCM); `next`/`previous` percorrem a pilha
  (`next` = por recência, `previous` = alterna com a anterior), ignorando docks/skip-taskbar.
- **MPRIS/volume** são chamadas síncronas curtas (timeout 0,5 s / 1,5 s) no loop principal.
- **`DebugSetActiveApp(s)`** existe apenas com `OPENMACROS_FAKE=1` (não aparece na introspecção em modo real);
  nesse modo as ações são registradas em log (`RecordingExecutor`), sem uinput/pactl/xdg-open.
- Novos métodos que gravam/executam passam por `authorize()` (uid + não-Flatpak).
