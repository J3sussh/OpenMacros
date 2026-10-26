# OpenMacros+

[English](README.md) | **Português (Brasil)**

Alternativa livre e independente ao Logi Options+ para Linux. Configura mouses e teclados Logitech HID++ 2.0.

[![CI](https://github.com/j3sussh/openmacros-plus/actions/workflows/ci.yml/badge.svg)](https://github.com/j3sussh/openmacros-plus/actions/workflows/ci.yml)
[![Licença: GPL-3.0-or-later](https://img.shields.io/badge/licen%C3%A7a-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

> **Não afiliado à Logitech.** O OpenMacros+ é um projeto independente. Não é feito, endossado nem patrocinado pela Logitech. Veja [Marcas registradas](#marcas-registradas).

![Tela inicial do OpenMacros+](docs/screenshots/home.png)

| | |
|---|---|
| ![Botões](docs/screenshots/buttons.png)<br>Botões | ![Perfis por aplicativo](docs/screenshots/app-profiles.png)<br>Perfis por aplicativo |
| ![Painel de ações](docs/screenshots/action-panel.png)<br>Painel de ações | ![Gestos](docs/screenshots/gestures.png)<br>Gestos |
| ![Apontar e rolar](docs/screenshots/pointer.png)<br>Apontar e rolar | ![Smart Actions](docs/screenshots/smart-actions.png)<br>Smart Actions |
| ![Editor de Smart Action](docs/screenshots/smart-editor.png)<br>Editor de Smart Action | ![Preferências](docs/screenshots/preferences.png)<br>Preferências |
| ![Aba Sobre](docs/screenshots/about.png)<br>Aba Sobre | ![Bandeja](docs/screenshots/tray.png)<br>Ícone e menu da bandeja |

## Recursos

- **Botões e remapeamento.** Reatribui os botões programáveis, inclusive o botão de gestos.
- **Gestos.** Clique mais quatro direções no botão de gestos, com limiar de sensibilidade ajustável.
- **Perfis por aplicativo.** Cada app em foco pode ter suas próprias ações de botão e ajustes de ponteiro/rolagem. O que você não definir é herdado de "Todos os aplicativos". Há um catálogo de sugestões por app, aplicado só quando você escolhe.
- **Ações nativas:**
  - mídia (MPRIS), volume, controle de janela (fechar, minimizar, maximizar, tela cheia, próxima/anterior);
  - atalhos de teclado, sequências de teclas, botões do mouse, comandos;
  - abrir app, URL ou arquivo; controlar app (abrir, fechar, trazer para frente);
  - digitar texto (qualquer Unicode, por colagem);
  - **IA com privacidade:** perguntar ao Claude, ChatGPT, Perplexity ou Gemini sobre a seleção atual. Por padrão o prompt vai pela área de transferência (veja [Privacidade e segurança](#privacidade-e-segurança));
  - sistema: bloquear tela, captura de tela, suspender, mostrar área de trabalho, silenciar microfone, Não perturbe (só XFCE), esvaziar lixeira.
- **Smart Actions.** Automações "Se… Então…". Gatilhos: botão do dispositivo, atalho global de teclado, aplicativo abrindo/fechando/ganhando foco, dispositivo conectando/desconectando. Até 5 gatilhos e 32 passos (ações e atrasos). Modelos prontos, gravador de teclas, exportar e importar.
- **Apontar e rolar.** Velocidade do ponteiro, DPI, rolagem de alta resolução, inversão de rolagem e SmartShift, conforme o dispositivo suporta. Pode ser sobreposto por aplicativo.
- **Easy-Switch.** Troca de canal pela janela ou pela bandeja.
- **Bandeja com bateria.** Ícone pelo menor nível de bateria; menu com dispositivos, perfil ativo e Easy-Switch.
- **Notificações e OSD.** Bateria baixa, troca de perfil, gesto disparado, conexão/desconexão.
- **Backup.** Exporta e importa a configuração (mesclar ou substituir).

### Fotos dos dispositivos

A GUI usa arte vetorial própria, sem nenhum material da Logitech.

Opcionalmente, você pode importar localmente as fotos oficiais dos dispositivos. Use o item de menu "Importar imagens do Logi Options+…" na tela inicial e aponte para o instalador oficial do Logi Options+ que **você mesmo baixou**. As imagens ficam só no seu computador, em `~/.local/share/openmacros/vendor`, e nunca entram neste repositório.

> A interface hoje está em português do Brasil. A internacionalização (i18n) está planejada (veja o [Roadmap](#roadmap)).

## Dispositivos suportados

Só o Logitech M720 Triathlon (Bluetooth e Unifying) foi testado em hardware real. Outros dispositivos HID++ 2.0 usam o layout genérico e podem funcionar, mas não foram testados. Veja [docs/DEVICES.md](docs/DEVICES.md) para a lista e para saber como contribuir com um dispositivo novo.

## Requisitos

- Linux com X11 (veja [Limitações](#limitações))
- Python 3.12+
- GTK 4 + libadwaita, PyGObject
- python-evdev, pyudev, python-xlib
- `xclip` ou `xsel` (área de transferência e seleção)
- Bandeja: GTK 3 + AyatanaAppIndicator3 (processo separado)

Debian / Ubuntu / Kali:

```sh
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  python3-evdev python3-pyudev python3-xlib xclip xsel \
  gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

## Instalação

### Debian/Ubuntu/Kali (.deb)

Baixe `openmacros-plus_<versão>_all.deb` na página de [Releases](https://github.com/j3sussh/openmacros-plus/releases) e instale. O `apt` traz as dependências sozinho:

```sh
sudo apt install ./openmacros-plus_<versão>_all.deb
```

O pacote instala a regra udev e habilita o serviço de usuário `openmacrosd` para todos os usuários. **Faça logout e login** (ou reconecte o receptor/mouse) para começar a usar. Se quiser, confira o download com o `SHA256SUMS` da mesma release (`sha256sum -c SHA256SUMS`).

Para remover: `sudo apt remove openmacros-plus`. O pacote nunca mexe na sua pasta pessoal, então `~/.config/openmacros` permanece.

> Se você já instalou a partir do código-fonte com `scripts/install.sh`, rode `scripts/uninstall.sh` antes. Senão os lançadores de `~/.local/bin` têm prioridade no `PATH` sobre os do pacote.

Para gerar o pacote você mesmo, use `packaging/deb/build-deb.sh` (veja [CONTRIBUTING](CONTRIBUTING.md#building-the-deb-package)).

### A partir do código-fonte

Instalação de usuário, sem sudo. Só a regra udev exige sudo.

```sh
git clone https://github.com/j3sussh/openmacros-plus.git
cd openmacros-plus
scripts/install.sh
```

Opções do `scripts/install.sh`:

| Opção | Efeito |
|---|---|
| `--pipx` | Instala com `pipx install --system-site-packages` em vez dos lançadores |
| `--no-start` | Habilita o serviço `openmacrosd` sem iniciá-lo |
| `-h`, `--help` | Mostra a ajuda |

O script instala `openmacrosd`, `openmacros` e `openmacros-tray` em `~/.local/bin`, a unidade systemd de usuário, o `.desktop`, o ícone e duas entradas de autostart (a bandeja e um auxiliar de sessão que entrega `DISPLAY`/`XAUTHORITY` ao serviço). É idempotente. No modo padrão os lançadores executam o código do repositório, então **não apague nem mova o repositório depois de instalar**.

#### Regra udev (acesso ao hidraw e ao uinput)

O script imprime estes comandos ao final, mas não os executa:

```sh
sudo install -m 644 data/udev/70-openmacros.rules /etc/udev/rules.d/70-openmacros.rules
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=misc
```

Depois reconecte o receptor/mouse ou refaça o login. A tag `uaccess` dá ao usuário da sessão acesso ao nó hidraw HID++ e a `/dev/uinput` (necessário para as ações de teclado e mouse).

A regra cobre Bluetooth e receptores USB (Unifying, Bolt, Lightspeed, Nano). Dispositivos USB com fio não são cobertos; veja os comentários em `data/udev/70-openmacros.rules`.

## Desinstalação

```sh
scripts/uninstall.sh            # remove lançadores, unidade, .desktop, ícone e autostart
scripts/uninstall.sh --purge    # também apaga ~/.config/openmacros
sudo rm /etc/udev/rules.d/70-openmacros.rules   # o script não remove a regra udev
```

## Uso rápido

```sh
openmacros                              # interface gráfica
openmacros-tray                         # bandeja (inicia sozinha no login após a instalação)
systemctl --user status openmacrosd     # o serviço que fala com o dispositivo
```

1. Abra o OpenMacros+ e escolha o dispositivo.
2. Na aba BOTÕES, clique em um botão na imagem e escolha a ação.
3. Para um perfil por aplicativo, use o "+" acima da imagem.

Mais nos [guias de usuário](docs/guide/getting-started.md) (em inglês).

Sem hardware? Rode com dispositivos simulados:

```sh
OPENMACROS_FAKE=1 openmacrosd
openmacros   # em outro terminal
```

Variáveis: `OPENMACROS_FAKE=1`, `OPENMACROS_LOG=DEBUG`, `OPENMACROS_CONFIG=/caminho/config.json` (padrão `~/.config/openmacros/config.json`).

## Privacidade e segurança

- **IA pela área de transferência.** Por padrão o prompt (sua seleção mais o seu modelo de texto) é copiado para a área de transferência, a página inicial do serviço abre e você cola com Ctrl+V. Nada vai na URL. A entrega por URL (`?q=`) é opcional, e a URL fica no histórico do navegador. O Gemini sempre usa a área de transferência. O OpenMacros+ nunca envia dados a serviço algum por conta própria.
- **Detector de segredos.** Se a seleção parecer conter um segredo (JWT, chaves AWS/GitHub/Slack, chave privada, token `Bearer`, `password=`, hashes, tokens longos), a entrega por URL é bloqueada e o prompt vai pela área de transferência, com aviso. O detector é **heurístico**: pode errar nos dois sentidos. Não o trate como garantia.
- **D-Bus.** O serviço só aceita chamadas do mesmo uid. Chamadores dentro de um sandbox Flatpak só podem usar métodos de leitura.
- **Smart Actions** executam comandos e teclas. Não guarde senhas nelas. Smart Actions importadas entram desativadas.

Para reportar uma vulnerabilidade, veja [SECURITY.md](SECURITY.md).

## Limitações

- **Perfis por aplicativo e gatilhos por aplicativo só funcionam em X11.** No Wayland o app em foco não é detectado, então só vale o perfil global. Suporte a Wayland está planejado.
- **Gatilhos de atalho global** usam grab de teclas do X11 e não funcionam no Wayland.
- **Digitar texto, modo "Simular teclas":** só layout US. O modo padrão (colagem) aceita qualquer Unicode e usa temporariamente a área de transferência.
- Dispositivos USB com fio não têm regra udev pronta.
- Só o M720 Triathlon foi testado em hardware real.

## Roadmap

Planejado ou em estudo. Sem datas e sem promessas.

- Actions Ring
- Efeitos estilo Spotlight
- Marketplace de Smart Actions e perfis
- Haptics experimental
- Interoperabilidade com Flow (em pesquisa)
- Mais dispositivos
- Internacionalização (i18n) da interface
- Suporte a Wayland

## Arquitetura

Dois processos mais a bandeja, ligados pelo D-Bus de sessão (`io.github.openmacros`):

- `openmacrosd`: serviço de usuário. Fala HID++ via hidraw e executa ações via uinput.
- `openmacros`: GUI GTK4/libadwaita. Só conversa com o serviço por D-Bus.
- `openmacros-tray`: bandeja em processo separado (GTK 3 + AyatanaAppIndicator3).

A configuração fica em `~/.config/openmacros/config.json` e é reaplicada a cada reconexão. Veja [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e o [índice da documentação](docs/README.md).

## Desenvolvimento

```sh
OPENMACROS_FAKE=1 PYTHONPATH=src python3 -m openmacros.daemon.main   # serviço com dispositivos simulados
PYTHONPATH=src python3 -m openmacros.gui                             # GUI, em outro terminal
xvfb-run -a dbus-run-session -- python3 -m pytest -q                 # suíte de testes completa
```

Os testes usam um transporte HID++ simulado, então não precisam de hardware. Para os testes de GUI instale `xvfb`, `dbus` e `pytest`. A CI (GitHub Actions, Ubuntu 24.04, Python 3.12 do sistema) roda o mesmo pytest, mais `compileall`, `bash -n` e `shellcheck`. Detalhes em [CONTRIBUTING.md](CONTRIBUTING.md) (em inglês).

## Contribuindo

Relatos de bugs, de dispositivos e pull requests são bem-vindos. Leia antes o [CONTRIBUTING.md](CONTRIBUTING.md). O projeto segue uma política de sala limpa: não contribua com código, imagens ou textos da Logitech. Todos devem seguir o [Código de Conduta](CODE_OF_CONDUCT.md).

## Licença

[GPL-3.0-or-later](LICENSE).

## Marcas registradas

Logitech, Logi, Options+, MX, Triathlon e outros nomes são marcas de seus respectivos donos e aparecem aqui apenas para indicar compatibilidade. Este projeto não é afiliado, endossado nem patrocinado pela Logitech.
