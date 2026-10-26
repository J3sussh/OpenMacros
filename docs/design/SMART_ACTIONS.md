# OpenMacros+ — Smart Actions v2 ("Se… Então…")

Substitui [INTEGRATIONS](INTEGRATIONS.md) §4 (o formato antigo continua sendo lido e é migrado). Modelo de produto
inspirado no Options+: **gatilhos** ("Se…") disparam uma lista de **ações** ("Então…"). Textos, ícones,
modelos e código são nossos (sala limpa).

## 1. Formato (config global `smart_actions`)
```json
"sa_ab12cd": {
  "name": "Modo reunião", "description": "Silencia o microfone e as notificações",
  "icon": "camera-video-symbolic", "enabled": true,
  "triggers": [ Trigger, ... ],              // 0..5; vazio = só por botão/Experimentar
  "steps":    [ Action | {"type":"delay","ms":500}, ... ],   // 1..32
  "stats": {"runs": 0, "last_run": null, "created": "ISO8601", "modified": "ISO8601"}  // só leitura
}
```
Migração: entradas sem `triggers`/`enabled`/`description`/`stats` recebem padrões; versão do
config inalterada.

## 2. Gatilhos (`Trigger`)
| JSON | Quando dispara | Implementação |
|---|---|---|
| `{"type":"shortcut","keys":["KEY_LEFTCTRL","KEY_LEFTALT","KEY_P"]}` | combinação global de teclado | X11 `XGrabKey` na raiz (python-xlib), registrando variantes com NumLock/CapsLock; falha (BadAccess/combinação já usada) → `trigger_errors` + sinal `Error`. Ao menos 1 modificador (Ctrl/Alt/Super/Shift) exceto F13–F24/teclas de mídia. Wayland: indisponível (`trigger_errors`). |
| `{"type":"app","event":"open"\|"close"\|"focus","app_id":"firefox"}` | 1ª janela do app aparece / última some / app ganha o foco | `_NET_CLIENT_LIST` (PropertyNotify na raiz) → conjunto de app_ids com janela (mesma regra de app_id do FocusWatcher); `focus` reaproveita `ActiveAppChanged`. Estado inicial ao subir o serviço NÃO dispara `open`. |
| `{"type":"device","event":"connect"\|"disconnect","device_id":"logi:…"\|"*"}` | dispositivo fica online/offline | eventos do manager (inclui volta do Easy-Switch). |

O gatilho "botão do dispositivo" continua sendo uma atribuição `{"type":"smart_action","id":…}` num
CID (global ou perfil de app), feita pela GUI com `SetProfileAssignment` — não fica em `triggers`.

**Proteções:** Smart Action desativada (`enabled:false`) não dispara por nenhum gatilho (Experimentar
continua funcionando); cada Smart Action dispara por gatilho no máx. 1×/2 s e nunca enquanto já
executa; ações disparadas por uma Smart Action não geram gatilhos `app`/`device` para ela mesma
durante a execução + 2 s (evita laço "ao abrir Firefox → abrir Firefox").

## 3. Ações novas (valem em Smart Actions, botões e `RunAction`)
```json
{"type":"app","op":"open"|"close"|"focus","target":"firefox.desktop"|"firefox"}
   // open: igual a "open" (.desktop/Gio); close: _NET_CLOSE_WINDOW em todas as janelas do app_id;
   // focus: _NET_ACTIVE_WINDOW na janela mais recente do app (abre se não houver)
{"type":"key_sequence","events":[{"key":"KEY_A","down":true,"delay_ms":0}, …]}
   // gravada na GUI; máx. 400 eventos; delay_ms 0..10000; o executor garante soltar tudo no fim/erro
{"type":"system","op":"lock"|"screenshot"|"screenshot_area"|"suspend"|"show_desktop"
                  |"mic_mute"|"dnd_on"|"dnd_off"|"dnd_toggle"|"empty_trash"}
   // lock: loginctl lock-session → xflock4 → xdg-screensaver lock
   // screenshot: xfce4-screenshooter -f / -r → gnome-screenshot; mic_mute: pactl set-source-mute
   // @DEFAULT_SOURCE@ toggle; dnd: xfconf-query -c xfce4-notifyd -p /do-not-disturb (outros DEs:
   // unsupported → log); show_desktop: _NET_SHOWING_DESKTOP toggle; suspend: systemctl suspend
```
`type_text`, `open`, `keys`, `media`, `volume`, `window`, `ai_prompt`, `command`, `delay` continuam.
`command` é permitido em passos (mesmas regras de validação). Ao salvar, passos `type_text` cujo
texto o detector de segredos acusar geram aviso (`warnings` na resposta, não bloqueia).

## 4. D-Bus (adições em `io.github.openmacros.Manager1`)
| Membro | Assinatura | |
|---|---|---|
| `GetSmartActions()` | `→ s` | (existente) cada entrada inclui `id`, `trigger_errors: [{"index":0,"message":"…"}]` |
| `SaveSmartAction(s json)` | `→ s` | (existente) agora devolve JSON `{"id":"…","warnings":[…]}` |
| `SetSmartActionEnabled(s id, b enabled)` | `→ b` | |
| `ExportSmartAction(s id)` | `→ s` | `{"openmacros_smart_action":1, …sem id/stats}` |
| `ImportSmartAction(s json)` | `→ s` | valida, cria com id novo, devolve o id |
| `GetRunningApps()` | `→ s` | lista JSON de ActiveApp com janela aberta (para o seletor de gatilho) |
| `SmartActionTriggered(s id, s trigger_json)` | sinal | também gera OSD se `osd_gestures` (rótulo "Smart Action: Modo reunião") |

Compatibilidade da GUI: `SaveSmartAction` pode devolver id puro (versão antiga) — tratar os dois.

## 5. GUI — tela Smart Actions no estilo Options+
- Abas **Minhas Smart Actions** | **Modelos**. Cartões em grade: ícone, nome, descrição, resumo
  "Se Ctrl+Alt+P · Ao abrir Firefox → 4 ações", switch Ativa/Inativa, menu ⋮ (Editar, Duplicar,
  Exportar…, Excluir). Ordenar: Mais recentes / Alfabética / Mais usadas. Botões **Criar** e
  **Importar…**. Estado vazio: "Clique em Criar para adicionar sua primeira Smart Action".
- Editor em duas seções: **Se…** (gatilhos, "Adicionar gatilho", "Ou" entre eles; tipos: Botão do
  dispositivo → escolhe dispositivo/botão/perfil e grava a atribuição; Atalho → captura combinação;
  Aplicativo → app (instalados + em execução) e evento Abrir/Fechar/Primeiro plano; Dispositivo →
  conectar/desconectar) e **Então…** (ações por categoria: Aplicativo, Pressionamento de tecla,
  Texto, Sistema, Mídia, IA, Atraso, Comando; reordenar; limite visível 32).
- **Gravador de teclas**: "Começar a gravar / Parar / Continuar", modos "Tempos reais" e "Atraso
  fixo (50 ms)"; captura pelos eventos de tecla do próprio diálogo (sem keylogger global).
- Diálogo de nome + descrição ao salvar; aviso fixo discreto "Não guarde senhas ou dados sensíveis
  em Smart Actions"; `warnings` do serviço viram toast; `trigger_errors` aparecem no gatilho.
- **Experimentar** roda tudo (`RunAction` com `{"type":"smart_action","id":…}` após salvar, ou
  passo a passo no rascunho).
- **Modelos** (nossos, pt-BR; ao usar vira cópia editável): Modo de trabalho; Modo reunião (mic mudo
  + não perturbe); Hora de relaxar (play na mídia + não perturbe off); Volto em breve (pausar mídia,
  mic mudo, bloquear tela); Pesquisar a seleção na web; Perguntar à IA sobre a seleção; Abrir meus
  sites ao abrir o navegador (gatilho app open); Atualizar projeto (git pull no terminal); Pentest
  (existente); Captura de área para a área de transferência.

## Notas do backend (desvios e esclarecimentos de §1–4)

- **Arquivos novos** (`daemon/`): `smart.py` (formato, migração, validação de gatilhos; puro), `triggers.py`
  (`TriggerEngine`, `AppTracker`, backends falsos), `xtriggers.py` (X11: `X11ShortcutBackend`, `X11AppWatcher`),
  `session_env.py` (ambiente gráfico tardio). Ações novas em `actions.py`; `AppController`/`SystemController` em
  `integrations.py`.
- **Migração** acontece ao carregar o `config.json` (`smart.migrate`): entradas v1 ganham `description:""`,
  `enabled:true`, `triggers:[]` e `stats`. `stats.created/modified` das entradas antigas = momento da 1ª leitura.
  `stats` é só leitura: ignorado em `SaveSmartAction`/`ImportSmartAction`; `runs` conta toda execução (botão,
  gatilho e Experimentar) e `modified` muda ao salvar/ativar/desativar. Backup (`ExportConfig`/`ImportConfig`) leva e
  traz `stats`.
- **`SaveSmartAction`** devolve `{"id","warnings":[…]}` (o aviso nunca repete o texto do passo). `GetSmartActions`
  acrescenta `trigger_errors` a cada entrada (`[{"index":N,"message":"…"}]`, índice do gatilho em `triggers`).
- **`ImportSmartAction`** exige `openmacros_smart_action == 1`, ignora `id`/`stats` do arquivo, não confere se os
  executáveis de `command` existem (como o backup) e a Smart Action **entra desativada** (`enabled:false`): um arquivo de
  terceiros com atalho/gatilho de aplicativo e passos `command` não deve passar a rodar sozinho. A GUI liga com
  `SetSmartActionEnabled`. Devolve só o id (sem `warnings`).
- **`enabled:false`** bloqueia também a atribuição de botão (`{"type":"smart_action"}`): só `RunAction`/Experimentar
  ignoram `enabled`. Smart Action desativada **não registra** o atalho no X (outros programas podem usá-lo).
- **Atalhos (`shortcut`)**: keycode do X = código evdev + 8 (xkb "evdev", o padrão em Linux), registrado com as 4
  variantes de CapsLock/NumLock (NumLock detectado pelo mapa de modificadores; padrão Mod2). Regras de validação
  (rejeitadas em `SaveSmartAction` com `InvalidArgument`): exatamente 1 tecla não modificadora; ≥ 1 modificador
  (Ctrl/Shift/Alt esquerdo/Super), exceto F13–F24 e teclas de mídia; `KEY_RIGHTALT` (AltGr) é recusado porque
  depende do layout; teclas com código evdev > 247 não existem no X. Falhas em tempo de execução
  (BadAccess/combinação já usada por outro programa, mesma combinação em duas Smart Actions, Wayland, sem `DISPLAY`,
  sem python-xlib) vão para `trigger_errors` e para o sinal `Error("", mensagem)` (uma vez por erro novo). Combinação
  duplicada: a primeira Smart Action ganha, as outras recebem o erro. Disparar um atalho **engole** a tecla (é um grab).
- **`app`**: uma conexão X própria escuta `_NET_CLIENT_LIST` (debounce 150 ms) e só conta janelas de tipo
  `NORMAL`/`DIALOG` (ou sem tipo) — docks/desktop/menus ficam de fora. `app_id` na mesma regra do FocusWatcher
  (`WM_CLASS[-1]` em minúsculas, senão o executável). `open`/`close` são por *conjunto de app_ids* (1ª janela / última
  janela). O estado inicial, inclusive quando o X só aparece depois (nova tentativa), não dispara `open`.
  `focus` dispara quando o `app_id` em foco muda (inclusive para um app já aberto).
- **`device`**: `connect`/`disconnect` são transições reais de online/offline do manager (volta do Easy-Switch,
  receptor reconectado, dispositivo novo ou removido). Os dispositivos achados na **1ª varredura** do serviço são estado
  inicial e não disparam.
- **Proteções**: ativa; no máx. 1×/2 s por Smart Action (qualquer gatilho); nunca enquanto ela executa; gatilhos
  `app`/`device` dela mesma ficam ignorados durante a execução + 2 s (também depois de uma execução por botão).
  Acrescentado: **corta-laço entre Smart Actions** (A abre B, B abre A): no máx. 6 disparos por gatilho em 30 s por
  Smart Action; ao estourar, o excedente é ignorado e sai um `Error` ("disparando em excesso").
- **`SmartActionTriggered(id, trigger_json)`** sai para gatilhos (atalho/app/device), não para botão (esse já gera
  `ActionTriggered`) nem para Experimentar. O OSD usa a categoria `smart` ("Smart Action: <nome>", respeita
  `osd_gestures`).
- **`app` (ação)**: `open` aceita `.desktop` (id ou caminho), nome simples (`firefox`: procura id do .desktop,
  `StartupWMClass` e executável; por último um executável no PATH) — `close`/`focus` casam janelas pelos app_ids
  derivados do alvo (id do .desktop, último trecho de um id reverso, `StartupWMClass`, executável) e, como o FocusWatcher,
  também pelo nome do executável. `focus` usa a janela mais ao topo de `_NET_CLIENT_LIST_STACKING` e abre o app se não
  houver janela. Alvo sem janela em `close` apenas loga.
- **`key_sequence`**: `delay_ms` é a espera ANTES do evento (tempos reais da gravação); só `KEY_*`/`BTN_*` do evdev.
  Roda pelo scheduler (não trava o loop); como passo de Smart Action o passo seguinte só começa quando a sequência
  termina. Teclas ainda pressionadas são soltas (ordem inversa) no fim, em erro de uinput e no desligamento do serviço.
- **`system`**: cada operação tenta as ferramentas na ordem do contrato; `screenshot*`, `suspend` e `empty_trash`
  são disparados sem esperar o resultado. `empty_trash` = `gio trash --empty` → `trash-empty` (o contrato não fixava).
  `mic_mute` sem `pactl`/`wpctl` cai na tecla `KEY_MICMUTE` via uinput. `dnd_*` só no XFCE (`xfconf-query`, cria a
  propriedade se faltar); em outros DEs a ação só loga. `show_desktop` alterna `_NET_SHOWING_DESKTOP`.
- **Colagem × CLIPBOARD** (`type_text` `paste` e `ai_prompt`): o CLIPBOARD é lido sem o corte de 8 KiB (até 1 MiB; maior
  → não salva, loga) e só se o `xclip` listar `UTF8_STRING`/`text/plain` em `TARGETS` (sem cair no `xsel`); se o original
  não puder ser restaurado, o CLIPBOARD é **limpo** depois do prazo de 600 ms (`xsel -bc`; com só `xclip`, grava vazio).
  `ai_prompt` cancela o restore pendente antes de copiar o prompt; num `SmartActionRunner`, depois de uma colagem
  o próximo passo que escreve no CLIPBOARD espera ≥ 150 ms (os `delay` do usuário contam); no SIGTERM o `Manager.close()`
  restaura (ou limpa) o CLIPBOARD na hora.
- **Serviço sem DISPLAY**: a unidade usa `WantedBy=default.target` (sem `graphical-session.target`). Sem `DISPLAY`, o
  daemon não desiste: a cada 3 s (depois de 20 tentativas, a cada 30 s) relê o ambiente do gerenciador com
  `systemctl --user show-environment` e, quando surge o `DISPLAY`, inicia foco, janelas e atalhos. Além disso o
  autostart `io.github.openmacros.Session.desktop` (instalado por `install.sh`) roda `import-environment` e reinicia o
  serviço no login gráfico — dois caminhos independentes para o mesmo resultado.
- **Limite do template de `ai_prompt`**: 4000 caracteres (igual à GUI); o texto de `type_text` continua em 2000.
- **Modo `OPENMACROS_FAKE=1`**: atalhos e lista de apps são simulados; `DebugSetActiveApp("x")` conta como "abrir x" e
  "foco em x" (dispara gatilhos `app`), útil para testar a GUI sem X.
