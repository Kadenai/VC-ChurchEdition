"""
Tema visual do Viral Cutter - Church Edition.

Centraliza as cores e fontes da marca para que app.py e os componentes nao
repitam estilo. As cores cruas vivem em PALETTE (usadas tambem por styles.py e
pela galeria em library.py).
"""

import gradio as gr

# ---------------------------------------------------------------------------
# Tokens de marca (a fonte da verdade das cores). Importe daqui em vez de
# colar hex soltos pelo código.
# ---------------------------------------------------------------------------
PALETTE = {
    # Fundos — "mar de branco com tinta verde": fundo verde bem clarinho,
    # cards quase brancos levemente esverdeados.
    "canvas": "#EBF1EE",       # fundo geral (verde-sálvia dessaturado)
    "surface": "#F7FAF8",      # cards / blocos (branco levemente esverdeado)
    "surface_soft": "#DEE8E3", # banners de ajuda / destaques suaves
    "canvas_dark": "#0C1B16",
    "surface_dark": "#122722",
    "surface_soft_dark": "#18352D",
    # Esmeralda dessaturada (tom sálvia, menos contraste)
    "primary": "#46A085",
    "primary_light": "#6FBCA4",
    "primary_lighter": "#A6D4C7",
    "primary_deep": "#347E66",   # acento legível sobre o claro
    "primary_deeper": "#265E4C",
    # Bordas
    "border": "#CFDDD6",
    "border_strong": "#A9C5BA",
    "border_dark": "#294E43",
    "border_strong_dark": "#356B59",
    # Texto — verde escuro suavizado (menos contraste que o quase-preto)
    "text": "#20382F",
    "text_soft": "#4A6359",
    "text_muted": "#8AA096",
    "text_dark": "#E7F2EE",
    "text_soft_dark": "#B0C9BF",
    "text_muted_dark": "#7A988C",
    # Preenchimento do checkbox marcado — esmeralda sóbria (menos berrante
    # que o primary), legível com o "check" branco nos dois temas.
    "check_accent": "#347E66",
    "check_accent_dark": "#58B394",
    # Terceira cor — areia/dourado sóbrio. Acento sutil em chips e nos
    # números de passo, para quebrar o monocromático verde.
    "accent": "#B79A63",
    "accent_soft": "#EFE7D4",
    "accent_deep": "#7E6230",
    "accent_dark": "#C9AE78",
    "accent_soft_dark": "#2C2718",
    "accent_deep_dark": "#E2CE9B",
    "grad_sand": "linear-gradient(135deg,#C9AE78 0%,#B79A63 50%,#9A7C45 100%)",
    # Estados
    "warning": "#F59E0B",
    "error": "#E11D48",
    # Gradientes
    "grad": "linear-gradient(135deg,#6FBCA4 0%,#46A085 50%,#347E66 100%)",
    "grad_hover": "linear-gradient(135deg,#46A085 0%,#347E66 50%,#265E4C 100%)",
}


def build_theme():
    """Tema Gradio (Soft) repintado para a marca, com light/dark tokens."""
    theme = gr.themes.Soft(
        primary_hue=gr.themes.colors.emerald,
        secondary_hue=gr.themes.colors.emerald,
        neutral_hue=gr.themes.colors.slate,
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
    ).set(
        # ---- Corpo / fundo ----
        body_background_fill=PALETTE["canvas"],
        body_background_fill_dark=PALETTE["canvas_dark"],
        body_text_color=PALETTE["text"],
        body_text_color_dark=PALETTE["text_dark"],
        body_text_color_subdued=PALETTE["text_soft"],
        body_text_color_subdued_dark=PALETTE["text_soft_dark"],
        background_fill_primary=PALETTE["surface"],
        background_fill_primary_dark=PALETTE["surface_dark"],
        background_fill_secondary=PALETTE["canvas"],
        background_fill_secondary_dark=PALETTE["canvas_dark"],
        # ---- Blocos / cards ----
        block_background_fill=PALETTE["surface"],
        block_background_fill_dark=PALETTE["surface_dark"],
        block_border_color=PALETTE["border"],
        block_border_color_dark=PALETTE["border_dark"],
        block_border_width="1px",
        block_radius="16px",
        block_shadow="0 8px 24px rgba(38,94,76,0.10)",
        block_label_text_color=PALETTE["text_soft"],
        block_label_text_color_dark=PALETTE["text_soft_dark"],
        block_title_text_color=PALETTE["text"],
        block_title_text_color_dark=PALETTE["text_dark"],
        block_title_text_weight="600",
        panel_background_fill=PALETTE["surface"],
        panel_background_fill_dark=PALETTE["surface_dark"],
        border_color_primary=PALETTE["border"],
        border_color_primary_dark=PALETTE["border_dark"],
        # ---- Inputs ----
        input_background_fill=PALETTE["surface"],
        input_background_fill_dark=PALETTE["surface_dark"],
        input_border_color=PALETTE["border_strong"],
        input_border_color_dark=PALETTE["border_strong_dark"],
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
        button_primary_shadow="0 8px 20px rgba(52,126,102,0.26)",
        # ---- Botão secundário ----
        button_secondary_background_fill=PALETTE["surface"],
        button_secondary_background_fill_dark=PALETTE["surface_dark"],
        button_secondary_background_fill_hover=PALETTE["surface_soft"],
        button_secondary_background_fill_hover_dark=PALETTE["surface_soft_dark"],
        button_secondary_text_color=PALETTE["primary_deep"],
        button_secondary_text_color_dark=PALETTE["primary_lighter"],
        button_secondary_border_color=PALETTE["border_strong"],
        button_secondary_border_color_dark=PALETTE["border_strong_dark"],
        button_large_radius="12px",
        button_small_radius="10px",
        # ---- Acentos / links ----
        color_accent_soft=PALETTE["surface_soft"],
        color_accent_soft_dark=PALETTE["surface_soft_dark"],
        link_text_color=PALETTE["primary_deep"],
        link_text_color_dark=PALETTE["primary_lighter"],
        link_text_color_hover=PALETTE["primary_deeper"],
        link_text_color_hover_dark=PALETTE["primary_light"],
        slider_color=PALETTE["primary"],
    )
    return theme
