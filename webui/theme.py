"""
Tema visual do Viral Cutter · Church Edition.

Paleta esmeralda + branco (tema claro). Centraliza as cores e fontes da marca
para que app.py e os componentes não repitam estilo. As cores cruas vivem em
PALETTE (usadas também por styles.py e pela galeria em library.py).
"""

import gradio as gr

# ---------------------------------------------------------------------------
# Tokens de marca (a fonte da verdade das cores). Importe daqui em vez de
# colar hex soltos pelo código.
# ---------------------------------------------------------------------------
PALETTE = {
    # Fundos — "mar de branco com tinta verde": fundo verde bem clarinho,
    # cards quase brancos levemente esverdeados.
    "canvas": "#E3F6EC",       # fundo geral (verde bem claro)
    "surface": "#F4FCF8",      # cards / blocos (branco levemente esverdeado)
    "surface_soft": "#D6F2E2", # banners de ajuda / destaques suaves
    # Esmeralda (verde mais clarinho)
    "primary": "#14C18E",
    "primary_light": "#3FD7AC",
    "primary_lighter": "#79E6C5",
    "primary_deep": "#0E9D77",   # acento legível sobre o claro
    "primary_deeper": "#0A7A5C",
    # Bordas
    "border": "#C3EDD6",
    "border_strong": "#97E0BC",
    # Texto — verde escuro quase preto (pedido do usuário)
    "text": "#08281D",
    "text_soft": "#355A4C",
    "text_muted": "#88A99A",
    # Estados
    "warning": "#F59E0B",
    "error": "#E11D48",
    # Gradientes
    "grad": "linear-gradient(135deg,#3FD7AC 0%,#14C18E 50%,#0E9D77 100%)",
    "grad_hover": "linear-gradient(135deg,#14C18E 0%,#0E9D77 50%,#0A7A5C 100%)",
}


def build_theme():
    """Tema Gradio (Soft) repintado para esmeralda claro."""
    theme = gr.themes.Soft(
        primary_hue=gr.themes.colors.emerald,
        secondary_hue=gr.themes.colors.emerald,
        neutral_hue=gr.themes.colors.slate,
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
    ).set(
        # ---- Corpo / fundo (força claro mesmo se o navegador estiver em dark) ----
        body_background_fill=PALETTE["canvas"],
        body_background_fill_dark=PALETTE["canvas"],
        body_text_color=PALETTE["text"],
        body_text_color_dark=PALETTE["text"],
        body_text_color_subdued=PALETTE["text_soft"],
        background_fill_primary=PALETTE["surface"],
        background_fill_primary_dark=PALETTE["surface"],
        background_fill_secondary=PALETTE["canvas"],
        background_fill_secondary_dark=PALETTE["canvas"],
        # ---- Blocos / cards ----
        block_background_fill=PALETTE["surface"],
        block_background_fill_dark=PALETTE["surface"],
        block_border_color=PALETTE["border"],
        block_border_color_dark=PALETTE["border"],
        block_border_width="1px",
        block_radius="16px",
        block_shadow="0 8px 24px rgba(16,185,129,0.08)",
        block_label_text_color=PALETTE["text_soft"],
        block_label_text_color_dark=PALETTE["text_soft"],
        block_title_text_color=PALETTE["text"],
        block_title_text_color_dark=PALETTE["text"],
        block_title_text_weight="600",
        panel_background_fill=PALETTE["surface"],
        panel_background_fill_dark=PALETTE["surface"],
        border_color_primary=PALETTE["border"],
        border_color_primary_dark=PALETTE["border"],
        # ---- Inputs ----
        input_background_fill=PALETTE["surface"],
        input_background_fill_dark=PALETTE["surface"],
        input_border_color=PALETTE["border_strong"],
        input_border_color_dark=PALETTE["border_strong"],
        input_border_color_focus=PALETTE["primary"],
        input_radius="10px",
        # ---- Botão primário (gradiente + glow) ----
        button_primary_background_fill=PALETTE["grad"],
        button_primary_background_fill_dark=PALETTE["grad"],
        button_primary_background_fill_hover=PALETTE["grad_hover"],
        button_primary_background_fill_hover_dark=PALETTE["grad_hover"],
        button_primary_text_color="#FFFFFF",
        button_primary_text_color_dark="#FFFFFF",
        button_primary_border_color=PALETTE["primary"],
        button_primary_shadow="0 8px 20px rgba(16,185,129,0.30)",
        # ---- Botão secundário ----
        button_secondary_background_fill=PALETTE["surface"],
        button_secondary_background_fill_dark=PALETTE["surface"],
        button_secondary_background_fill_hover=PALETTE["surface_soft"],
        button_secondary_text_color=PALETTE["primary_deep"],
        button_secondary_text_color_dark=PALETTE["primary_deep"],
        button_secondary_border_color=PALETTE["border_strong"],
        button_secondary_border_color_dark=PALETTE["border_strong"],
        button_large_radius="12px",
        button_small_radius="10px",
        # ---- Acentos / links ----
        color_accent_soft=PALETTE["surface_soft"],
        link_text_color=PALETTE["primary_deep"],
        link_text_color_hover=PALETTE["primary_deeper"],
        slider_color=PALETTE["primary"],
    )
    return theme
