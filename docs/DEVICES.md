# Dispositivos

O OpenMacros+ fala HID++ 2.0 com dispositivos Logitech via hidraw. Dispositivos não listados abaixo podem funcionar com o layout genérico, mas **não foram testados**.

Marcas pertencem aos seus donos; o OpenMacros+ não é afiliado à Logitech.

## Testados em hardware real

| Dispositivo | Conexão | PID | Botões | Gestos | Ponteiro | Easy-Switch | Bateria |
|---|---|---|---|---|---|---|---|
| M720 Triathlon | Bluetooth | `b015` | sim | sim | sim | sim | sim |
| M720 Triathlon | Unifying (receptor `046d:c52b`) | `405e` | sim | sim | sim | sim | sim |

"Ponteiro" = velocidade/DPI e rolagem. O M720 usa o layout `m720` (6 botões: clique da roda, voltar, avançar, roda para esquerda/direita e botão de gestos).

## Receptores com regra udev

Bluetooth (qualquer `046d`), Unifying (`c52b`), Bolt (`c548`), Lightspeed e Nano (`c534`). Só o Unifying foi verificado na máquina de desenvolvimento; os demais seguem a documentação pública. Veja `data/udev/70-openmacros.rules`. Dispositivos USB com fio não são cobertos.

## Contribuir com um dispositivo novo

1. **Instale e rode** o OpenMacros+ com o dispositivo conectado (`OPENMACROS_LOG=DEBUG openmacrosd` mostra o que foi descoberto). Confirme que a regra udev está ativa.
2. **Colete os dados** (a aba Sobre e o `GetDevice` D-Bus mostram quase tudo):
   - nome, tipo (mouse, teclado, trackball), PID e modo de conexão (Bluetooth, receptor, USB);
   - lista de **features HID++** (ex.: `0x1b04`, `0x1000`, `0x1814`, `0x2201`, `0x2205`, `0x2110`/`0x2111`, `0x2121`);
   - **controles** de `0x1B04`: CID, nome, se é remapeável/desviável, se tem `raw_xy`;
   - versão do firmware, se disponível.
   ```sh
   busctl --user call io.github.openmacros /io/github/openmacros io.github.openmacros.Manager1 GetDevices
   ```
   Remova números de série, `unitId` e IDs do `id` (`logi:...`) antes de publicar.
3. **Teste e anote** o que funciona: remapear cada botão, gestos, DPI/velocidade, rolagem, Easy-Switch, bateria, reconexão após suspensão.
4. **Layout (opcional, para ter foto/arte e marcadores):** crie `src/openmacros/gui/data/layouts/<modelo>.json` e uma arte SVG própria em `src/openmacros/gui/data/art/<modelo>.svg`. Formato, como em `m720.json`:
   ```json
   {
     "name": "m720",
     "art": "m720",
     "aspect": [400, 520],
     "markers": [
       {"cid": 82, "x": 0.50, "y": 0.22, "side": "up"}
     ]
   }
   ```
   `x` e `y` são frações (0 a 1) da imagem; `side` indica de que lado fica o rótulo; `cid` liga o marcador ao botão. Sem layout, o dispositivo usa o genérico (`generic-mouse` ou `generic-keyboard`).
5. **Abra uma issue ou PR** com a tabela de testes e, se houver, o layout.

**Não envie** imagens, ícones ou textos da Logitech; use arte própria (SVG) ou o recurso local de importação da GUI. Capturas de protocolo (hex de pacotes) de dispositivos novos são bem-vindas se feitas por você no seu próprio hardware.
