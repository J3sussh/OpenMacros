# Clique

Configurador open source (GPL-3.0-or-later) para mouses e teclados Logitech HID++ 2.0 no Linux.
Dois processos: `cliqued` (serviço de usuário, fala HID++ via hidraw) e `clique` (GUI GTK4/libadwaita),
conectados por D-Bus de sessão. Veja `docs/ARCHITECTURE.md`.

## Instalação

Dependências do sistema: Python 3.12+, PyGObject, python-evdev (opcional: python3-pyudev para hotplug).

    pip install --user .          # instala `cliqued` e `clique` em ~/.local/bin

### Regra udev (acesso ao hidraw e uinput)

    sudo cp data/udev/70-clique.rules /etc/udev/rules.d/
    sudo udevadm control --reload && sudo udevadm trigger

Reconecte o dispositivo. A tag `uaccess` libera o acesso ao usuário da sessão atual.
A regra cobre só o nó hidraw que fala HID++: Bluetooth (bus 0005) e receptores USB, casando a
interface correta (Unifying/Bolt/Lightspeed: interface 02; Nano c534: interface 01). Dispositivos USB
com fio não são cobertos; veja os comentários em `data/udev/70-clique.rules`.

### Serviço de usuário

    mkdir -p ~/.config/systemd/user
    cp data/systemd/cliqued.service ~/.config/systemd/user/
    systemctl --user enable --now cliqued

## Uso

    cliqued                       # serviço (dispositivos reais)
    CLIQUE_FAKE=1 cliqued         # dispositivos simulados (M720 e mouse genérico), sem hardware
    clique                        # interface gráfica

Sem instalar: `PYTHONPATH=src python3 -m clique.daemon.main`.

Variáveis: `CLIQUE_FAKE=1`, `CLIQUE_LOG=DEBUG`, `CLIQUE_CONFIG=/caminho/config.json`
(padrão `~/.config/clique/config.json`; em modo simulado a configuração fica só em memória).

## Testes

    python3 -m pytest -q
