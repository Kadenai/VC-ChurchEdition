"""
CSS global e helpers de HTML do Viral Cutter · Church Edition.

- CSS(): folha de estilo única, repinta a UI em esmeralda/branco e força o
  tema claro mesmo quando o Colab/navegador está em modo escuro.
- help_banner(), step_badge(), section_title(): blocos de HTML reutilizáveis
  para deixar a interface amigável a leigos (cada coisa explica o que faz).
"""

from theme import PALETTE as P

# ---------------------------------------------------------------------------
# Folha de estilo global
# ---------------------------------------------------------------------------
CSS = f"""
/* ====== Fontes da marca (fallback ao GoogleFont do tema) ====== */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap');

/* ====== Força tema CLARO esmeralda (vence o dark do Colab) ====== */
body, .gradio-container, .dark {{
    background: {P['canvas']} !important;
    color: {P['text']} !important;
    font-family: 'Inter', system-ui, sans-serif !important;
}}

/* Largura do container */
.gradio-container {{
    max-width: 1180px !important;
    margin: 0 auto !important;
}}

/* Blocos / cards claros (cobre variações internas do Gradio) */
.dark .block, .dark .form, .dark .gr-box, .dark .panel {{
    background: {P['surface']} !important;
    color: {P['text']} !important;
    border-color: {P['border']} !important;
}}

/* Inputs claros */
input, textarea, select,
.dark input, .dark textarea, .dark select {{
    background: {P['surface']} !important;
    color: {P['text']} !important;
    border-color: {P['border_strong']} !important;
}}
input::placeholder, textarea::placeholder {{ color: {P['text_muted']} !important; }}

/* Esconde o footer padrão do Gradio */
footer {{ display: none !important; }}

/* ====== Tipografia ====== */
h1, h2, h3, h4, .vc-title {{ font-family: 'Poppins', 'Inter', sans-serif !important; }}

/* ====== Abas ====== */
.tab-nav button {{
    font-weight: 600 !important;
    font-size: 1rem !important;
    border-radius: 10px 10px 0 0 !important;
    transition: color .2s, background .2s !important;
}}
.tab-nav button.selected {{
    color: {P['primary_deep']} !important;
    border-bottom: 3px solid {P['primary']} !important;
}}

/* ====== Botão primário: brilho que desliza (shine sweep) ====== */
button.primary, .primary > button {{
    position: relative !important;
    overflow: hidden !important;
    font-weight: 600 !important;
    text-shadow: 0 1px 2px rgba(6,40,30,.32) !important;
    transition: transform .15s ease, box-shadow .2s ease !important;
}}
button.primary:hover, .primary > button:hover {{
    transform: translateY(-1px) !important;
    box-shadow: 0 12px 28px rgba(16,185,129,.38) !important;
}}
button.primary::after, .primary > button::after {{
    content: ''; position: absolute; top: 0; left: -120%;
    width: 80%; height: 100%;
    background: linear-gradient(120deg, transparent, rgba(255,255,255,.55), transparent);
    transform: skewX(-20deg);
}}
button.primary:hover::after, .primary > button:hover::after {{
    animation: vc-shine .9s ease;
}}
@keyframes vc-shine {{ from {{ left: -120%; }} to {{ left: 130%; }} }}

/* ====== Componentes de marca ====== */
/* Cabeçalho com gradiente + brilho sutil */
.vc-header {{
    background: {P['grad']};
    border-radius: 18px;
    padding: 26px 28px;
    color: #fff;
    text-align: center;
    box-shadow: 0 12px 30px rgba(16,185,129,.28);
    position: relative;
    overflow: hidden;
    margin-bottom: 8px;
}}
.vc-header::before {{
    content: ''; position: absolute; top: -60%; left: -30%;
    width: 60%; height: 220%;
    background: linear-gradient(120deg, transparent, rgba(255,255,255,.25), transparent);
    transform: skewX(-20deg);
    animation: vc-header-shine 6s ease-in-out infinite;
}}
@keyframes vc-header-shine {{
    0%, 100% {{ left: -30%; opacity: 0; }}
    50% {{ left: 120%; opacity: 1; }}
}}
.vc-header .vc-brand {{
    font-family: 'Poppins', sans-serif; font-weight: 700;
    font-size: 2.1rem; letter-spacing: -.5px; margin: 0;
    display: flex; align-items: center; justify-content: center; gap: 12px;
    text-shadow: 0 1px 4px rgba(6,40,30,.38);
}}
.vc-header .vc-edition {{
    display: inline-block; margin-left: 6px; padding: 3px 12px;
    font-size: .78rem; font-weight: 600; letter-spacing: .5px;
    background: rgba(255,255,255,.22); border: 1px solid rgba(255,255,255,.4);
    border-radius: 999px; vertical-align: middle;
}}
.vc-header .vc-tagline {{ margin: 8px 0 0 0; font-size: 1.02rem; opacity: .96; text-shadow: 0 1px 3px rgba(6,40,30,.3); }}

/* Banner de ajuda (💡 explica o que cada coisa faz) */
.vc-help {{
    display: flex; gap: 10px; align-items: flex-start;
    background: {P['surface_soft']};
    border: 1px solid {P['border']};
    border-left: 4px solid {P['primary']};
    color: {P['primary_deeper']};
    padding: 10px 14px; border-radius: 10px;
    font-size: .92rem; line-height: 1.45; margin: 4px 0 10px 0;
}}
.vc-help .vc-help-ico {{ font-size: 1.05rem; line-height: 1.4; }}

/* Badge de passo numerado */
.vc-step {{ display: flex; align-items: center; gap: 12px; margin: 6px 0 2px 0; }}
.vc-step .vc-step-num {{
    flex: 0 0 auto; width: 34px; height: 34px; border-radius: 50%;
    background: {P['grad']}; color: #fff; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Poppins', sans-serif; box-shadow: 0 4px 10px rgba(16,185,129,.3);
}}
.vc-step .vc-step-txt {{ font-family: 'Poppins', sans-serif; font-weight: 600; font-size: 1.12rem; color: {P['text']}; }}
.vc-step .vc-step-sub {{ font-size: .88rem; color: {P['text_soft']}; font-weight: 400; }}

/* Chips de módulos ativos */
.vc-chip {{
    display: inline-flex; align-items: center; gap: 6px;
    background: {P['surface_soft']}; color: {P['primary_deeper']};
    border: 1px solid {P['border_strong']}; border-radius: 999px;
    padding: 5px 12px; font-size: .85rem; font-weight: 600;
}}

/* ====== Galeria de resultados: hover lift ====== */
.viral-card {{ transition: transform .2s ease; }}
.viral-card:hover {{ transform: translateY(-4px); }}
.viral-card:hover .vc-video-wrap {{ box-shadow: 0 14px 34px rgba(16,185,129,.20) !important; }}

/* Aparição suave dos resultados */
@keyframes vc-fade-in {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}
.vc-fade {{ animation: vc-fade-in .45s ease both; }}
"""

# ---------------------------------------------------------------------------
# Helpers de HTML reutilizáveis
# ---------------------------------------------------------------------------
def help_banner(text):
    """Banner '💡' que explica, em linguagem leiga, o que a seção faz."""
    return (
        f'<div class="vc-help"><span class="vc-help-ico">💡</span>'
        f'<span>{text}</span></div>'
    )


def step_badge(number, title, subtitle=""):
    """Cabeçalho de passo numerado (1, 2, 3...) do assistente."""
    sub = f'<span class="vc-step-sub"> — {subtitle}</span>' if subtitle else ""
    return (
        f'<div class="vc-step"><div class="vc-step-num">{number}</div>'
        f'<div class="vc-step-txt">{title}{sub}</div></div>'
    )


def section_title(emoji, title):
    """Título de seção simples com emoji."""
    return f'<div class="vc-title" style="font-size:1.15rem;font-weight:600;color:{P["text"]};margin:2px 0 6px;">{emoji} {title}</div>'
