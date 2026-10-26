# M720 Triathlon — protocolo levantado do Logi Options+ 2.8.1479

Fontes: `data/devices/devices_initial.json`, depot `m720_triathlon` e o agente
`logioptionsplus_agent.exe` (nomes de classe RTTI + desmontagem de `SetCtrlIdReportingAsync`
em `0x140a145ac`). Formatos de flags conferidos com a especificação pública do HID++ 2.0 / Solaar.

## Identificação
| Modo | Interface | PID |
|---|---|---|
| Receptor Unifying | HID++ via receptor `046d:c52b` | `405e` |
| Bluetooth | HID++ direto | `b015` |

modelId Options+: `6b015` · hosts Easy-Switch: 3 · scroll hi-res: sim · bateria: `0x1000` (não unified)

## Botões programáveis (CIDs, feature 0x1B04)
| CID | Hex | Botão |
|---|---|---|
| 82 | 0x52 | Clique da roda |
| 83 | 0x53 | Voltar |
| 86 | 0x56 | Avançar |
| 91 | 0x5B | Roda p/ esquerda |
| 93 | 0x5D | Roda p/ direita |
| 208 | 0xD0 | Polegar (gestos) |

## Feature 0x1B04 — Special Keys & Mouse Buttons
Funções (nomes do agente → índice):
| fn | Agente | Uso |
|---|---|---|
| 0 | GetCount | nº de controles |
| 1 | GetCtrlIdInfo | info do controle i (CID, TID, flags) |
| 2 | GetCtrlIdReporting | estado atual de um CID |
| 3 | SetCtrlIdReportingAsync | **confirmado no binário**: 6 bytes de parâmetro |
| 4 | GetCapabilities | |
| 5 | ResetAllCidReportSettingsAsync | volta tudo ao padrão |

Parâmetros da fn 3 (ordem confirmada no binário):
```
[0..1] CID (big-endian)
[2]    flags1: bit0 divert, bit1 divert-valid, bit2 persist, bit3 persist-valid,
               bit4 rawXY, bit5 rawXY-valid
[3..4] remap CID (big-endian, 0 = sem remap)
[5]    flags2: bit0 forceRawXY, bit1 valid, bit2 analytics, bit3 valid,
               bit4 rawWheel, bit5 valid
```
Exemplo — desviar o polegar e receber movimento bruto enquanto pressionado:
`CID=00 D0, flags1=0x33 (divert+rawXY com bits valid), remap=00 00, flags2=00`

Eventos (classes `KeyReport`, `RawXYReport`, `RawWheelReport`):
- evento 0 (KeyReport): até 4 CIDs desviados pressionados, u16 BE cada; lista vazia = soltou.
- evento 1 (RawXYReport): dx, dy como int16 BE.
- evento 2 (RawWheelReport): roda bruta (não usado no M720).

## Gestos (calculados no host)
Máquina de estados `ButtonGestureContinuousBaseState` do agente:
1. Botão do polegar pressionado → começa a somar dx/dy.
2. Se a distância passar do limite e estiver dentro da zona de "angle snapping", trava a direção
   (horizontal ou vertical) e dispara o gesto.
3. Pode trocar de eixo durante o movimento (logs "Ending horizontal… Starting vertical").
4. Se soltar sem passar do limite → executa a ação de clique do botão.

Limites de gestos contínuos nos presets: 15 (sensibilidade mínima) a 1 (máxima) unidades
do dispositivo; duração por ação 50–100 ms. Os valores exatos para gestos de 4 direções
ainda não foram extraídos do binário.

## Outras features que o Options+ usa no M720
- 0x1814 Change Host / 0x1815 Hosts Info — Easy-Switch
- 0x2121 Hi-Res Wheel — resolução/inversão da roda
- 0x1000 Battery Status
- ajuste de velocidade do ponteiro (`pointerSpeed`) — feature a confirmar no dispositivo
