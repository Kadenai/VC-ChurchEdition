import os
import sys

# Necessário porque este arquivo é importado por app.py (mesma pasta), mas o i18n
# vive na raiz do projeto.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(WORKING_DIR)

from i18n.i18n import I18nAuto
i18n = I18nAuto(language="pt_BR")

# Ícone de marca (tesoura + play em esmeralda), inline para funcionar no Colab
# sem depender de arquivo externo carregar.
_BRAND_ICON = """
<svg width="40" height="40" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle cx="24" cy="24" r="22" fill="rgba(255,255,255,0.16)" stroke="rgba(255,255,255,0.5)" stroke-width="1.5"/>
  <path d="M20 19l12 5-12 5V19z" fill="#fff"/>
  <circle cx="15" cy="16" r="3.2" stroke="#fff" stroke-width="2" fill="none"/>
  <circle cx="15" cy="32" r="3.2" stroke="#fff" stroke-width="2" fill="none"/>
  <line x1="17.8" y1="17.6" x2="30" y2="26" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
  <line x1="17.8" y1="30.4" x2="30" y2="22" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
</svg>
"""

# Cabeçalho principal (faixa com gradiente esmeralda + brilho — classes em styles.py)
header_html = f"""
<div class="vc-header">
  <h1 class="vc-brand">{_BRAND_ICON}<span>Viral Cutter<span class="vc-edition">CHURCH EDITION</span></span></h1>
  <p class="vc-tagline">{i18n('Transforme sermões em cortes prontos para as redes sociais.')}</p>
</div>
"""

# Crédito discreto (GPL v3 exige preservar a atribuição) + ajuda da chave de IA.
about_html = f"""
<div style="line-height:1.7; font-size:0.95rem; color:#355A4C;">
  <h3 style="font-family:'Poppins',sans-serif; color:#08281D; margin-bottom:6px;">Viral Cutter · Church Edition</h3>
  <p>{i18n('Edição feita para igrejas: transforma vídeos longos de cultos e pregações em cortes verticais com legendas, prontos para Reels, Shorts e TikTok.')}</p>

  <div style="margin-top:18px; padding:16px 18px; background:#D6F2E2; border:1px solid #C3EDD6; border-left:4px solid #14C18E; border-radius:12px;">
    <h4 style="font-family:'Poppins',sans-serif; color:#0A7A5C; margin:0 0 8px 0;">🔑 {i18n('Como conseguir a chave de IA (grátis)')}</h4>
    <ol style="margin:0; padding-left:20px; color:#355A4C;">
      <li>{i18n('Acesse')} <a href="https://aistudio.google.com/app/apikey" target="_blank" style="color:#0E9D77; font-weight:600;">aistudio.google.com/app/apikey</a> {i18n('e entre com sua conta Google.')}</li>
      <li>{i18n('Clique em "Criar chave de API" (Create API key).')}</li>
      <li>{i18n('Copie a chave gerada (começa com "AIza...").')}</li>
      <li>{i18n('Cole no campo "Chave de IA" na aba Criar Cortes. Pronto — fica salva.')}</li>
    </ol>
  </div>

  <p style="margin-top:18px; font-size:0.85rem; color:#88A99A;">
    {i18n('Baseado no projeto de código aberto ViralCutter, de Rafael Godoy')}
    (<a href="https://github.com/rafaelGodoyEbert/ViralCutter" target="_blank" style="color:#0E9D77;">GitHub</a>),
    {i18n('licenciado sob a GNU GPL v3. Esta é uma versão modificada para uso em igrejas.')}
  </p>
</div>
"""
