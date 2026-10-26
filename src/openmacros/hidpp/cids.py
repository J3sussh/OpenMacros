"""Nomes legíveis (PT-BR) de Control IDs da feature 0x1B04. Tabela própria."""

CID_NAMES: dict[int, str] = {
    0x50: "Botão esquerdo",
    0x51: "Botão direito",
    0x52: "Botão da roda",
    0x53: "Voltar",
    0x54: "Botão de rolagem para baixo",
    0x55: "Botão de rolagem para cima",
    0x56: "Avançar",
    0x57: "Botão lateral extra",
    0x5B: "Inclinar roda para a esquerda",
    0x5D: "Inclinar roda para a direita",
    0xC3: "Botão de gestos",
    0xC4: "Alternar modo da roda",
    0xC5: "Alternar modo da roda (alternativo)",
    0xD0: "Botão de gestos",
    0xFD: "Alterar DPI",
}

# Botões físicos cujo comportamento padrão pode ser re-emitido via uinput
CID_TO_BUTTON: dict[int, str] = {
    0x50: "BTN_LEFT",
    0x51: "BTN_RIGHT",
    0x52: "BTN_MIDDLE",
    0x53: "BTN_SIDE",
    0x56: "BTN_EXTRA",
}


def cid_name(cid: int) -> str:
    return CID_NAMES.get(cid, f"Botão 0x{cid:02X}")

# Botões de inclinar a roda: sem BTN_*, re-emitidos como roda horizontal (REL_HWHEEL)
CID_TO_REL: dict[int, tuple[str, int]] = {
    0x5B: ("REL_HWHEEL", -1),
    0x5D: ("REL_HWHEEL", 1),
}
