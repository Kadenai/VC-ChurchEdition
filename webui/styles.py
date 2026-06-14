"""
CSS global e helpers de HTML do Viral Cutter - Church Edition.
"""

from theme import PALETTE as P

try:
    from icons import icon
except ImportError:
    from webui.icons import icon


# ---------------------------------------------------------------------------
# Folha de estilo global
# ---------------------------------------------------------------------------
CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap');

:root {{
    --vc-canvas: {P['canvas']};
    --vc-surface: {P['surface']};
    --vc-surface-soft: {P['surface_soft']};
    --vc-primary: {P['primary']};
    --vc-primary-light: {P['primary_light']};
    --vc-primary-lighter: {P['primary_lighter']};
    --vc-primary-deep: {P['primary_deep']};
    --vc-primary-deeper: {P['primary_deeper']};
    --vc-border: {P['border']};
    --vc-border-strong: {P['border_strong']};
    --vc-text: {P['text']};
    --vc-text-soft: {P['text_soft']};
    --vc-text-muted: {P['text_muted']};
    --vc-warning: {P['warning']};
    --vc-error: {P['error']};
    --vc-grad: {P['grad']};
    --vc-grad-hover: {P['grad_hover']};
    --vc-grad-sand: {P['grad_sand']};
    --vc-check-accent: {P['check_accent']};
    --vc-accent: {P['accent']};
    --vc-accent-soft: {P['accent_soft']};
    --vc-accent-deep: {P['accent_deep']};
    color-scheme: light;
}}

html[data-vc-theme="dark"] {{
    --vc-canvas: {P['canvas_dark']};
    --vc-surface: {P['surface_dark']};
    --vc-surface-soft: {P['surface_soft_dark']};
    --vc-primary-deep: {P['primary_lighter']};
    --vc-primary-deeper: {P['primary_light']};
    --vc-border: {P['border_dark']};
    --vc-border-strong: {P['border_strong_dark']};
    --vc-text: {P['text_dark']};
    --vc-text-soft: {P['text_soft_dark']};
    --vc-text-muted: {P['text_muted_dark']};
    --vc-check-accent: {P['check_accent_dark']};
    --vc-accent: {P['accent_dark']};
    --vc-accent-soft: {P['accent_soft_dark']};
    --vc-accent-deep: {P['accent_deep_dark']};
    color-scheme: dark;
}}

html, body, .gradio-container {{
    background: var(--vc-canvas) !important;
    color: var(--vc-text) !important;
    font-family: 'Inter', system-ui, sans-serif !important;
}}

.gradio-container {{
    max-width: 1180px !important;
    margin: 0 auto !important;
}}

.gradio-container .block,
.gradio-container .form,
.gradio-container .gr-box,
.gradio-container .panel,
.gradio-container .tabitem {{
    background: var(--vc-surface) !important;
    color: var(--vc-text) !important;
    border-color: var(--vc-border) !important;
}}

input, textarea, select,
.gradio-container input,
.gradio-container textarea,
.gradio-container select {{
    background: var(--vc-surface) !important;
    color: var(--vc-text) !important;
    border-color: var(--vc-border-strong) !important;
}}

input::placeholder,
textarea::placeholder {{
    color: var(--vc-text-muted) !important;
}}

label, .label-wrap, .prose, .markdown, .gradio-container p, .gradio-container li {{
    color: var(--vc-text-soft) !important;
}}

.gradio-container strong {{
    color: var(--vc-text) !important;
}}

footer {{
    display: none !important;
}}

h1, h2, h3, h4, .vc-title {{
    color: var(--vc-text) !important;
    font-family: 'Poppins', 'Inter', sans-serif !important;
}}

a {{
    color: var(--vc-primary-deep) !important;
}}

.gradio-container .tab-nav button,
.gradio-container .tab-nav button span {{
    color: var(--vc-text-soft) !important;
    opacity: 1 !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    border-radius: 10px 10px 0 0 !important;
    transition: color .2s, background .2s !important;
}}

.gradio-container .tab-nav button.selected,
.gradio-container .tab-nav button.selected span {{
    color: var(--vc-primary-deep) !important;
    border-bottom: 3px solid var(--vc-primary) !important;
}}

.gradio-container [role="tab"],
.gradio-container [role="tab"] * {{
    color: var(--vc-text-soft) !important;
    opacity: 1 !important;
}}

.gradio-container [role="tab"][aria-selected="true"],
.gradio-container [role="tab"][aria-selected="true"] * {{
    color: var(--vc-primary-deep) !important;
}}

.gradio-container label:has(input[type="radio"]) {{
    background: var(--vc-surface-soft) !important;
    border: 1px solid var(--vc-border-strong) !important;
    color: var(--vc-text) !important;
}}

.gradio-container label:has(input[type="radio"]) span {{
    color: var(--vc-text) !important;
}}

.gradio-container label:has(input[type="radio"]:checked) {{
    background: var(--vc-primary) !important;
    border-color: var(--vc-primary) !important;
}}

.gradio-container label:has(input[type="radio"]:checked) span {{
    color: #fff !important;
}}

/* ---- Checkbox: marca visível e tom sóbrio em ambos os temas ----
   A regra genérica de input acima usa "background ... !important", o que
   apagava o "check" do checkbox marcado. Aqui desenhamos o controle por
   conta própria para garantir a marca visível e legível. */
.gradio-container input[type="checkbox"] {{
    appearance: none !important;
    -webkit-appearance: none !important;
    flex: 0 0 auto !important;
    width: 18px !important;
    height: 18px !important;
    margin: 0 8px 0 0 !important;
    border-radius: 5px !important;
    border: 1.5px solid var(--vc-border-strong) !important;
    background: var(--vc-surface) !important;
    cursor: pointer !important;
    vertical-align: -0.18em !important;
    transition: background-color .15s ease, border-color .15s ease !important;
}}

.gradio-container input[type="checkbox"]:hover {{
    border-color: var(--vc-check-accent) !important;
}}

.gradio-container input[type="checkbox"]:checked {{
    background-color: var(--vc-check-accent) !important;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='5 12 10 17 19 7'/%3E%3C/svg%3E") !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: 70% !important;
    border-color: var(--vc-check-accent) !important;
}}

/* O texto do checkbox fica num <span> próprio (não coberto pela regra de
   label genérica) — fixamos a cor para não sumir no modo escuro. */
.gradio-container label:has(input[type="checkbox"]),
.gradio-container label:has(input[type="checkbox"]) span {{
    color: var(--vc-text-soft) !important;
}}

button.primary, .primary > button {{
    position: relative !important;
    overflow: hidden !important;
    font-weight: 600 !important;
    text-shadow: 0 1px 2px rgba(6,40,30,.32) !important;
    transition: transform .15s ease, box-shadow .2s ease !important;
}}

button.primary:hover, .primary > button:hover {{
    transform: translateY(-1px) !important;
    box-shadow: 0 12px 28px rgba(52,126,102,.30) !important;
}}

button.primary::after, .primary > button::after {{
    content: '';
    position: absolute;
    top: 0;
    left: -120%;
    width: 80%;
    height: 100%;
    background: linear-gradient(120deg, transparent, rgba(255,255,255,.55), transparent);
    transform: skewX(-20deg);
}}

button.primary:hover::after, .primary > button:hover::after {{
    animation: vc-shine .9s ease;
}}

@keyframes vc-shine {{
    from {{ left: -120%; }}
    to {{ left: 130%; }}
}}

.vc-icon {{
    display: inline-block;
    flex: 0 0 auto;
    vertical-align: -0.18em;
}}

.vc-icon-inline {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
}}

.vc-decorated-icon {{
    display: inline-flex !important;
    align-items: center !important;
    gap: 7px !important;
}}

.vc-decorated-icon svg {{
    flex: 0 0 auto;
}}

.vc-header {{
    background: var(--vc-grad);
    border-radius: 18px;
    padding: 26px 72px 26px 28px;
    color: #fff;
    text-align: center;
    box-shadow: 0 12px 30px rgba(52,126,102,.24);
    position: relative;
    overflow: hidden;
    margin-bottom: 8px;
}}

html[data-vc-theme="dark"] .vc-header {{
    box-shadow: 0 16px 42px rgba(40,90,74,.30);
}}

.vc-header::before {{
    content: '';
    position: absolute;
    top: -60%;
    left: -30%;
    width: 60%;
    height: 220%;
    background: linear-gradient(120deg, transparent, rgba(255,255,255,.25), transparent);
    transform: skewX(-20deg);
    animation: vc-header-shine 6s ease-in-out infinite;
}}

@keyframes vc-header-shine {{
    0%, 100% {{ left: -30%; opacity: 0; }}
    50% {{ left: 120%; opacity: 1; }}
}}

.vc-header .vc-brand {{
    font-family: 'Poppins', sans-serif;
    font-weight: 700;
    font-size: 2.1rem;
    letter-spacing: 0;
    margin: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    text-shadow: 0 1px 4px rgba(6,40,30,.38);
}}

.vc-header .vc-edition {{
    display: inline-block;
    margin-left: 6px;
    padding: 3px 12px;
    font-size: .78rem;
    font-weight: 600;
    letter-spacing: .5px;
    background: rgba(255,255,255,.22);
    border: 1px solid rgba(255,255,255,.4);
    border-radius: 999px;
    vertical-align: middle;
}}

.vc-header .vc-tagline {{
    margin: 8px 0 0 0;
    color: rgba(255,255,255,.96) !important;
    font-size: 1.02rem;
    text-shadow: 0 1px 3px rgba(6,40,30,.3);
}}

.vc-theme-toggle {{
    position: absolute;
    top: 14px;
    right: 16px;
    z-index: 2;
    width: 40px;
    height: 40px;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,.42);
    background: rgba(255,255,255,.18);
    color: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: transform .15s ease, background .2s ease;
}}

.vc-theme-toggle:hover {{
    transform: translateY(-1px);
    background: rgba(255,255,255,.26);
}}

.vc-help {{
    display: flex;
    gap: 10px;
    align-items: flex-start;
    background: var(--vc-surface-soft);
    border: 1px solid var(--vc-border);
    border-left: 4px solid var(--vc-primary);
    color: var(--vc-primary-deeper);
    padding: 10px 14px;
    border-radius: 10px;
    font-size: .92rem;
    line-height: 1.45;
    margin: 4px 0 10px 0;
}}

.vc-help span,
.vc-help p,
.vc-help li {{
    color: var(--vc-primary-deeper) !important;
}}

html[data-vc-theme="dark"] .vc-help span,
html[data-vc-theme="dark"] .vc-help p,
html[data-vc-theme="dark"] .vc-help li {{
    color: var(--vc-text) !important;
}}

.vc-help .vc-help-ico {{
    color: var(--vc-primary-deep);
    line-height: 1.4;
    margin-top: 1px;
}}

.vc-step {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 6px 0 2px 0;
}}

.vc-step .vc-step-num {{
    flex: 0 0 auto;
    width: 34px;
    height: 34px;
    border-radius: 50%;
    background: var(--vc-grad-sand);
    color: #fff;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Poppins', sans-serif;
    box-shadow: 0 4px 10px rgba(122,98,48,.30);
}}

.vc-step .vc-step-txt {{
    color: var(--vc-text);
    font-family: 'Poppins', sans-serif;
    font-weight: 600;
    font-size: 1.12rem;
}}

.vc-step .vc-step-sub {{
    color: var(--vc-text-soft);
    font-size: .88rem;
    font-weight: 400;
}}

.vc-chip {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--vc-accent-soft);
    color: var(--vc-accent-deep);
    border: 1px solid var(--vc-accent);
    border-radius: 999px;
    padding: 5px 12px;
    font-size: .85rem;
    font-weight: 600;
}}

.vc-status-card,
.vc-active-modules,
.vc-asset-status,
.vc-footer {{
    background: var(--vc-surface-soft);
    border: 1px solid var(--vc-border);
    color: var(--vc-text-soft);
}}

@keyframes vc-spin {{
    to {{ transform: rotate(360deg); }}
}}

@keyframes vc-processing-pulse {{
    0%, 100% {{ box-shadow: 0 0 0 0 rgba(52, 211, 153, .20); }}
    50% {{ box-shadow: 0 0 0 8px rgba(52, 211, 153, 0); }}
}}

.vc-processing-status {{
    display: flex;
    align-items: center;
    gap: 13px;
    margin: 10px 0 14px;
    padding: 14px 16px;
    border-radius: 12px;
    background: var(--vc-surface-soft);
    border: 1px solid var(--vc-border);
    color: var(--vc-text);
    box-shadow: 0 10px 28px rgba(8, 55, 41, .10);
}}

.vc-processing-status.is-running {{
    border-color: var(--vc-primary);
    background:
        linear-gradient(135deg, rgba(52, 211, 153, .13), rgba(255, 255, 255, 0)),
        var(--vc-surface-soft);
}}

.vc-processing-status.is-done {{
    border-color: rgba(70, 160, 133, .45);
}}

.vc-processing-status.is-error {{
    border-color: rgba(225, 29, 72, .36);
    background: rgba(225, 29, 72, .08);
}}

.vc-processing-status.is-manual {{
    border-color: rgba(224, 164, 63, .45);
    background: rgba(224, 164, 63, .09);
}}

.vc-processing-mark {{
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 38px;
    width: 38px;
    height: 38px;
    border-radius: 999px;
    color: var(--vc-primary-deep);
    background: var(--vc-surface);
}}

.vc-processing-status.is-running .vc-processing-mark {{
    animation: vc-processing-pulse 1.8s ease-in-out infinite;
}}

.vc-processing-spinner {{
    position: absolute;
    inset: 2px;
    border: 3px solid rgba(70, 160, 133, .22);
    border-top-color: var(--vc-primary);
    border-radius: inherit;
    animation: vc-spin .8s linear infinite;
}}

.vc-processing-icon {{
    display: inline-flex;
    position: relative;
    z-index: 1;
}}

.vc-processing-status.is-error .vc-processing-mark {{
    color: var(--vc-error);
}}

.vc-processing-copy {{
    min-width: 0;
}}

.vc-processing-title {{
    color: var(--vc-text);
    font-weight: 800;
    font-size: 1rem;
    line-height: 1.25;
}}

.vc-processing-message {{
    color: var(--vc-text-soft);
    font-weight: 600;
    margin-top: 2px;
    transition: opacity .14s ease;
}}

.viral-card {{
    transition: transform .2s ease;
}}

.viral-card:hover {{
    transform: translateY(-4px);
}}

.viral-card:hover .vc-video-wrap {{
    box-shadow: 0 14px 34px rgba(52,126,102,.18) !important;
}}

@keyframes vc-fade-in {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to {{ opacity: 1; transform: none; }}
}}

.vc-fade {{
    animation: vc-fade-in .45s ease both;
}}

@media (max-width: 640px) {{
    .vc-header {{
        padding: 24px 54px 24px 18px;
    }}

    .vc-header .vc-brand {{
        font-size: 1.55rem;
        flex-wrap: wrap;
    }}
}}
"""


# ---------------------------------------------------------------------------
# Helpers de HTML reutilizaveis
# ---------------------------------------------------------------------------
def help_banner(text):
    """Banner with a lightbulb SVG that explains a section in plain language."""
    return (
        f'<div class="vc-help"><span class="vc-help-ico">{icon("lightbulb", 20)}</span>'
        f'<span>{text}</span></div>'
    )


def step_badge(number, title, subtitle=""):
    """Cabecalho de passo numerado (1, 2, 3...) do assistente."""
    sub = f'<span class="vc-step-sub"> - {subtitle}</span>' if subtitle else ""
    return (
        f'<div class="vc-step"><div class="vc-step-num">{number}</div>'
        f'<div class="vc-step-txt">{title}{sub}</div></div>'
    )


def section_title(icon_name, title):
    """Titulo de secao simples com SVG."""
    return (
        f'<div class="vc-title vc-icon-inline" '
        f'style="font-size:1.15rem;font-weight:600;margin:2px 0 6px;">'
        f'{icon(icon_name, 19)}<span>{title}</span></div>'
    )
