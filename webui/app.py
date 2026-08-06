import gradio as gr
import subprocess
import os
import sys
import json
import copy
import psutil
import shutil
import datetime
import html
import random
import time
import urllib.parse
import uuid
from fastapi import Body, FastAPI, File, Form, UploadFile
from fastapi.staticfiles import StaticFiles
import uvicorn


import re
import library # Module for Library Logic
import subtitle_handler as subs # Module for Subtitles
import subtitle_editor as editor # Module for Editor Logic
import outro_handler # Module for Outro/Ending Logic
import watermark_handler # Module for Watermark Logic
import audio_handler # Module for Audio Overlay Logic
import original_volume_handler # Module for original source volume preview
import segment_editor_state # Per-segment dynamic editor state
import segment_editor_preview # Fast per-segment visual preview
import render_state # Applied feature flags per segment
try:
    from media_utils import extract_file_path, resolve_existing_path
except ImportError:
    from webui.media_utils import extract_file_path, resolve_existing_path

# Path to the main script
MAIN_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main_improved.py")
WORKING_DIR = os.path.dirname(MAIN_SCRIPT_PATH)
sys.path.append(WORKING_DIR)

from i18n.i18n import I18nAuto
# Church Edition é PT-first: força português independente do locale (no Colab costuma ser en_US).
i18n = I18nAuto(language="pt_BR")

VIRALS_DIR = os.path.join(WORKING_DIR, "VIRALS")
MODELS_DIR = os.path.join(WORKING_DIR, "models")
WEBUI_ASSETS_DIR = os.path.join(WORKING_DIR, "WEBUI_ASSETS")
WEBUI_PREVIEW_DIR = os.path.join(WORKING_DIR, "webui", "PREVIEW")

# Ensure directories exist
def _ensure_dir(path):
    # Symlink quebrado (ex.: VIRALS -> Drive desmontado no Colab) faria
    # os.makedirs falhar com FileExistsError. Remove o link morto e recria local.
    if os.path.islink(path) and not os.path.exists(path):
        print(f"[AVISO] Link quebrado em {path} (Drive desmontado?). Recriando como pasta local — "
              "rode a célula 1 do notebook para religar ao Google Drive.")
        try:
            os.unlink(path)
        except OSError:
            pass
    os.makedirs(path, exist_ok=True)

_ensure_dir(VIRALS_DIR)
_ensure_dir(MODELS_DIR)


def _running_in_colab():
    return bool(os.environ.get("COLAB_RELEASE_TAG")) or os.path.isdir("/content")


def _link_colab_persistent_configs():
    """Keep user settings and uploaded assets on Drive in Colab."""
    if not _running_in_colab():
        return

    real_virals = os.path.realpath(VIRALS_DIR)
    if not os.path.isdir(real_virals):
        return

    config_dir = os.path.join(real_virals, "_configuracoes")
    os.makedirs(config_dir, exist_ok=True)

    assets_remote = os.path.join(real_virals, "_webui_assets")
    try:
        if os.path.isdir(WEBUI_ASSETS_DIR) and not os.path.islink(WEBUI_ASSETS_DIR):
            shutil.copytree(WEBUI_ASSETS_DIR, assets_remote, dirs_exist_ok=True)
        else:
            os.makedirs(assets_remote, exist_ok=True)

        if os.path.islink(WEBUI_ASSETS_DIR):
            current_target = os.path.realpath(WEBUI_ASSETS_DIR)
            if os.path.abspath(current_target) != os.path.abspath(assets_remote):
                os.unlink(WEBUI_ASSETS_DIR)
        elif os.path.isdir(WEBUI_ASSETS_DIR):
            shutil.rmtree(WEBUI_ASSETS_DIR)

        if not os.path.exists(WEBUI_ASSETS_DIR):
            try:
                os.symlink(assets_remote, WEBUI_ASSETS_DIR)
            except OSError:
                if os.path.isdir(assets_remote) and not os.path.exists(WEBUI_ASSETS_DIR):
                    shutil.copytree(assets_remote, WEBUI_ASSETS_DIR, dirs_exist_ok=True)
                raise
    except OSError as e:
        print(f"[AVISO] Nao foi possivel vincular WEBUI_ASSETS ao Drive: {e}")

    config_files = [
        "api_config.json",
        "watermark_config.json",
        "outro_config.json",
        "audio_config.json",
        "ui_settings.json",
        "temp_subtitle_config.json",
    ]

    for name in config_files:
        local = os.path.join(WORKING_DIR, name)
        remote = os.path.join(config_dir, name)

        if not os.path.exists(remote):
            if os.path.isfile(local) and not os.path.islink(local):
                shutil.copy2(local, remote)
            elif name == "api_config.json":
                with open(remote, "w", encoding="utf-8") as f:
                    json.dump({
                        "selected_api": "gemini",
                        "gemini": {
                            "api_key": "",
                            "model": "gemini-3.6-flash",
                            "chunk_size": 70000,
                        },
                    }, f, indent=4)

        if os.path.exists(remote) and not os.path.isdir(local):
            try:
                if os.path.islink(local) or os.path.exists(local):
                    os.remove(local)
                os.symlink(remote, local)
            except OSError as e:
                print(f"[AVISO] Nao foi possivel vincular {name} ao Drive: {e}")


_link_colab_persistent_configs()

ALLOWED_DIRS = [
    os.path.abspath(VIRALS_DIR),
    os.path.abspath(WEBUI_ASSETS_DIR),
    os.path.abspath(WEBUI_PREVIEW_DIR),
]
try:
    gr.set_static_paths(paths=ALLOWED_DIRS)
except AttributeError:
    pass

# Global variables
current_process = None

# Helpers
def convert_color_to_ass(hex_color, alpha="00"):

    if not hex_color:
        return f"&H{alpha}FFFFFF&"
    
    hex_clean = hex_color.lstrip('#').strip()
    
    # Handle rgb/rgba format: rgb(255, 215, 0)
    if hex_clean.lower().startswith("rgb"):
        try:
            # Extract numbers including floats
            nums = re.findall(r"[\d\.]+", hex_clean)
            if len(nums) >= 3:
                r = int(float(nums[0]))
                g = int(float(nums[1]))
                b = int(float(nums[2]))
                # Clamp
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                # Convert to hex
                ret = f"&H{alpha}{b:02X}{g:02X}{r:02X}&".upper()
                return ret
        except Exception:
            pass

    # Handle 3-digit hex (e.g. F00 -> FF0000)
    if len(hex_clean) == 3:
        hex_clean = "".join([c*2 for c in hex_clean])
        
    if len(hex_clean) == 6:
        r = hex_clean[0:2]
        g = hex_clean[2:4]
        b = hex_clean[4:6]
        # Uppercase just in case
        ret = f"&H{alpha}{b}{g}{r}&".upper()
        return ret

    return f"&H{alpha}FFFFFF&"

def kill_process():
    global current_process
    if current_process:
        try:
            parent = psutil.Process(current_process.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
            current_process = None
            return i18n("Process terminated.")
        except Exception as e:
            return i18n("Error terminating process: {}").format(e)
    return i18n("No process running.")

GEMINI_MODELS = [
    'gemini-3.6-flash',
    'gemini-3-flash-preview'
]

# Subtitle logic moved to subtitle_handler.py


def _tail_log(text, max_lines=220, max_chars=22000):
    """Devolve só a cauda do log para enviar ao navegador.

    Em jobs longos o stdout do whisperx/ffmpeg vira centenas de KB. Mandar o
    buffer inteiro a cada yield faz o front re-renderizar um textarea gigante e
    re-escanear o log a cada atualização. Com a janela fora de foco isso vira
    uma fila enorme de re-renders que só "drena" quando o foco volta — e como o
    último yield é o que carrega a galeria, os vídeos só apareciam depois dos
    logs terminarem de rolar. Mandar só a cauda mantém cada atualização barata.
    """
    if not text:
        return text
    if len(text) > max_chars:
        text = text[-max_chars:]
    lines = text.splitlines()
    if len(lines) > max_lines:
        return "\n".join(lines[-max_lines:])
    return text


LOG_STREAM_INTERVAL_SECONDS = 3.0

PROCESSING_MESSAGES = [
    "Identificando melhores momentos...",
    "Analisando as Escrituras...",
    "Imitando os Bereianos...",
    "Garimpando o trecho que prende a atenção...",
    "Conferindo o contexto antes do corte...",
    "Separando ouro de ruído...",
    "Procurando frases que cabem no Reels...",
    "Lapidando legendas para a tela pequena...",
    "Montando cortes com começo, meio e graça...",
    "Buscando aquele momento compartilhável...",
    "Ajustando o ritmo sem perder a mensagem...",
    "Preparando tudo para sair redondinho...",
    "Checando se o gancho chega chegando...",
    "Organizando os clipes com calma e propósito...",
    "Fazendo o sermão virar cortes úteis...",
    "Procurando o melhor gancho do sermão...",
    "Conferindo se o corte tem começo forte...",
    "Separando uma mensagem boa para edificar o feed...",
    "Ouvindo com atenção pastoral...",
    "Cuidando para o contexto não sair do lugar...",
    "Ajustando o corte sem atropelar a mensagem...",
    "Peneirando frases com potencial de abençoar alguém...",
    "Marcando momentos que merecem replay...",
    "Organizando os trechos como quem prepara a liturgia...",
    "Buscando clareza, impacto e fidelidade ao conteúdo...",
    "Deixando o vídeo pronto para a missão digital...",
    "Selecionando partes que podem alcançar mais gente...",
    "Dando uma lapidada santa nas legendas...",
    "Separando pão quentinho para as redes...",
    "Procurando o amém visual do corte...",
    "Checando se a mensagem fica clara sem o vídeo inteiro...",
    "Preparando um corte que dá vontade de enviar no grupo...",
    "Fazendo o trecho caber no tempo sem perder a unção...",
    "Ajustando cada segundo com zelo e carinho...",
    "Buscando frases que apontam para Cristo...",
    "Organizando tudo para servir melhor a igreja...",
    "Cuidando da legenda para ninguém perder a frase boa...",
    "Procurando o momento em que a mensagem acende...",
    "Tirando excesso sem tirar essência...",
    "Conferindo se o corte segue edificante...",
    "Dando ritmo de short sem pressa no coração...",
    "Preparando o material para evangelizar no scroll...",
    "Chamando os melhores trechos para a frente...",
    "Ajustando a cadência da fala nas legendas...",
    "Cuidando para o corte terminar no lugar certo...",
    "Buscando um trecho que pare o polegar no feed...",
    "Fazendo revisão de contexto, estilo Bereia...",
    "Separando o que é forte, claro e compartilhável...",
    "Montando o corte com zelo de equipe de mídia...",
    "Deixando as legendas legíveis para todo mundo...",
    "Procurando aquele trecho que vira conversa depois do culto...",
    "Ajustando áudio, imagem e mensagem para caminharem juntos...",
    "Preparando cortes para fortalecer a comunicação da igreja...",
    "Cuidando dos detalhes enquanto você pode respirar um pouco...",
    "Verificando se a ideia principal aparece rápido...",
    "Organizando o sermão em pequenos convites de atenção...",
    "Selecionando trechos com verdade e boa retenção...",
    "Polindo o conteúdo sem mexer na essência...",
    "Transformando minutos preciosos em cortes certeiros...",
    "Preparando tudo para a igreja postar com tranquilidade...",
    "Alinhando legendas, cortes e propósito...",
    "Separando momentos que podem tocar alguém hoje...",
    "Fazendo a parte técnica trabalhar em silêncio...",
    "Mantendo a mensagem no centro do corte...",
    "Quase lá: ainda cuidando dos detalhes finais...",
    "Conferindo o corte com amor pela sã doutrina...",
    "Deixando a mensagem clara, simples e confessional...",
    "Separando um trecho com cheiro de púlpito fiel...",
    "Organizando tudo com decência e boa ordem...",
    "Buscando um recorte que honre o texto bíblico...",
    "Mantendo a Escritura acima do algoritmo...",
    "Lapidando sem transformar sermão em entretenimento vazio...",
    "Procurando um trecho que sirva à igreja, não só ao feed...",
    "Cuidando para a graça continuar no centro...",
    "Separando conteúdo com convicção reformada...",
    "Conferindo se a aplicação ficou bem amarrada ao texto...",
    "Transformando o sermão em corte sem perder reverência...",
    "Ajustando o ritmo com zelo e sobriedade...",
    "Buscando clareza sem diluir a mensagem...",
    "Deixando o corte pronto para edificar os santos...",
    "Preparando um trecho para fortalecer a fé no meio da semana...",
    "Cortando com cuidado de quem ama boa teologia...",
    "Mantendo o foco na Palavra, não no barulho...",
    "Selecionando frases que apontam para a suficiência das Escrituras...",
    "Polindo detalhes com espírito de catecismo...",
    "Separando uma pequena porção de doutrina boa...",
    "Cuidando para a legenda não tropeçar na teologia...",
    "Buscando um momento que ajude a igreja a lembrar da graça...",
    "Ajustando o corte com zelo pastoral e técnico...",
    "Procurando um trecho que faça sentido fora do culto inteiro...",
    "Mantendo a soberania de Deus no centro da narrativa...",
    "Preparando cortes com reverência e boa comunicação...",
    "Separando uma frase que poderia virar anotação de sermão...",
    "Checando se o recorte preserva o argumento do pregador...",
    "Dando forma curta a uma verdade antiga...",
    "Cuidando para a edição servir à mensagem...",
    "Buscando impacto sem apelar para sensacionalismo...",
    "Lapidando uma verdade bíblica para o formato vertical...",
    "Organizando o corte como quem prepara ordem de culto...",
    "Separando trechos com sabor de sola Scriptura...",
    "Conferindo se o trecho permanece fiel ao contexto...",
    "Deixando o clipe pronto para uma igreja que pensa...",
    "Preparando material para discipulado no feed...",
    "Buscando frases que ajudem a família da fé...",
    "Ajustando segundos com paciência presbiteriana...",
    "Cuidando do corte com zelo confessional...",
    "Separando momentos de lei, graça e aplicação...",
    "Mantendo a edição debaixo da Palavra...",
    "Preparando um corte digno do mural da igreja...",
    "Procurando o trecho que explica bem antes de emocionar...",
    "Deixando a teologia respirar dentro do formato curto...",
    "Selecionando uma frase com peso de boa doutrina...",
    "Cuidando para o gancho não roubar o evangelho...",
    "Ajustando a legenda para servir quem assiste sem som...",
    "Separando pequenos convites à leitura bíblica...",
    "Buscando clareza para quem caiu de paraquedas no vídeo...",
    "Polindo o corte como quem revisa boletim dominical...",
    "Preparando o conteúdo para ser útil, não só bonito...",
    "Guardando o contexto como um bom bereiano faria...",
    "Selecionando trechos com verdade, beleza e sobriedade...",
    "Deixando o sermão viajar sem perder o endereço bíblico...",
    "Ajustando tudo com um olho no texto e outro na timeline...",
    "Separando uma porção curta de alimento sólido...",
    "Mantendo a graça comum até na renderização...",
    "Procurando momentos que ajudem a igreja a perseverar...",
    "Cuidando para o corte soar como igreja, não como trend vazia...",
    "Preparando legendas que respeitam a cadência do pregador...",
    "Buscando um trecho bom para enviar no grupo de estudo...",
    "Ajustando o vídeo com zelo de ministério de mídia...",
    "Separando algo que combine com domingo e segunda-feira...",
    "Conferindo se a chamada combina com a mensagem...",
    "Mantendo o tom reverente sem ficar engessado...",
    "Transformando o sermão em ponte para novas conversas...",
    "Buscando um recorte que una verdade e clareza...",
    "Deixando o conteúdo pronto para servir a comunidade da aliança...",
    "Preparando um pequeno eco da pregação para a semana...",
    "Cortando sem cortar a linha de raciocínio...",
    "Cuidando para a estética obedecer ao conteúdo...",
    "Separando tesouros antigos em embalagem de hoje...",
    "Ajustando o corte com calma sabática...",
    "Buscando o trecho que deixa a doutrina mais memorável...",
    "Mantendo Cristo no centro, inclusive no thumbnail mental...",
    "Preparando cortes para uma comunicação reformada e bonita...",
    "Selecionando frases que lembram graça, fé e arrependimento...",
    "Deixando o vídeo pronto para edificar sem gritar...",
    "Organizando a mensagem para caber no feed sem encolher a verdade...",
    "Procurando uma aplicação que chegue mansa e firme...",
    "Cuidando para cada corte ter começo honesto e final claro...",
    "Polindo uma pequena janela para a pregação inteira...",
    "Separando conteúdo que ajuda a igreja a confessar melhor...",
    "Ajustando tudo com zelo, ordem e um cafezinho imaginário...",
    "Buscando o trecho que aponta para o Deus soberano...",
    "Mantendo a edição discreta para a Palavra aparecer...",
    "Preparando um corte que poderia sair depois da Escola Dominical...",
    "Conferindo se a frase sustenta o peso fora do contexto longo...",
    "Deixando a mensagem compartilhável sem virar rasa...",
    "Selecionando trechos com coração pastoral e cabeça reformada...",
    "Ajustando o corte como quem afina o coral antes do culto...",
    "Separando um momento que ajude alguém a voltar para a Bíblia...",
    "Cuidando para a tecnologia servir ao Reino com sobriedade...",
    "Preparando clipes com teologia robusta e legenda legível...",
    "Buscando a frase que dá vontade de abrir a Bíblia...",
    "Mantendo a beleza a serviço da verdade...",
    "Cortando com cuidado, porque contexto também é mordomia...",
    "Organizando tudo para comunicar graça com clareza...",
    "Separando uma pequena janela para a grande história da redenção...",
    "Ajustando a edição para não competir com o conteúdo...",
    "Preparando o vídeo com aquele toque de ordem reformada...",
    "Buscando um momento que seja fiel, útil e compartilhável...",
    "Deixando o corte pronto para sair em paz no feed da igreja...",
]

KEEP_TAB_OPEN_NOTE = "Mantenha esta aba aberta, mas não precisa ficar aqui esperando."


def _stage_title(text):
    return f"{text}. {KEEP_TAB_OPEN_NOTE}"


def _processing_status_html(kind="running", title=None, message=None, messages=None):
    icon_map = {
        "running": "sparkles",
        "done": "check",
        "error": "alert-triangle",
        "manual": "edit",
    }
    rotating_messages = []
    if kind == "running":
        rotating_messages = list(messages if messages is not None else PROCESSING_MESSAGES)
        random.shuffle(rotating_messages)

    default_title = {
        "running": _stage_title("Gerando seus cortes"),
        "done": "Pronto! Seus cortes estão na tela.",
        "error": "Algo deu errado.",
        "manual": "Revisão manual pronta.",
    }.get(kind, _stage_title("Gerando seus cortes"))
    default_message = {
        "running": rotating_messages[0] if rotating_messages else PROCESSING_MESSAGES[0],
        "done": "Pode revisar, baixar ou ajustar as legendas agora.",
        "error": 'Abra "Ver detalhes técnicos" para ver o log.',
        "manual": "Confira o prompt e continue quando estiver tudo certo.",
    }.get(kind, "")

    title = html.escape(title or default_title)
    message = html.escape(message or default_message)
    data_messages = html.escape(json.dumps(rotating_messages, ensure_ascii=False), quote=True)
    rotating_attr = f' data-rotating="1" data-messages="{data_messages}" data-message-index="0"' if rotating_messages else ""
    spinner = '<span class="vc-processing-spinner" aria-hidden="true"></span>' if kind == "running" else ""
    try:
        status_icon = icon(icon_map.get(kind, "sparkles"), 20)
    except Exception:
        status_icon = ""

    return (
        f'<div class="vc-processing-status is-{kind}"{rotating_attr}>'
        f'<div class="vc-processing-mark">{spinner}<span class="vc-processing-icon">{status_icon}</span></div>'
        f'<div class="vc-processing-copy">'
        f'<div class="vc-processing-title">{title}</div>'
        f'<div class="vc-processing-message">{message}</div>'
        f'</div></div>'
    )


def _infer_processing_status(logs, tick=0):
    tail = (logs or "")[-8000:].lower()
    title = _stage_title("Gerando seus cortes")
    if any(term in tail for term in ("frame=", "ffmpeg", "render", "renderizando", "editing", "editando")):
        title = _stage_title("Renderizando os cortes")
    elif any(term in tail for term in ("legenda", "subtitle", "ass", "srt")):
        title = _stage_title("Preparando legendas")
    elif any(term in tail for term in ("cortando", "cutting", "segmento", "segment")):
        title = _stage_title("Cortando os melhores trechos")
    elif any(term in tail for term in ("viral", "gemini", "analisando", "analyz")):
        title = _stage_title("Escolhendo os melhores momentos")
    elif any(term in tail for term in ("transcre", "transcrib", "whisper")):
        title = _stage_title("Transcrevendo o áudio")
    elif any(term in tail for term in ("download", "baixando", "yt-dlp")):
        title = _stage_title("Baixando o vídeo")

    return _processing_status_html("running", title=title, messages=PROCESSING_MESSAGES)


def run_viral_cutter(input_source, project_name, url, video_file, segments, viral, hook_mode, themes, min_duration, max_duration, ai_duration, model, manual_mode, api_key, ai_model_name, chunk_size, workflow,
                     use_custom_subs, font_name, font_size, font_color, highlight_color, outline_color, outline_thickness, shadow_color, shadow_size, is_bold, is_italic, is_uppercase, vertical_pos, margin_h, alignment,
                     h_size, w_block, gap, mode, under, strike, border_s, remove_punc, video_quality, use_youtube_subs):

    global current_process

    # --- Normaliza campos numéricos (gr.Number devolve None se o campo for
    # apagado; sem isso, int(None) mata o gerador e o botão fica preso em
    # "Gerando..." até recarregar a página) ---
    def _safe_int(value, default):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default
    segments = _safe_int(segments, DEFAULT_UI_SETTINGS["segments"])
    min_duration = _safe_int(min_duration, DEFAULT_UI_SETTINGS["min_duration"])
    max_duration = _safe_int(max_duration, DEFAULT_UI_SETTINGS["max_duration"])
    chunk_size = _safe_int(chunk_size, DEFAULT_UI_SETTINGS["chunk_size"])

    # --- SAVE UI STATE ---
    ui_state_to_save = {
        "video_quality": video_quality, "use_youtube_subs": use_youtube_subs,
        "segments": segments, "viral": viral, "hook_mode": hook_mode, "themes": themes, "min_duration": min_duration, "max_duration": max_duration, "ai_duration": ai_duration,
        "model": model, "manual_mode": manual_mode, "ai_model_name": ai_model_name, "chunk_size": chunk_size, "workflow": workflow,
        "font_name": font_name, "font_size": font_size, "font_color": font_color, "highlight_color": highlight_color,
        "outline_color": outline_color, "outline_thickness": outline_thickness, "shadow_color": shadow_color,
        "shadow_size": shadow_size, "is_bold": is_bold, "is_italic": is_italic, "is_uppercase": is_uppercase,
        "vertical_pos": vertical_pos, "margin_h": margin_h, "alignment": alignment,
        "h_size": h_size, "w_block": w_block, "gap": gap, "mode": mode,
        "under": under, "strike": strike, "border_s": border_s, "remove_punc": remove_punc,
    }
    try:
        with open(os.path.join(WORKING_DIR, "ui_settings.json"), "w", encoding="utf-8") as f:
            json.dump(ui_state_to_save, f, indent=4)
    except: pass
    # Persiste a chave de IA (digita 1x e fica salva em api_config.json).
    save_api_key(api_key)
    # ---------------------

    yield "", gr.update(value=i18n("Gerando..."), interactive=False), gr.update(visible=True), _processing_status_html("running"), "", gr.update(visible=False), None

    cmd = [sys.executable, MAIN_SCRIPT_PATH]
    cmd.extend(["--language", "pt"])
    
    # Input Source Logic
    if input_source == "Existing Project":
        if not project_name:
             yield i18n("Error: No project selected."), gr.update(value=i18n("Gerar meus cortes"), interactive=True), gr.update(visible=False), _processing_status_html("error", "Escolha um projeto antes de gerar."), "", gr.update(visible=False), None
             return
        full_project_path = os.path.join(VIRALS_DIR, project_name)
        cmd.extend(["--project-path", full_project_path])
    elif input_source == "Upload Video":
        if not video_file:
             yield i18n("Error: No video file uploaded."), gr.update(value=i18n("Gerar meus cortes"), interactive=True), gr.update(visible=False), _processing_status_html("error", "Envie um vídeo antes de gerar."), "", gr.update(visible=False), None
             return

        video_file_path = resolve_existing_path(extract_file_path(video_file))
        if not video_file_path:
             yield i18n("Error: Uploaded video file could not be found."), gr.update(value=i18n("Gerar meus cortes"), interactive=True), gr.update(visible=False), _processing_status_html("error", "Não encontrei o vídeo enviado."), "", gr.update(visible=False), None
             return
        
        # Determine project name from filename
        original_filename = os.path.basename(video_file_path)
        name_no_ext = os.path.splitext(original_filename)[0]
        # Sanitize: Allow alphanumeric, space, dash, underscore
        safe_name = "".join([c for c in name_no_ext if c.isalnum() or c in " _-"]).strip()
        if not safe_name: safe_name = "Untitled_Upload"
        
        # Always append timestamp as requested
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name_upload = f"{safe_name}_{timestamp}"
        project_path = os.path.join(VIRALS_DIR, project_name_upload)
             
        os.makedirs(project_path, exist_ok=True)
        
        target_path = os.path.join(project_path, "input.mp4")
        shutil.copy(video_file_path, target_path)
        
        cmd.extend(["--project-path", project_path])
        # Skip YouTube subs as it is a local upload
        cmd.append("--skip-youtube-subs")
        
    else:
        if url: cmd.extend(["--url", url])
        # Pass Video Quality
        if video_quality: cmd.extend(["--video-quality", video_quality])
        # Pass Subtitle Option (if False, we skip)
        if not use_youtube_subs: cmd.append("--skip-youtube-subs")
        
    cmd.extend(["--segments", str(int(segments))])
    if viral: cmd.append("--viral")
    if hook_mode: cmd.append("--hook-mode")
    if themes: cmd.extend(["--themes", themes])
    cmd.extend(["--min-duration", str(int(min_duration))])
    cmd.extend(["--max-duration", str(int(max_duration))])
    if ai_duration: cmd.append("--ai-duration")
    cmd.extend(["--model", model])
    if manual_mode: cmd.append("--manual-webui")
    # A chave já foi persistida em api_config.json (lido pelo main). Só passa na
    # linha de comando se a persistência falhou — argv é visível a outros processos.
    if api_key and load_saved_api_key() != (api_key or "").strip():
        cmd.extend(["--api-key", api_key])

    # AI Params
    if ai_model_name: cmd.extend(["--ai-model-name", str(ai_model_name)])
    if chunk_size: cmd.extend(["--chunk-size", str(int(chunk_size))])

    workflow_map = {"Full": "1", "Cut Only": "2", "Subtitles Only": "3"}
    cmd.extend(["--workflow", workflow_map.get(workflow, "1")])

    cmd.append("--skip-prompts") # Always skip prompts in WebUI to prevent freezing

    watermark_config_path = os.path.join(WORKING_DIR, "watermark_config.json")
    if os.path.exists(watermark_config_path):
        try:
            with open(watermark_config_path, "r", encoding="utf-8") as f:
                wcfg = json.load(f)
                if wcfg.get("enabled", False):
                    cmd.extend(["--watermark-config", watermark_config_path])
        except Exception as e:
            print(f"Warning: failed to load watermark config: {e}")

    outro_config_path = os.path.join(WORKING_DIR, "outro_config.json")
    if os.path.exists(outro_config_path):
        try:
            with open(outro_config_path, "r", encoding="utf-8") as f:
                ocfg = json.load(f)
                if ocfg.get("enabled", False):
                    cmd.extend(["--outro-config", outro_config_path])
        except Exception as e:
            print(f"Warning: failed to load outro config: {e}")

    audio_config_path = os.path.join(WORKING_DIR, "audio_config.json")
    if os.path.exists(audio_config_path):
        try:
            with open(audio_config_path, "r", encoding="utf-8") as f:
                acfg = json.load(f)
                try:
                    source_video_volume = float(acfg.get("source_video_volume", 200.0))
                except (TypeError, ValueError):
                    source_video_volume = 200.0
                if acfg.get("enabled", False) or abs(source_video_volume - 100.0) > 0.001:
                    cmd.extend(["--audio-config", audio_config_path])
        except Exception as e:
            print(f"Warning: failed to load audio config: {e}")

    if use_custom_subs:
        subtitle_config = {
            "font": font_name, "base_size": int(font_size), "base_color": convert_color_to_ass(font_color), "highlight_color": convert_color_to_ass(highlight_color),
            "outline_color": convert_color_to_ass(outline_color), "outline_thickness": outline_thickness, "shadow_color": convert_color_to_ass(shadow_color),
            "shadow_size": shadow_size, "vertical_position": vertical_pos, "margin_h": margin_h, "alignment": alignment, "bold": 1 if is_bold else 0, "italic": 1 if is_italic else 0, 
            "underline": 1 if under else 0, "strikeout": 1 if strike else 0, "border_style": border_s, "words_per_block": int(w_block), "gap_limit": gap,
            "mode": mode, "highlight_size": int(h_size), "remove_punctuation": remove_punc
        }
        # Uppercase is handled in main script or logic? 
        # Actually subtitle_config doesn't seem to natively support "uppercase" in get_subtitle_config default, but app.py was using it. 
        # I should probably add it back if I want to support it, but user said "PROHIBITED to remove existing ones".
        # I'll re-add 'uppercase': 1 if is_uppercase else 0 to the dict if the backend supports it, otherwise it's just ignored.
        # But wait, main_improved.py doesn't have 'uppercase' in get_subtitle_config. 
        # I'll keep it in the dict just in case logic uses it elsewhere or if I missed it.
        # Actually, standard ASS doesn't support uppercase flag directly in Style, it needs to be text transform.
        # But I'll leave it in the dict.
        subtitle_config["uppercase"] = 1 if is_uppercase else 0

        subtitle_config_path = os.path.join(WORKING_DIR, "temp_subtitle_config.json")
        try:
            with open(subtitle_config_path, "w", encoding="utf-8") as f:
                json.dump(subtitle_config, f, indent=4)
            cmd.extend(["--subtitle-config", subtitle_config_path])
        except Exception as e:
            print(f"Warning: failed to write temp subtitle config: {e}")
    
    logs = ""
    project_folder_path = None
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        current_process = subprocess.Popen(cmd, cwd=WORKING_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True, env=env)
        if input_source == "Existing Project" and project_name:
             # If using existing project, we already know the path, but let's see if logs confirm it
             project_folder_path = os.path.join(VIRALS_DIR, project_name)

        last_update_time = time.time()
        status_tick = 1
        
        while True:
            line = current_process.stdout.readline()
            if not line and current_process.poll() is not None:
                break
            
            if line:
                logs += line
                if "Project Folder:" in line:
                    parts = line.split("Project Folder:")
                    if len(parts) > 1: project_folder_path = parts[1].strip()
                
                # Throttle (0.5s) + manda só a cauda do log: menos atualizações
                # e cada uma barata, pra fila não acumular quando a janela está
                # fora de foco (senão a galeria, que vem no último yield, só
                # aparecia depois dos logs terminarem de rolar).
                current_time = time.time()
                if current_time - last_update_time > LOG_STREAM_INTERVAL_SECONDS:
                    yield _tail_log(logs, max_lines=120, max_chars=14000), gr.update(visible=True, interactive=False), gr.update(visible=True), _infer_processing_status(logs, status_tick), gr.update(), gr.update(visible=False), None
                    last_update_time = current_time
                    status_tick += 1

    except Exception as e:
        logs += f"\nError running process: {str(e)}\n"
        yield _tail_log(logs), gr.update(value=i18n("Gerar meus cortes"), interactive=True), gr.update(visible=False), _processing_status_html("error"), gr.update(), gr.update(), gr.update()
    finally:
        if current_process:
            if current_process.stdout:
                try:
                    current_process.stdout.close()
                except Exception: pass
            if current_process.poll() is None:
                # If we are here, it means we finished reading or errored out, but process is still running.
                # If it was a normal break from loop, process should be done or close to done.
                # If we are stopping, current_process.terminate() might be needed outside? 
                # But here we just wait.
                try:
                    current_process.wait()
                except Exception: pass
            current_process = None
    
    # Wait to ensure filesystem flush
    time.sleep(1.0)
    
    # PAUSE CHECK:
    if "[PAUSE_FOR_MANUAL_WEBUI]" in logs:
        # Extrair prompt
        prompt_content = ""
        if project_folder_path:
            try:
                 with open(os.path.join(project_folder_path, "prompt_full.txt"), "r", encoding="utf-8") as f:
                      prompt_content = f.read()
            except: prompt_content = "Erro lendo prompt_full.txt. Acesse a pasta do projeto."
            
        yield _tail_log(logs), gr.update(value=i18n("Gerar meus cortes"), interactive=True), gr.update(visible=False), _processing_status_html("manual"), "", gr.update(visible=True), prompt_content
        return

    html_output = ""
    status_output = _processing_status_html("done")
    if project_folder_path and os.path.exists(project_folder_path):
        html_output = library.generate_project_gallery(project_folder_path, is_full_path=True)
    else:
        html_output = f"<h3>{i18n('Error: Project folder could not be determined from logs.')}</h3>"
        status_output = _processing_status_html("error", "Não encontrei a pasta do projeto.", "Os detalhes técnicos podem ajudar a localizar onde o processo parou.")
    yield _tail_log(logs), gr.update(value=i18n("Gerar meus cortes"), interactive=True), gr.update(visible=False), status_output, html_output, gr.update(visible=False), None

# Tema e estilos da marca (Church Edition) — paleta esmeralda + branco.
import styles
from styles import CSS as css
from theme import build_theme, PALETTE
try:
    from icons import icon
except ImportError:
    from webui.icons import icon

import header

# --- Chave de IA (Gemini): salvar/carregar de api_config.json p/ digitar só 1 vez ---
API_CONFIG_PATH = os.path.join(WORKING_DIR, "api_config.json")

def load_saved_api_key():
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return ((cfg.get("gemini", {}) or {}).get("api_key") or "").strip()
    except Exception:
        return ""

def save_api_key(key):
    key = (key or "").strip()
    if not key:
        return
    cfg = {}
    try:
        if os.path.exists(API_CONFIG_PATH):
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg.setdefault("selected_api", "gemini")
    cfg.setdefault("gemini", {})["api_key"] = key
    try:
        with open(API_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception:
        pass

def api_key_status_html():
    if load_saved_api_key():
        return (f"<div class='vc-icon-inline' style='color:var(--vc-primary-deep);font-size:0.9rem;font-weight:600;'>"
                f"{icon('check', 17)}<span>{i18n('Chave de IA salva — não precisa digitar de novo.')}</span></div>")
    return (f"<div style='color:var(--vc-text-muted);font-size:0.9rem;'>"
            f"{i18n('Nenhuma chave salva ainda.')}</div>")

UI_SETTINGS_PATH = os.path.join(WORKING_DIR, "ui_settings.json")

# Padrão de fábrica das configurações de corte. O botão "Restaurar padrões"
# volta tudo para cá; e o que o usuário muda é salvo ao vivo como novo padrão.
DEFAULT_UI_SETTINGS = {
    "video_quality": "best",
    "use_youtube_subs": False,
    "segments": 12,
    "viral": True,
    "hook_mode": False,
    "themes": "",
    "min_duration": 60,
    "max_duration": 140,
    "ai_duration": True,
    "model": "large-v3-turbo",
    "manual_mode": False,
    "ai_model_name": GEMINI_MODELS[0],
    "chunk_size": 70000,
    "workflow": "Full",
    "font_name": "Montserrat",
    "font_size": 30,
    "font_color": "#FFFFFF",
    "highlight_color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_thickness": 1,
    "shadow_color": "#000000",
    "shadow_size": 1,
    "is_bold": True,
    "is_italic": False,
    "is_uppercase": False,
    "vertical_pos": 115,
    "margin_h": 35,
    "alignment": 2,
    "h_size": 30,
    "w_block": 4,
    "gap": 0.6,
    "mode": "no_highlight",
    "under": False,
    "strike": False,
    "border_s": 1,
    "remove_punc": False,
}

def load_ui_state():
    # Mescla sobre o padrão de fábrica para que toda chave exista.
    state = dict(DEFAULT_UI_SETTINGS)
    if os.path.exists(UI_SETTINGS_PATH):
        try:
            with open(UI_SETTINGS_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass
    return state

def save_ui_settings_live(video_quality, use_youtube_subs, segments, viral, themes,
                          min_duration, max_duration, ai_duration, model, manual_mode,
                          ai_model_name, chunk_size, workflow, margin_h, hook_mode, **extra):
    """Salva ao vivo o que o usuário mudou — vira o novo padrão na próxima abertura."""
    data = load_ui_state()
    data.update({
        "video_quality": video_quality, "use_youtube_subs": use_youtube_subs,
        "segments": segments, "viral": viral, "themes": themes,
        "min_duration": min_duration, "max_duration": max_duration, "ai_duration": ai_duration,
        "model": model, "manual_mode": manual_mode, "ai_model_name": ai_model_name,
        "chunk_size": chunk_size, "workflow": workflow, "margin_h": margin_h,
        "hook_mode": hook_mode,
    })
    data.update(extra)
    try:
        with open(UI_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass
    return ""


def save_subtitle_settings_live(font_name, font_size, font_color, highlight_color,
                                outline_color, outline_thickness, shadow_color, shadow_size,
                                is_bold, is_italic, is_uppercase, h_size, w_block,
                                gap, mode, under, strike, border_s, vertical_pos,
                                margin_h, alignment, remove_punc):
    data = load_ui_state()
    data.update({
        "font_name": font_name, "font_size": font_size, "font_color": font_color,
        "highlight_color": highlight_color, "outline_color": outline_color,
        "outline_thickness": outline_thickness, "shadow_color": shadow_color,
        "shadow_size": shadow_size, "is_bold": is_bold, "is_italic": is_italic,
        "is_uppercase": is_uppercase, "h_size": h_size, "w_block": w_block,
        "gap": gap, "mode": mode, "under": under, "strike": strike,
        "border_s": border_s, "vertical_pos": vertical_pos,
        "margin_h": margin_h, "alignment": alignment, "remove_punc": remove_punc,
    })
    try:
        with open(UI_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass
    return ""

ui_state = load_ui_state()

def get_active_modules_html():
    active = []
    
    try:
        cfg = watermark_handler.load_watermark_config()
        if cfg.get("enabled", False):
            label = i18n("Marca d'água")
            active.append(f"{icon('droplet', 15)}<span>{label}</span>")
    except: pass

    try:
        cfg = audio_handler.load_audio_config()
        if cfg.get("enabled", False):
            active.append(f"{icon('music', 15)}<span>{i18n('Áudio BGM')}</span>")
        try:
            source_volume = float(cfg.get("source_video_volume", 200.0))
        except (TypeError, ValueError):
            source_volume = 200.0
        if abs(source_volume - 100.0) > 0.001:
            label = i18n("Volume Original ({}%)").format(int(round(source_volume)))
            active.append(f"{icon('volume-2', 15)}<span>{label}</span>")
    except: pass

    try:
        cfg = outro_handler.load_outro_config()
        if cfg.get("enabled", False):
            active.append(f"{icon('film', 15)}<span>{i18n('Outro')}</span>")
    except: pass
    
    if active:
        items = ''.join(f"<span class='vc-chip'>{item}</span>" for item in active)
        return f"<div class='vc-active-modules' style='flex-grow:1; padding:8px 15px; border-radius:10px; font-size:0.95em; font-weight:600; display:flex; align-items:center; justify-content:center; gap:8px; flex-wrap:wrap;'><b>{i18n('Módulos Ativos')}:</b>{items}</div>"
    else:
        return f"<div class='vc-active-modules' style='flex-grow:1; padding:8px 15px; border-radius:10px; color:var(--vc-text-muted); font-size:0.95em; display:flex; align-items:center; justify-content:center;'>{i18n('Nenhum módulo extra ativo para este projeto.')}</div>"

def _pick_uploaded_or_saved(uploaded_file, saved_path):
    return uploaded_file or saved_path


def _watermark_preview_from_saved(uploaded_image, saved_image, x, y, scale, opacity):
    image_path = _pick_uploaded_or_saved(uploaded_image, saved_image)
    return watermark_handler.generate_watermark_preview(image_path, x, y, scale, opacity)


def _save_watermark_config_and_state(enabled, watermark_image_path, position_x, position_y, scale, opacity):
    status = watermark_handler.save_watermark_config(
        enabled, watermark_image_path, position_x, position_y, scale, opacity
    )
    cfg = watermark_handler.load_watermark_config()
    return status, cfg.get("watermark_image_path")


def _audio_preview_from_saved(video_file, uploaded_audio, saved_audio, base_volume, loop_bgm=True):
    audio_path = _pick_uploaded_or_saved(uploaded_audio, saved_audio)
    return audio_handler.generate_audio_preview(video_file, audio_path, base_volume, loop_bgm)


def _outro_preview_from_saved(uploaded_video, saved_video, uploaded_image, saved_image, x, y, scale, rounded_corners=0):
    video_path = _pick_uploaded_or_saved(uploaded_video, saved_video)
    image_path = _pick_uploaded_or_saved(uploaded_image, saved_image)
    return outro_handler.generate_outro_preview(video_path, image_path, x, y, scale, rounded_corners)


def _save_outro_config_and_state(enabled, outro_video_path, overlay_image_path, position_x, position_y, scale, fade_duration, rounded_corners, outro_volume):
    status = outro_handler.save_outro_config(
        enabled, outro_video_path, overlay_image_path, position_x, position_y, scale, fade_duration, rounded_corners, outro_volume
    )
    cfg = outro_handler.load_outro_config()
    return status, cfg.get("outro_video_path"), cfg.get("overlay_image_path")


def _asset_status_html(rows):
    """Render the currently-saved asset filenames so users can see what is configured.

    `rows` is a list of (description, path) tuples. The upload widgets always look
    empty (Gradio does not preload saved files), so this label is what tells the
    user an asset is actually saved and active.
    """
    html_rows = []
    for desc, path in rows:
        if path and os.path.exists(path):
            html_rows.append(
                f"<div class='vc-icon-inline' style='color:var(--vc-primary-deep);'>{icon('check', 15)}<span>{desc}: <b>{os.path.basename(path)}</b></span></div>"
            )
        else:
            html_rows.append(
                f"<div style='color:var(--vc-text-muted);'>- {desc}: {i18n('nenhum arquivo salvo')}</div>"
            )
    return (
        f"<div style='font-size:0.85em; line-height:1.5; padding:6px 10px; "
        f"background:var(--vc-surface-soft); border:1px solid var(--vc-border); border-radius:10px;'>"
        + "".join(html_rows)
        + "</div>"
    )


def _outro_assets_from_state(saved_video, saved_image):
    return _asset_status_html([
        (i18n("Vídeo de Encerramento salvo"), saved_video),
        (i18n("Imagem Overlay salva"), saved_image),
    ])


def _watermark_asset_from_state(saved_image):
    return _asset_status_html([(i18n("Imagem da Marca d'água salva"), saved_image)])


def _audio_assets_from_state(saved_audio, saved_outro_music):
    return _asset_status_html([
        (i18n("Áudio BGM salvo"), saved_audio),
        (i18n("Música de Encerramento salva"), saved_outro_music),
    ])


_global_js = """
(async () => {
    const st = document.createElement('style');
    st.textContent = '@keyframes vc-spin{to{transform:rotate(360deg)}}.vc-spin{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border:2px solid rgba(70,160,133,0.25);border-top-color:#46A085;border-radius:50%;animation:vc-spin .8s linear infinite}.vc-ok{color:#46A085!important;transform:scale(1.3);transition:all .3s}.vc-err{color:#E11D48!important;transform:scale(1.3);transition:all .3s}.apply-feature-btn:not(.applied):hover{filter:brightness(1.12)}.apply-feature-btn.applied:hover{background:#DC2626!important;color:#fff!important;border-color:#DC2626!important;cursor:pointer!important;filter:none!important}.apply-feature-btn .vc-feature-icon-remove{display:none}.apply-feature-btn.applied:hover .vc-feature-icon-current{display:none}.apply-feature-btn.applied:hover .vc-feature-icon-remove{display:inline-flex}';
    document.head.appendChild(st);
    const vcIconPaths = {
        alert: '<path d="m21.7 18.9-8.5-15a1.4 1.4 0 0 0-2.4 0l-8.5 15A1.4 1.4 0 0 0 3.5 21h17a1.4 1.4 0 0 0 1.2-2.1Z"></path><path d="M12 9v4"></path><path d="M12 17h.01"></path>',
        broom: '<path d="M3 21h12"></path><path d="M5 21v-4.5L14.5 7"></path><path d="m14 7 3-3 3 3-3 3z"></path><path d="M8 16h7l-2 5H6z"></path>',
        check: '<path d="M20 6 9 17l-5-5"></path>',
        download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="M7 10l5 5 5-5"></path><path d="M12 15V3"></path>',
        droplet: '<path d="M12 22a7 7 0 0 0 7-7c0-4-7-13-7-13S5 11 5 15a7 7 0 0 0 7 7Z"></path>',
        edit: '<path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>',
        film: '<rect x="3" y="3" width="18" height="18" rx="2"></rect><path d="M7 3v18"></path><path d="M17 3v18"></path><path d="M3 8h4"></path><path d="M17 8h4"></path><path d="M3 16h4"></path><path d="M17 16h4"></path>',
        folder: '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"></path>',
        key: '<circle cx="7.5" cy="15.5" r="5.5"></circle><path d="m21 2-9.6 9.6"></path><path d="m15 8 3 3"></path><path d="m17 6 3 3"></path>',
        lightbulb: '<path d="M15 14c.2-1.1.8-1.8 1.5-2.7A6 6 0 1 0 7.5 11.3c.7.9 1.3 1.6 1.5 2.7"></path><path d="M9 18h6"></path><path d="M10 22h4"></path>',
        message: '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 1 1 17 0Z"></path>',
        moon: '<path d="M12 3a6.4 6.4 0 0 0 9 9 9 9 0 1 1-9-9Z"></path>',
        music: '<path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle>',
        palette: '<circle cx="13.5" cy="6.5" r=".5"></circle><circle cx="17.5" cy="10.5" r=".5"></circle><circle cx="8.5" cy="7.5" r=".5"></circle><circle cx="6.5" cy="12.5" r=".5"></circle><path d="M12 22a10 10 0 1 1 10-10c0 3-2 4-4 4h-1.5a2.5 2.5 0 0 0 0 5H12Z"></path>',
        play: '<path d="m8 5 11 7-11 7Z"></path>',
        plus: '<path d="M12 5v14"></path><path d="M5 12h14"></path>',
        refresh: '<path d="M21 12a9 9 0 0 1-15.4 6.4L3 16"></path><path d="M3 21v-5h5"></path><path d="M3 12A9 9 0 0 1 18.4 5.6L21 8"></path><path d="M21 3v5h-5"></path>',
        rotate: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"></path><path d="M3 3v5h5"></path>',
        save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"></path><path d="M17 21v-8H7v8"></path><path d="M7 3v5h8"></path>',
        scissors: '<circle cx="6" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><path d="M20 4 8.1 15.9"></path><path d="M14.5 14.5 20 20"></path><path d="M8.1 8.1 12 12"></path>',
        search: '<circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path>',
        sparkles: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z"></path><path d="M5 3v4"></path><path d="M3 5h4"></path><path d="M19 17v4"></path><path d="M17 19h4"></path>',
        sun: '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2"></path><path d="M12 20v2"></path><path d="m4.9 4.9 1.4 1.4"></path><path d="m17.7 17.7 1.4 1.4"></path><path d="M2 12h2"></path><path d="M20 12h2"></path><path d="m6.3 17.7-1.4 1.4"></path><path d="m19.1 4.9-1.4 1.4"></path>',
        trash: '<path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="m19 6-1 14H6L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path>',
        upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="M17 8 12 3 7 8"></path><path d="M12 3v12"></path>',
        volume: '<path d="M11 5 6 9H2v6h4l5 4Z"></path><path d="M15.5 8.5a5 5 0 0 1 0 7"></path><path d="M19 5a10 10 0 0 1 0 14"></path>',
        wand: '<path d="M15 4V2"></path><path d="M15 16v-2"></path><path d="M8 9H6"></path><path d="M20 9h-2"></path><path d="m17.8 6.2 1.4-1.4"></path><path d="m10.8 13.2-1.4 1.4"></path><path d="m10.8 4.8-1.4-1.4"></path><path d="m17.8 11.8 1.4 1.4"></path><path d="m3 21 9-9"></path>',
        x: '<circle cx="12" cy="12" r="10"></circle><path d="m15 9-6 6"></path><path d="m9 9 6 6"></path>',
        zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9Z"></path>'
    };
    function vcIcon(name, size = 18) {
        const paths = vcIconPaths[name] || '';
        return '<svg data-vc-icon="' + name + '" class="vc-icon" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
    }
    // Exposto globalmente: o JS do status amigável (logs_output.change) roda em
    // outro escopo e precisa enxergar vcIcon — sem isso o status nunca aparece.
    window.vcIcon = vcIcon;
    function vcTickProcessingStatus() {
        document.querySelectorAll('.vc-processing-status[data-rotating="1"]').forEach((card) => {
            const msgEl = card.querySelector('.vc-processing-message');
            if (!msgEl) return;
            let messages = [];
            try { messages = JSON.parse(card.dataset.messages || '[]'); } catch (e) {}
            if (!messages || messages.length < 2) return;
            const now = Date.now();
            const last = Number(card.dataset.lastRotation || '0');
            if (now - last < 2600) return;
            const nextIndex = (Number(card.dataset.messageIndex || '0') + 1) % messages.length;
            card.dataset.lastRotation = String(now);
            card.dataset.messageIndex = String(nextIndex);
            msgEl.style.opacity = '0';
            window.setTimeout(() => {
                msgEl.textContent = messages[nextIndex];
                msgEl.style.opacity = '1';
            }, 140);
        });
    }
    window.setInterval(vcTickProcessingStatus, 700);
    function vcApplyTheme(theme) {
        const next = theme === 'dark' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-vc-theme', next);
        try { localStorage.setItem('vc-theme', next); } catch (e) {}
        document.querySelectorAll('[data-vc-theme-toggle]').forEach((btn) => {
            btn.innerHTML = vcIcon(next === 'dark' ? 'sun' : 'moon', 20);
            btn.title = next === 'dark' ? 'Usar modo claro' : 'Usar modo escuro';
            btn.setAttribute('aria-label', btn.title);
        });
    }
    try {
        const params = new URLSearchParams(window.location.search || '');
        const requestedTheme = params.get('__theme') === 'dark' ? 'dark' : params.get('__theme') === 'light' ? 'light' : null;
        vcApplyTheme(requestedTheme || localStorage.getItem('vc-theme') || 'dark');
    } catch (e) {
        vcApplyTheme('light');
    }
    document.body.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-vc-theme-toggle]');
        if (!btn) return;
        const current = document.documentElement.getAttribute('data-vc-theme') || 'light';
        vcApplyTheme(current === 'dark' ? 'light' : 'dark');
    }, true);
    const vcDecorations = new Map([
        ['Criar Cortes', 'film'],
        ['Identidade da Igreja', 'palette'],
        ["Logo / Marca d'água", 'droplet'],
        ['Trilha sonora', 'music'],
        ['Volume do vídeo', 'volume'],
        ['Encerramento', 'film'],
        ['Ajustar Legendas', 'edit'],
        ['Meus Vídeos', 'folder'],
        ['Sobre / Ajuda', 'lightbulb'],
        ['Upar vídeo', 'upload'],
        ['Link do YouTube', 'play'],
        ['Projeto já criado', 'folder'],
        ['Opções avançadas (não precisa mexer)', 'key'],
        ['Salvar JSON e Pular Fase 1 (Retoma edição)', 'save'],
        ['Render Animated Preview (Slow)', 'film'],
        ['Renderizar Prévia Animada (Lento)', 'film'],
        ['Gerar meus cortes', 'sparkles'],
        ['Restaurar configurações padrão', 'rotate'],
        ["Salvar Marca d'água", 'save'],
        ['Atualizar Preview Manualmente', 'refresh'],
        ['Salvar Configurações de Áudio', 'save'],
        ['Salvar Volume Original', 'save'],
        ['Salvar Configurações', 'save'],
        ['Save Changes', 'save'],
        ['Salvar Alterações', 'save'],
        ['Render This Segment (Very-Fast)', 'zap'],
        ['Renderizar Este Segmento (Muito Rápido)', 'zap'],
        ['Render All (Fast)', 'film'],
        ['Renderizar Tudo (Rápido)', 'film'],
        ['Sim, limpar agora', 'trash'],
        ['Analisar', 'search'],
        ['Apagar tudo', 'trash'],
        ['Refresh', 'refresh'],
        ['Refresh List', 'refresh'],
        ['Load Subtitles', 'edit']
    ]);
    function vcDecorateTextIcons() {
        document.querySelectorAll('button, .tab-nav button').forEach((el) => {
            if (el.dataset && el.dataset.vcDecorated === '1') return;
            if (el.querySelector && el.querySelector('svg[data-vc-icon]')) return;
            const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
            const name = vcDecorations.get(text);
            if (!name) return;
            el.innerHTML = vcIcon(name, 17) + '<span>' + text + '</span>';
            el.classList.add('vc-decorated-icon');
            if (el.dataset) el.dataset.vcDecorated = '1';
        });
    }
    setTimeout(vcDecorateTextIcons, 50);
    setTimeout(vcDecorateTextIcons, 500);
    setTimeout(vcDecorateTextIcons, 1500);
    setTimeout(vcDecorateTextIcons, 3000);
    const VC_BUFFER_BASE_SECONDS = 5;
    const VC_BUFFER_LIMIT_SECONDS = 600;
    function vcBufferValue(value) {
        const parsed = parseInt(value, 10);
        if (!Number.isFinite(parsed)) return 0;
        return Math.max(-VC_BUFFER_LIMIT_SECONDS, Math.min(VC_BUFFER_LIMIT_SECONDS, parsed));
    }
    window.vcUpdateBufferSaldo = function(input) {
        if (!input) return;
        const value = vcBufferValue(input.value);
        const row = input.parentElement;
        if (!row) return;
        const target = input.classList.contains('buffer-start-input') ? '.saldo-start' : '.saldo-end';
        const saldo = row.querySelector(target);
        if (saldo) saldo.textContent = '(saldo: ' + (VC_BUFFER_BASE_SECONDS - value) + 's)';
    };
    window.vcClampBufferInput = function(input) {
        if (!input) return;
        const raw = String(input.value || '').trim();
        if (raw === '' || raw === '-') return;
        input.value = vcBufferValue(input.value);
        window.vcUpdateBufferSaldo(input);
    };
    function vcCacheBust(src) {
        if (!src) return src;
        try {
            const u = new URL(src, window.location.href);
            u.searchParams.set('t', String(Date.now()));
            if (u.origin === window.location.origin) return u.pathname + u.search + u.hash;
            return u.href;
        } catch (e) {
            const base = String(src).split('?')[0];
            return base + '?t=' + Date.now();
        }
    }
    // Helper: reload the <video> tag in a card so the new burned subtitle is visible.
    function vcReloadVideoInCard(cardEl, explicitSrc, downloadName) {
        if (!cardEl) return;
        const v = cardEl.querySelector('video');
        if (!v) return;
        const srcEl = v.querySelector('source');
        const srcFromSource = srcEl ? (srcEl.getAttribute('src') || srcEl.src || '') : '';
        const baseSrc = (explicitSrc || v.currentSrc || srcFromSource || v.getAttribute('src') || '').split('?')[0];
        if (!baseSrc) return;
        const nextSrc = vcCacheBust(baseSrc);
        if (srcEl) {
            srcEl.src = nextSrc;
            srcEl.setAttribute('src', nextSrc);
            v.removeAttribute('src');
        } else {
            v.src = nextSrc;
        }
        const download = cardEl.querySelector('a[download]');
        if (download) {
            download.href = nextSrc;
            if (downloadName) download.setAttribute('download', downloadName);
        }
        v.load();
    }

    // Polish one segment's subtitles with AI (per-card button)
    document.body.addEventListener("click", async (e) => {
        let btn = e.target.closest('.polish-subs-btn');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        if (btn._vcL) return;
        const project = btn.getAttribute('data-project') || '';
        const segment = btn.getAttribute('data-segment') || '';
        if (!project || segment === '') return;
        btn._vcL = true;
        const oh = btn.innerHTML;
        const oc = btn.style.color;
        btn.innerHTML = '<div class="vc-spin"></div>';
        btn.style.pointerEvents = 'none';
        try {
            const r = await fetch('/polish_segment_api?project=' + project + '&segment=' + encodeURIComponent(segment));
            const d = await r.json();
            if (d.success) {
                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>';
                btn.classList.add('vc-ok');
                // Find the card container and reload its video
                let card = btn.closest('.viral-card') || btn.parentElement;
                while (card && !card.querySelector('video')) card = card.parentElement;
                vcReloadVideoInCard(card, d.video_url, d.download_name);
                setTimeout(() => { btn.innerHTML = oh; btn.style.color = oc; btn.style.pointerEvents = ''; btn.classList.remove('vc-ok'); btn._vcL = false; }, 2500);
            } else {
                console.warn('Polish failed:', d.error);
                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
                btn.classList.add('vc-err');
                btn.title = 'Erro: ' + (d.error || 'falhou');
                setTimeout(() => { btn.innerHTML = oh; btn.style.color = oc; btn.style.pointerEvents = ''; btn.classList.remove('vc-err'); btn._vcL = false; }, 4000);
            }
        } catch (err) {
            console.warn('Polish error:', err);
            btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
            btn.classList.add('vc-err');
            setTimeout(() => { btn.innerHTML = oh; btn.style.color = oc; btn.style.pointerEvents = ''; btn.classList.remove('vc-err'); btn._vcL = false; }, 4000);
        }
    }, true);

    // Polish ALL segments' subtitles with AI (toolbar button above gallery)
    document.body.addEventListener("click", async (e) => {
        const btn = e.target.closest('.polish-all-subs-btn');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        if (btn._vcL) return;
        const project = btn.getAttribute('data-project') || '';
        if (!project) return;
        if (!confirm('Corrigir as legendas de TODOS os segmentos? Isso pode levar alguns minutos.')) return;
        btn._vcL = true;
        const oh = btn.innerHTML;
        btn.innerHTML = '<div class="vc-spin" style="border-top-color:#fff"></div><span>Corrigindo...</span>';
        btn.style.pointerEvents = 'none';
        btn.style.opacity = '0.85';
        try {
            const r = await fetch('/polish_all_segments_api?project=' + project);
            const d = await r.json();
            if (d.success) {
                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg><span>' + (d.polished || 0) + '/' + (d.total || 0) + ' corrigidas</span>';
                // Reload every video that was rendered with its exact new URL.
                const rendered = new Map();
                (d.results || []).forEach((item) => {
                    if (item && item.success && item.segment !== undefined) rendered.set(String(item.segment), item);
                });
                document.querySelectorAll('.viral-card').forEach((c, idx) => {
                    const key = c.getAttribute('data-segment') || String(idx);
                    const item = rendered.get(key);
                    vcReloadVideoInCard(c, item && item.video_url, item && item.download_name);
                });
                setTimeout(() => { btn.innerHTML = oh; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; }, 4000);
            } else {
                console.warn('Polish all failed:', d.error);
                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg><span>Falhou</span>';
                btn.title = 'Erro: ' + (d.error || 'falhou');
                setTimeout(() => { btn.innerHTML = oh; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; }, 5000);
            }
        } catch (err) {
            console.warn('Polish all error:', err);
            btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line></svg><span>Erro</span>';
            setTimeout(() => { btn.innerHTML = oh; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; }, 5000);
        }
    }, true);
    // Reprocess buffer/margin for a segment (independent start/end controls)
    document.body.addEventListener("click", async (e) => {
        const btn = e.target.closest('.reprocess-buffer-btn');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        if (btn._vcL) return;
        const project = btn.getAttribute('data-project') || '';
        const segment = btn.getAttribute('data-segment') || '';
        const startId = btn.getAttribute('data-start-id') || '';
        const endId = btn.getAttribute('data-end-id') || '';
        if (!project || segment === '') return;

        const startInput = document.getElementById(startId);
        const endInput = document.getElementById(endId);
        if (!startInput || !endInput) return;

        const bufStart = vcBufferValue(startInput.value);
        const bufEnd = vcBufferValue(endInput.value);

        btn._vcL = true;
        const oh = btn.innerHTML;
        btn.innerHTML = '<div class="vc-spin" style="width:16px;height:16px;border-width:2px"></div> Reprocessando...';
        btn.style.pointerEvents = 'none';
        btn.style.opacity = '0.85';
        startInput.disabled = true;
        endInput.disabled = true;
        try {
            const r = await fetch('/adjust_buffer_api?project=' + project + '&segment=' + encodeURIComponent(segment) + '&buffer_start=' + encodeURIComponent(bufStart) + '&buffer_end=' + encodeURIComponent(bufEnd));
            const d = await r.json();
            if (d.success) {
                btn.innerHTML = vcIcon('check', 16) + '<span>Pronto!</span>';
                btn.classList.add('vc-ok');
                if (d.buffer_start_used !== undefined) startInput.value = d.buffer_start_used;
                if (d.buffer_end_used !== undefined) endInput.value = d.buffer_end_used;
                window.vcUpdateBufferSaldo(startInput);
                window.vcUpdateBufferSaldo(endInput);
                // Reload video
                let card = btn.closest('.viral-card') || btn.parentElement;
                while (card && !card.querySelector('video')) card = card.parentElement;
                vcReloadVideoInCard(card, d.video_url, d.download_name);
                setTimeout(() => { btn.innerHTML = oh; btn.classList.remove('vc-ok'); btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; startInput.disabled = false; endInput.disabled = false; }, 2500);
            } else {
                console.warn('Buffer reprocess failed:', d.error);
                btn.innerHTML = vcIcon('x', 16) + '<span>Falhou</span>';
                btn.classList.add('vc-err');
                btn.title = 'Erro: ' + (d.error || 'falhou');
                setTimeout(() => { btn.innerHTML = oh; btn.classList.remove('vc-err'); btn.title = ''; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; startInput.disabled = false; endInput.disabled = false; }, 3500);
            }
        } catch (err) {
            console.warn('Buffer reprocess error:', err);
            btn.innerHTML = vcIcon('x', 16) + '<span>Erro</span>';
            btn.classList.add('vc-err');
            setTimeout(() => { btn.innerHTML = oh; btn.classList.remove('vc-err'); btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; startInput.disabled = false; endInput.disabled = false; }, 3500);
        }
    }, true);

    function vcEscapeHtml(text) {
        return String(text || '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[ch]));
    }

    function vcSetFeatureButtonState(btn, applied) {
        if (!btn) return;
        const label = btn.getAttribute('data-label') || 'Recurso';
        const safeLabel = vcEscapeHtml(label);
        const accent = btn.getAttribute('data-accent') || '#3b82f6';
        btn.disabled = false;
        btn.style.display = 'inline-flex';
        btn.style.alignItems = 'center';
        btn.style.gap = '5px';
        btn.style.padding = '5px 9px';
        btn.style.fontSize = '11.5px';
        btn.style.fontWeight = '600';
        btn.style.fontFamily = 'sans-serif';
        btn.style.opacity = '1';
        btn.style.pointerEvents = '';
        btn.style.filter = 'none';
        btn.style.transition = 'background .2s,color .2s,border-color .2s,filter .2s';
        if (applied) {
            btn.classList.add('applied');
            btn.style.background = '#E2E8F0';
            btn.style.color = '#94A3B8';
            btn.style.border = '1px solid #CBD5E1';
            btn.style.borderRadius = '8px';
            btn.style.cursor = 'pointer';
            btn.title = btn.getAttribute('data-remove-title') || ('Remover ' + label + ' deste corte');
            btn.innerHTML = '<span class="vc-feature-icon-current">' + vcIcon('check', 14) + '</span><span class="vc-feature-icon-remove">' + vcIcon('x', 14) + '</span><span class="vc-feature-label">' + safeLabel + '</span>';
        } else {
            btn.classList.remove('applied');
            btn.style.background = accent;
            btn.style.color = '#fff';
            btn.style.border = 'none';
            btn.style.borderRadius = '7px';
            btn.style.cursor = 'pointer';
            btn.title = btn.getAttribute('data-apply-title') || ('Aplicar ' + label);
            btn.innerHTML = vcIcon('plus', 14) + '<span class="vc-feature-label">' + safeLabel + '</span>';
        }
    }

    function vcSyncFeatureButtons(card, features) {
        if (!card || !features) return;
        card.querySelectorAll('.apply-feature-btn[data-feature]').forEach((featureBtn) => {
            const key = featureBtn.getAttribute('data-feature') || '';
            vcSetFeatureButtonState(featureBtn, !!features[key]);
        });
    }

    const vcSegmentEditor = {
        project: '',
        segment: null,
        card: null,
        data: null,
        activeTab: 'subtitle',
        saveTimer: null,
        previewTimer: null,
        previewRequestId: 0,
        saving: false
    };

    function vcEnsureSegmentEditor() {
        if (!document.getElementById('vc-segment-editor-style')) {
            const css = document.createElement('style');
            css.id = 'vc-segment-editor-style';
            css.textContent = `
                .vc-segment-editor-overlay{position:fixed;inset:0;background:rgba(15,23,42,.72);z-index:9999;display:flex;align-items:center;justify-content:center;padding:18px}
                .vc-segment-editor-modal{width:min(1180px,96vw);height:min(860px,94vh);background:var(--vc-surface);color:var(--vc-text);border:1px solid var(--vc-border-strong);border-radius:12px;box-shadow:0 24px 80px rgba(0,0,0,.35);display:grid;grid-template-rows:auto 1fr auto;overflow:hidden}
                .vc-segment-editor-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid var(--vc-border);background:var(--vc-surface-soft)}
                .vc-segment-editor-title{font-weight:800;font-size:15px;line-height:1.25}
                .vc-segment-editor-close{border:0;background:transparent;color:var(--vc-text-muted);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;padding:6px;border-radius:8px}
                .vc-segment-editor-body{display:grid;grid-template-columns:minmax(420px,500px) 1fr;min-height:0}
                .vc-segment-editor-preview{padding:14px;border-right:1px solid var(--vc-border);background:#0f172a;min-height:0;display:flex;align-items:stretch}
                .vc-segment-editor-preview-grid{width:100%;display:grid;grid-template-columns:1fr 1fr;gap:12px;min-height:0}
                .vc-preview-pane{min-width:0;display:grid;grid-template-rows:auto 1fr;gap:8px;color:#cbd5e1}
                .vc-preview-pane-title{font-size:12px;font-weight:800;color:#e2e8f0;display:flex;align-items:center;gap:6px}
                .vc-preview-frame{min-height:0;border:1px solid rgba(148,163,184,.22);border-radius:10px;background:#020617;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative}
                .vc-preview-frame video,.vc-preview-frame img{width:100%;height:100%;object-fit:contain;background:#000}
                .vc-segment-editor-preview-placeholder,.vc-segment-editor-live-placeholder{padding:14px;text-align:center;color:#94a3b8;font-size:12px;line-height:1.45}
                .vc-segment-editor-preview-status{font-size:11px;color:#94a3b8}
                .vc-segment-editor-side{display:grid;grid-template-columns:170px 1fr;min-width:0;min-height:0}
                .vc-segment-editor-tabs{border-right:1px solid var(--vc-border);background:var(--vc-surface-soft);padding:10px;display:flex;flex-direction:column;gap:6px}
                .vc-segment-editor-tab{border:1px solid transparent;background:transparent;color:var(--vc-text);border-radius:8px;padding:9px 10px;text-align:left;cursor:pointer;font-weight:700;display:flex;align-items:center;gap:8px}
                .vc-segment-editor-tab.active{background:var(--vc-primary-soft);border-color:var(--vc-border-strong);color:var(--vc-primary-deep)}
                .vc-segment-editor-panels{overflow:auto;padding:14px}
                .vc-segment-editor-panel{display:none}
                .vc-segment-editor-panel.active{display:block}
                .vc-editor-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
                .vc-editor-field{display:flex;flex-direction:column;gap:5px;font-size:12px;color:var(--vc-text-soft)}
                .vc-editor-field input,.vc-editor-field select{width:100%;box-sizing:border-box;border:1px solid var(--vc-border-strong);border-radius:7px;background:var(--vc-surface);color:var(--vc-text);padding:8px;font-size:13px}
                .vc-editor-field input[type="checkbox"]{width:auto}
                .vc-editor-check{flex-direction:row;align-items:center;color:var(--vc-text);font-weight:600}
                .vc-editor-section-title{font-size:13px;font-weight:800;margin:14px 0 8px;color:var(--vc-primary-deep)}
                .vc-segment-editor-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px;border-top:1px solid var(--vc-border);background:var(--vc-surface-soft)}
                .vc-segment-editor-status{font-size:12px;color:var(--vc-text-muted)}
                .vc-segment-editor-render{border:0;border-radius:9px;background:var(--vc-grad);color:#fff;font-weight:800;padding:9px 14px;cursor:pointer;display:inline-flex;align-items:center;gap:8px}
                @media(max-width:980px){.vc-segment-editor-body{grid-template-columns:1fr}.vc-segment-editor-preview{height:360px;border-right:0;border-bottom:1px solid var(--vc-border)}.vc-segment-editor-side{grid-template-columns:1fr}.vc-segment-editor-tabs{flex-direction:row;overflow:auto;border-right:0;border-bottom:1px solid var(--vc-border)}.vc-editor-grid{grid-template-columns:1fr}}
                @media(max-width:560px){.vc-segment-editor-preview{height:520px}.vc-segment-editor-preview-grid{grid-template-columns:1fr}}
            `;
            document.head.appendChild(css);
        }
        let overlay = document.getElementById('vc-segment-editor-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'vc-segment-editor-overlay';
            overlay.className = 'vc-segment-editor-overlay';
            overlay.style.display = 'none';
            document.body.appendChild(overlay);
        }
        return overlay;
    }

    function vcDeepGet(obj, path, fallback) {
        const parts = String(path || '').split('.');
        let cur = obj;
        for (const part of parts) {
            if (!cur || typeof cur !== 'object' || !(part in cur)) return fallback;
            cur = cur[part];
        }
        return cur === undefined || cur === null ? fallback : cur;
    }

    function vcDeepSet(obj, path, value) {
        const parts = String(path || '').split('.');
        let cur = obj;
        for (let i = 0; i < parts.length - 1; i++) {
            const part = parts[i];
            if (!cur[part] || typeof cur[part] !== 'object') cur[part] = {};
            cur = cur[part];
        }
        cur[parts[parts.length - 1]] = value;
    }

    function vcAssToHex(value, fallback = '#FFFFFF') {
        const text = String(value || '').trim();
        const m = text.match(/&H[0-9A-Fa-f]{2}([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})&?/);
        if (m) return '#' + m[3] + m[2] + m[1];
        if (/^#[0-9A-Fa-f]{6}$/.test(text)) return text;
        return fallback;
    }

    function vcHexToAss(value) {
        const clean = String(value || '#FFFFFF').replace('#', '').trim();
        if (!/^[0-9A-Fa-f]{6}$/.test(clean)) return '&H00FFFFFF&';
        return ('&H00' + clean.slice(4, 6) + clean.slice(2, 4) + clean.slice(0, 2) + '&').toUpperCase();
    }

    function vcEditorInput(config, path, label, type, fallback, attrs = '') {
        const cfg = (((vcSegmentEditor.data || {}).state || {}).configs || {})[config] || {};
        const raw = vcDeepGet(cfg, path, fallback);
        const value = type === 'color' ? vcAssToHex(raw, fallback) : raw;
        const ass = type === 'color' ? ' data-ass="1"' : '';
        return `<label class="vc-editor-field"><span>${label}</span><input class="vc-editor-input" data-config="${config}" data-path="${path}" type="${type}" value="${vcEscapeHtml(value)}"${ass} ${attrs}></label>`;
    }

    function vcEditorCheck(config, path, label, intBool = false) {
        const cfg = (((vcSegmentEditor.data || {}).state || {}).configs || {})[config] || {};
        const checked = !!vcDeepGet(cfg, path, false);
        return `<label class="vc-editor-field vc-editor-check"><input class="vc-editor-input" data-config="${config}" data-path="${path}" type="checkbox" ${intBool ? 'data-int-bool="1"' : ''} ${checked ? 'checked' : ''}><span>${label}</span></label>`;
    }

    function vcEditorSelect(config, path, label, options, fallback) {
        const cfg = (((vcSegmentEditor.data || {}).state || {}).configs || {})[config] || {};
        const cur = String(vcDeepGet(cfg, path, fallback));
        const opts = options.map(([value, text]) => `<option value="${vcEscapeHtml(value)}" ${cur === String(value) ? 'selected' : ''}>${text}</option>`).join('');
        return `<label class="vc-editor-field"><span>${label}</span><select class="vc-editor-input" data-config="${config}" data-path="${path}">${opts}</select></label>`;
    }

    function vcEditorFile(config, field, label, accept) {
        return `<label class="vc-editor-field"><span>${label}</span><input class="vc-editor-file" data-config="${config}" data-field="${field}" type="file" accept="${accept || ''}"></label>`;
    }

    // Aplicar um recurso desativável (marca d'água/outro/áudio/música) a UM corte.
    function vcRenderSegmentEditor(data) {
        vcSegmentEditor.data = data;
        const overlay = vcEnsureSegmentEditor();
        const state = data.state || {};
        const configs = state.configs || {};
        const title = vcEscapeHtml(data.title || ('Segmento ' + ((data.segment || 0) + 1)));
        const videoSrc = data.video_url ? vcCacheBust(data.video_url) : '';
        const bufStart = vcBufferValue((data || {}).buffer_start_used || 0);
        const bufEnd = vcBufferValue((data || {}).buffer_end_used || 0);
        overlay.innerHTML = `
            <div class="vc-segment-editor-modal" role="dialog" aria-modal="true">
                <div class="vc-segment-editor-head">
                    <div class="vc-segment-editor-title">${vcIcon('edit', 18)} Editando: ${title}</div>
                    <button type="button" class="vc-segment-editor-close" title="Fechar">${vcIcon('x', 22)}</button>
                </div>
                <div class="vc-segment-editor-body">
                    <div class="vc-segment-editor-preview">
                        <div class="vc-segment-editor-preview-grid">
                            <div class="vc-preview-pane">
                                <div class="vc-preview-pane-title">${vcIcon('play', 14)}Video atual</div>
                                <div class="vc-preview-frame">
                                    ${videoSrc ? `<video controls playsinline preload="metadata"><source src="${videoSrc}" type="video/mp4"></video>` : `<div class="vc-segment-editor-preview-placeholder">Video nao encontrado</div>`}
                                </div>
                            </div>
                            <div class="vc-preview-pane">
                                <div class="vc-preview-pane-title">${vcIcon('palette', 14)}Previa rapida</div>
                                <div class="vc-preview-frame">
                                    <img class="vc-segment-editor-preview-img" alt="Previa rapida" style="display:none">
                                    <div class="vc-segment-editor-live-placeholder">Gerando preview...</div>
                                </div>
                                <div class="vc-segment-editor-preview-status">Legendas, marca d'agua e outro usam uma imagem rapida.</div>
                            </div>
                        </div>
                    </div>
                    <div class="vc-segment-editor-side">
                        <div class="vc-segment-editor-tabs">
                            <button type="button" class="vc-segment-editor-tab active" data-editor-tab="subtitle">${vcIcon('message', 16)}Legendas</button>
                            <button type="button" class="vc-segment-editor-tab" data-editor-tab="watermark">${vcIcon('droplet', 16)}Marca</button>
                            <button type="button" class="vc-segment-editor-tab" data-editor-tab="audio">${vcIcon('music', 16)}Audio</button>
                            <button type="button" class="vc-segment-editor-tab" data-editor-tab="outro">${vcIcon('film', 16)}Outro</button>
                            <button type="button" class="vc-segment-editor-tab" data-editor-tab="margin">${vcIcon('scissors', 16)}Margem</button>
                        </div>
                        <div class="vc-segment-editor-panels">
                            <section class="vc-segment-editor-panel active" data-editor-panel="subtitle">
                                <div class="vc-editor-grid">
                                    ${vcEditorInput('subtitle','font','Fonte','text','Montserrat')}
                                    ${vcEditorInput('subtitle','base_size','Tamanho base','number',30,'min="8" max="120" step="1"')}
                                    ${vcEditorInput('subtitle','base_color','Cor base','color','#FFFFFF')}
                                    ${vcEditorInput('subtitle','highlight_color','Cor destaque','color','#FFFFFF')}
                                    ${vcEditorInput('subtitle','highlight_size','Tamanho destaque','number',30,'min="8" max="120" step="1"')}
                                    ${vcEditorSelect('subtitle','mode','Modo',[['highlight','Destaque'],['word_by_word','Palavra por palavra'],['no_highlight','Sem destaque']],'no_highlight')}
                                    ${vcEditorInput('subtitle','words_per_block','Palavras por bloco','number',4,'min="1" max="30" step="1"')}
                                    ${vcEditorInput('subtitle','gap_limit','Limite de pausa','number',0.6,'min="0" max="10" step="0.1"')}
                                    ${vcEditorInput('subtitle','vertical_position','Posicao vertical','number',115,'min="0" max="700" step="1"')}
                                    ${vcEditorInput('subtitle','margin_h','Margem horizontal','number',35,'min="0" max="500" step="1"')}
                                    ${vcEditorSelect('subtitle','alignment','Alinhamento',[['1','Esquerda'],['2','Centro'],['3','Direita']],'2')}
                                    ${vcEditorInput('subtitle','outline_color','Cor contorno','color','#000000')}
                                    ${vcEditorInput('subtitle','outline_thickness','Espessura contorno','number',1,'min="0" max="20" step="1"')}
                                    ${vcEditorInput('subtitle','shadow_color','Cor sombra','color','#000000')}
                                    ${vcEditorInput('subtitle','shadow_size','Tamanho sombra','number',1,'min="0" max="20" step="1"')}
                                    ${vcEditorSelect('subtitle','border_style','Borda',[['1','Contorno'],['3','Caixa opaca']],'1')}
                                    ${vcEditorCheck('subtitle','bold','Negrito', true)}
                                    ${vcEditorCheck('subtitle','italic','Italico', true)}
                                    ${vcEditorCheck('subtitle','uppercase','Maiusculas', true)}
                                    ${vcEditorCheck('subtitle','underline','Sublinhado', true)}
                                    ${vcEditorCheck('subtitle','strikeout','Tachado', true)}
                                    ${vcEditorCheck('subtitle','remove_punctuation','Remover pontuacao')}
                                </div>
                            </section>
                            <section class="vc-segment-editor-panel" data-editor-panel="watermark">
                                <div class="vc-editor-grid">
                                    ${vcEditorCheck('watermark','enabled','Ativar marca d agua')}
                                    ${vcEditorFile('watermark','watermark_image_path','Enviar imagem','image/*')}
                                    ${vcEditorInput('watermark','watermark_image_path','Caminho da imagem','text',vcDeepGet(configs.watermark || {}, 'watermark_image_path', ''))}
                                    ${vcEditorInput('watermark','position_x','Posicao X','number',480,'min="-1080" max="1080" step="1"')}
                                    ${vcEditorInput('watermark','position_y','Posicao Y','number',0,'min="-1920" max="1920" step="1"')}
                                    ${vcEditorInput('watermark','scale','Escala (%)','number',15,'min="1" max="500" step="1"')}
                                    ${vcEditorInput('watermark','opacity','Opacidade (%)','number',30,'min="0" max="100" step="1"')}
                                </div>
                            </section>
                            <section class="vc-segment-editor-panel" data-editor-panel="audio">
                                <div class="vc-editor-section-title">Trilha sonora</div>
                                <div class="vc-editor-grid">
                                    ${vcEditorCheck('audio','enabled','Ativar audio BGM')}
                                    ${vcEditorFile('audio','audio_file_path','Enviar audio BGM','audio/*')}
                                    ${vcEditorInput('audio','audio_file_path','Caminho do audio','text',vcDeepGet(configs.audio || {}, 'audio_file_path', ''))}
                                    ${vcEditorInput('audio','base_volume','Volume BGM (%)','number',12,'min="0" max="100" step="1"')}
                                    ${vcEditorInput('audio','source_video_volume','Volume original (%)','number',100,'min="0" max="200" step="1"')}
                                    ${vcEditorCheck('audio','loop_to_end','Repetir ate o fim')}
                                    ${vcEditorInput('audio','fade_in_duration','Fade-in (s)','number',0.5,'min="0" max="60" step="0.1"')}
                                    ${vcEditorInput('audio','fade_out_duration','Fade-out (s)','number',0.5,'min="0" max="60" step="0.1"')}
                                    ${vcEditorCheck('audio','stop_before_outro','Parar BGM antes do outro')}
                                    ${vcEditorCheck('audio','use_ending_volume','Usar volume final')}
                                    ${vcEditorCheck('audio','sync_with_outro','Sincronizar com outro')}
                                    ${vcEditorInput('audio','ending_volume','Volume final (%)','number',20,'min="0" max="100" step="1"')}
                                    ${vcEditorInput('audio','ending_start_time','Comecar volume final (s)','number',10,'min="0" max="600" step="1"')}
                                    ${vcEditorInput('audio','crossfade_duration','Suavizacao (s)','number',3,'min="0" max="60" step="0.1"')}
                                </div>
                                <div class="vc-editor-section-title">Musica de encerramento</div>
                                <div class="vc-editor-grid">
                                    ${vcEditorCheck('audio','outro_music.enabled','Ativar musica do outro')}
                                    ${vcEditorFile('audio','outro_music.audio_file_path','Enviar musica do outro','audio/*')}
                                    ${vcEditorInput('audio','outro_music.audio_file_path','Caminho da musica','text',vcDeepGet(configs.audio || {}, 'outro_music.audio_file_path', ''))}
                                    ${vcEditorInput('audio','outro_music.volume','Volume musica (%)','number',50,'min="0" max="100" step="1"')}
                                    ${vcEditorSelect('audio','outro_music.start_from','Trecho usado',[['start','Inicio'],['end','Final']],'end')}
                                    ${vcEditorInput('audio','outro_music.fade_in_duration','Fade-in musica (s)','number',1,'min="0" max="60" step="0.1"')}
                                    ${vcEditorCheck('audio','outro_music.fade_out_enabled','Fade-out no fim')}
                                    ${vcEditorInput('audio','outro_music.fade_out_duration','Fade-out musica (s)','number',1,'min="0" max="60" step="0.1"')}
                                </div>
                            </section>
                            <section class="vc-segment-editor-panel" data-editor-panel="outro">
                                <div class="vc-editor-grid">
                                    ${vcEditorCheck('outro','enabled','Ativar outro / encerramento')}
                                    ${vcEditorFile('outro','outro_video_path','Enviar video de outro','video/*')}
                                    ${vcEditorInput('outro','outro_video_path','Caminho do video','text',vcDeepGet(configs.outro || {}, 'outro_video_path', ''))}
                                    ${vcEditorFile('outro','overlay_image_path','Enviar imagem overlay','image/*')}
                                    ${vcEditorInput('outro','overlay_image_path','Caminho da imagem','text',vcDeepGet(configs.outro || {}, 'overlay_image_path', ''))}
                                    ${vcEditorInput('outro','fade_duration','Duracao do fade (s)','number',1,'min="0" max="30" step="0.1"')}
                                    ${vcEditorInput('outro','outro_volume','Volume do outro (%)','number',40,'min="0" max="200" step="1"')}
                                    ${vcEditorInput('outro','position_x','Imagem X','number',179,'min="-1080" max="1080" step="1"')}
                                    ${vcEditorInput('outro','position_y','Imagem Y','number',886,'min="-1920" max="1920" step="1"')}
                                    ${vcEditorInput('outro','scale','Escala imagem (%)','number',42,'min="1" max="500" step="1"')}
                                    ${vcEditorInput('outro','rounded_corners','Bordas (%)','number',10,'min="0" max="50" step="1"')}
                                </div>
                            </section>
                            <section class="vc-segment-editor-panel" data-editor-panel="margin">
                                <div class="vc-editor-section-title">Margem de seguranca</div>
                                <p style="font-size:12px;color:var(--vc-text-muted);margin:0 0 14px;line-height:1.5;">Quantos segundos entram antes e depois do corte limpo da IA. Positivo amplia o trecho, negativo apara. Reprocessa este video a partir do material original e re-renderiza mantendo os ajustes das outras abas.</p>
                                <div class="vc-editor-grid">
                                    <label class="vc-editor-field">
                                        <span>Inicio (s) <span style="color:var(--vc-text-muted);font-weight:400;">+ antes / - apara</span></span>
                                        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                                            <input type="number" class="buffer-start-input" id="vc-editor-buf-start" min="-600" max="600" step="1" value="${bufStart}" style="width:90px;text-align:center;" title="+ amplia para antes, - corta o inicio" onchange="if(window.vcUpdateBufferSaldo)window.vcUpdateBufferSaldo(this)" oninput="if(window.vcClampBufferInput)window.vcClampBufferInput(this)">
                                            <span class="saldo-start" style="font-size:11px;color:var(--vc-text-muted);white-space:nowrap;">(saldo: ${5 - bufStart}s)</span>
                                        </div>
                                    </label>
                                    <label class="vc-editor-field">
                                        <span>Final (s) <span style="color:var(--vc-text-muted);font-weight:400;">+ depois / - apara</span></span>
                                        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                                            <input type="number" class="buffer-end-input" id="vc-editor-buf-end" min="-600" max="600" step="1" value="${bufEnd}" style="width:90px;text-align:center;" title="+ amplia depois, - corta o final" onchange="if(window.vcUpdateBufferSaldo)window.vcUpdateBufferSaldo(this)" oninput="if(window.vcClampBufferInput)window.vcClampBufferInput(this)">
                                            <span class="saldo-end" style="font-size:11px;color:var(--vc-text-muted);white-space:nowrap;">(saldo: ${5 - bufEnd}s)</span>
                                        </div>
                                    </label>
                                </div>
                                <button type="button" class="vc-editor-buffer-btn" style="margin-top:14px;padding:9px 14px;background:var(--vc-grad);color:#fff;font-weight:800;border:0;border-radius:9px;cursor:pointer;display:inline-flex;align-items:center;gap:8px;">${vcIcon('refresh', 16)}<span>Reprocessar margem</span></button>
                            </section>
                        </div>
                    </div>
                </div>
                <div class="vc-segment-editor-foot">
                    <div class="vc-segment-editor-status">Alteracoes sao salvas automaticamente para este video.</div>
                    <button type="button" class="vc-segment-editor-render">${vcIcon('zap', 17)}<span>Salvar e renderizar este video</span></button>
                </div>
            </div>
        `;
        overlay.style.display = 'flex';
        vcSegmentEditor.activeTab = 'subtitle';
        vcScheduleSegmentEditorPreview('subtitle');
    }

    function vcSegmentEditorStatus(text, isError = false) {
        const el = document.querySelector('#vc-segment-editor-overlay .vc-segment-editor-status');
        if (!el) return;
        el.textContent = text || '';
        el.style.color = isError ? 'var(--vc-error)' : 'var(--vc-text-muted)';
    }

    function vcPreviewKindForTab(tab) {
        return ['subtitle', 'watermark', 'outro'].includes(tab) ? tab : 'audio';
    }

    function vcSetSegmentEditorPreview(message, imageUrl, isError = false) {
        const root = document.getElementById('vc-segment-editor-overlay');
        if (!root) return;
        const img = root.querySelector('.vc-segment-editor-preview-img');
        const ph = root.querySelector('.vc-segment-editor-live-placeholder');
        const status = root.querySelector('.vc-segment-editor-preview-status');
        if (status) {
            status.textContent = message || '';
            status.style.color = isError ? 'var(--vc-error)' : '#94a3b8';
        }
        if (imageUrl && img) {
            img.src = vcCacheBust(imageUrl);
            img.style.display = 'block';
            if (ph) ph.style.display = 'none';
            return;
        }
        if (img) {
            img.removeAttribute('src');
            img.style.display = 'none';
        }
        if (ph) {
            ph.textContent = message || 'Preview indisponivel.';
            ph.style.display = 'block';
            ph.style.color = isError ? 'var(--vc-error)' : '#94a3b8';
        }
    }

    function vcSetSegmentEditorPreviewLoading(message) {
        const root = document.getElementById('vc-segment-editor-overlay');
        if (!root) return;
        const img = root.querySelector('.vc-segment-editor-preview-img');
        const ph = root.querySelector('.vc-segment-editor-live-placeholder');
        const status = root.querySelector('.vc-segment-editor-preview-status');
        if (status) {
            status.textContent = message || 'Gerando preview rapido...';
            status.style.color = '#94a3b8';
        }
        if (img && img.getAttribute('src')) {
            img.style.display = 'block';
            if (ph) ph.style.display = 'none';
        } else if (ph) {
            ph.textContent = message || 'Gerando preview rapido...';
            ph.style.display = 'block';
            ph.style.color = '#94a3b8';
        }
    }

    function vcScheduleSegmentEditorPreview(kind) {
        if (vcSegmentEditor.previewTimer) clearTimeout(vcSegmentEditor.previewTimer);
        const previewKind = vcPreviewKindForTab(kind || vcSegmentEditor.activeTab || 'subtitle');
        vcSegmentEditor.previewTimer = setTimeout(() => vcRefreshSegmentEditorPreview(previewKind), 450);
    }

    async function vcRefreshSegmentEditorPreview(kind) {
        if (!vcSegmentEditor.data) return;
        const previewKind = vcPreviewKindForTab(kind || vcSegmentEditor.activeTab || 'subtitle');
        if (previewKind === 'audio') {
            const msg = (vcSegmentEditor.activeTab === 'margin')
                ? 'A aba Margem reprocessa o corte a partir do material original. Use o botao "Reprocessar margem" para aplicar.'
                : 'A aba Audio ainda nao tem preview visual. Os ajustes continuam salvos por video.';
            vcSetSegmentEditorPreview(msg, null, false);
            return;
        }
        const requestId = ++vcSegmentEditor.previewRequestId;
        vcSetSegmentEditorPreviewLoading('Gerando preview rapido...');
        try {
            const body = {
                project: vcSegmentEditor.project,
                segment: vcSegmentEditor.segment,
                kind: previewKind,
                configs: (((vcSegmentEditor.data || {}).state || {}).configs || {})
            };
            const r = await fetch('/segment_editor_preview_api', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            const d = await r.json();
            if (requestId !== vcSegmentEditor.previewRequestId) return;
            if (!d.success) throw new Error(d.error || 'Falha ao gerar preview');
            vcSetSegmentEditorPreview(d.message || 'Preview atualizado.', d.preview_url, false);
        } catch (err) {
            if (requestId !== vcSegmentEditor.previewRequestId) return;
            vcSetSegmentEditorPreview('Erro no preview: ' + err.message, null, true);
        }
    }

    function vcReadEditorInput(input) {
        if (!input) return null;
        if (input.type === 'checkbox') {
            return input.dataset.intBool === '1' ? (input.checked ? 1 : 0) : input.checked;
        }
        if (input.dataset.ass === '1') return vcHexToAss(input.value);
        if (input.type === 'number' || input.type === 'range') {
            const n = Number(input.value);
            return Number.isFinite(n) ? n : 0;
        }
        return input.value || '';
    }

    function vcScheduleSegmentEditorSave() {
        if (vcSegmentEditor.saveTimer) clearTimeout(vcSegmentEditor.saveTimer);
        vcSegmentEditorStatus('Salvando alteracoes...');
        vcSegmentEditor.saveTimer = setTimeout(() => vcSaveSegmentEditorState(false), 650);
    }

    async function vcSaveSegmentEditorState(force) {
        if (!vcSegmentEditor.data || vcSegmentEditor.saving) return vcSegmentEditor.data;
        if (vcSegmentEditor.saveTimer) {
            clearTimeout(vcSegmentEditor.saveTimer);
            vcSegmentEditor.saveTimer = null;
        }
        vcSegmentEditor.saving = true;
        try {
            const body = {
                project: vcSegmentEditor.project,
                segment: vcSegmentEditor.segment,
                configs: (((vcSegmentEditor.data || {}).state || {}).configs || {})
            };
            const r = await fetch('/segment_editor_save_api', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            const d = await r.json();
            if (!d.success) throw new Error(d.error || 'Falha ao salvar');
            vcSegmentEditor.data = d;
            vcSegmentEditorStatus(force ? 'Alteracoes salvas.' : 'Salvo automaticamente.');
            return d;
        } catch (err) {
            vcSegmentEditorStatus('Erro ao salvar: ' + err.message, true);
            throw err;
        } finally {
            vcSegmentEditor.saving = false;
        }
    }

    async function vcOpenSegmentEditor(projectAttr, segment, card) {
        const project = decodeURIComponent(projectAttr || '');
        vcSegmentEditor.project = project;
        vcSegmentEditor.segment = Number(segment);
        vcSegmentEditor.card = card || null;
        const overlay = vcEnsureSegmentEditor();
        overlay.style.display = 'flex';
        overlay.innerHTML = '<div class="vc-segment-editor-modal" style="display:flex;align-items:center;justify-content:center;color:var(--vc-text);"><div class="vc-spin"></div><span style="margin-left:10px">Abrindo editor...</span></div>';
        try {
            const r = await fetch('/segment_editor_state_api?project=' + encodeURIComponent(project) + '&segment=' + encodeURIComponent(segment));
            const d = await r.json();
            if (!d.success) throw new Error(d.error || 'Falha ao abrir editor');
            vcRenderSegmentEditor(d);
        } catch (err) {
            overlay.innerHTML = '<div class="vc-segment-editor-modal" style="padding:24px;color:var(--vc-error);"><button type="button" class="vc-segment-editor-close" style="float:right">' + vcIcon('x', 22) + '</button>Erro ao abrir editor: ' + vcEscapeHtml(err.message) + '</div>';
        }
    }

    async function vcUploadSegmentEditorAsset(input) {
        if (!input || !input.files || !input.files[0] || !vcSegmentEditor.data) return;
        const config = input.getAttribute('data-config') || '';
        const field = input.getAttribute('data-field') || '';
        const fd = new FormData();
        fd.append('project', vcSegmentEditor.project);
        fd.append('segment', String(vcSegmentEditor.segment));
        fd.append('config_key', config);
        fd.append('field', field);
        fd.append('file', input.files[0]);
        vcSegmentEditorStatus('Enviando asset...');
        input.disabled = true;
        try {
            const r = await fetch('/segment_editor_upload_asset_api', { method: 'POST', body: fd });
            const d = await r.json();
            if (!d.success) throw new Error(d.error || 'Falha no upload');
            vcSegmentEditor.data = d;
            const cfg = (((vcSegmentEditor.data || {}).state || {}).configs || {})[config] || {};
            const value = vcDeepGet(cfg, field, d.path || '');
            document.querySelectorAll(`#vc-segment-editor-overlay .vc-editor-input[data-config="${config}"][data-path="${field}"]`).forEach((el) => { el.value = value || ''; });
            vcSegmentEditorStatus('Asset salvo para este video.');
            if (['watermark', 'outro'].includes(config)) vcScheduleSegmentEditorPreview(config);
        } catch (err) {
            vcSegmentEditorStatus('Erro no upload: ' + err.message, true);
        } finally {
            input.disabled = false;
            input.value = '';
        }
    }

    async function vcRenderSegmentEditorVideo(btn) {
        if (!vcSegmentEditor.data) return;
        const old = btn ? btn.innerHTML : '';
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<div class="vc-spin" style="width:16px;height:16px;border-width:2px;border-top-color:#fff"></div><span>Renderizando...</span>';
        }
        try {
            await vcSaveSegmentEditorState(true);
            vcSegmentEditorStatus('Renderizando este video...');
            const body = {
                project: vcSegmentEditor.project,
                segment: vcSegmentEditor.segment,
                configs: (((vcSegmentEditor.data || {}).state || {}).configs || {})
            };
            const r = await fetch('/segment_editor_render_api', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            const d = await r.json();
            if (!d.success) throw new Error(d.error || 'Falha ao renderizar');
            vcSegmentEditor.data = d;
            const root = document.getElementById('vc-segment-editor-overlay');
            vcReloadVideoInCard(root, d.video_url, d.download_name);
            let card = vcSegmentEditor.card;
            if (!card) card = document.querySelector('.viral-card[data-segment="' + vcSegmentEditor.segment + '"]');
            vcReloadVideoInCard(card, d.video_url, d.download_name);
            if (d.features) vcSyncFeatureButtons(card, d.features);
            vcSegmentEditorStatus('Renderizado e salvo como arquivo final.');
            vcScheduleSegmentEditorPreview(vcSegmentEditor.activeTab || 'subtitle');
        } catch (err) {
            vcSegmentEditorStatus('Erro ao renderizar: ' + err.message, true);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = old;
            }
        }
    }

    async function vcReprocessSegmentEditorMargin(btn) {
        if (!vcSegmentEditor.data) return;
        const root = document.getElementById('vc-segment-editor-overlay');
        const startInput = root ? root.querySelector('#vc-editor-buf-start') : null;
        const endInput = root ? root.querySelector('#vc-editor-buf-end') : null;
        if (!startInput || !endInput) return;
        const bufStart = vcBufferValue(startInput.value);
        const bufEnd = vcBufferValue(endInput.value);
        const old = btn ? btn.innerHTML : '';
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<div class="vc-spin" style="width:16px;height:16px;border-width:2px;border-top-color:#fff"></div><span>Reprocessando...</span>';
        }
        startInput.disabled = true;
        endInput.disabled = true;
        try {
            vcSegmentEditorStatus('Reprocessando margem deste video...');
            const body = {
                project: vcSegmentEditor.project,
                segment: vcSegmentEditor.segment,
                buffer_start: bufStart,
                buffer_end: bufEnd,
                configs: (((vcSegmentEditor.data || {}).state || {}).configs || {})
            };
            const r = await fetch('/segment_editor_buffer_api', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            const d = await r.json();
            if (!d.success) throw new Error(d.error || 'Falha ao reprocessar margem');
            vcSegmentEditor.data = d;
            if (d.buffer_start_used !== undefined) startInput.value = d.buffer_start_used;
            if (d.buffer_end_used !== undefined) endInput.value = d.buffer_end_used;
            window.vcUpdateBufferSaldo(startInput);
            window.vcUpdateBufferSaldo(endInput);
            vcReloadVideoInCard(root, d.video_url, d.download_name);
            let card = vcSegmentEditor.card;
            if (!card) card = document.querySelector('.viral-card[data-segment="' + vcSegmentEditor.segment + '"]');
            vcReloadVideoInCard(card, d.video_url, d.download_name);
            if (d.features) vcSyncFeatureButtons(card, d.features);
            vcSegmentEditorStatus('Margem aplicada e video renderizado.');
            vcScheduleSegmentEditorPreview(vcSegmentEditor.activeTab || 'subtitle');
        } catch (err) {
            vcSegmentEditorStatus('Erro ao reprocessar margem: ' + err.message, true);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = old;
            }
            startInput.disabled = false;
            endInput.disabled = false;
        }
    }

    document.body.addEventListener('click', (e) => {
        const openBtn = e.target.closest('.segment-editor-open-btn');
        if (openBtn) {
            e.preventDefault();
            e.stopPropagation();
            let card = openBtn.closest('.viral-card') || openBtn.parentElement;
            while (card && !card.querySelector('video')) card = card.parentElement;
            vcOpenSegmentEditor(openBtn.getAttribute('data-project') || '', openBtn.getAttribute('data-segment') || '0', card);
            return;
        }
        const closeBtn = e.target.closest('.vc-segment-editor-close');
        if (closeBtn || e.target.id === 'vc-segment-editor-overlay') {
            const overlay = document.getElementById('vc-segment-editor-overlay');
            if (overlay) overlay.style.display = 'none';
            return;
        }
        const tab = e.target.closest('.vc-segment-editor-tab');
        if (tab) {
            const key = tab.getAttribute('data-editor-tab');
            const root = document.getElementById('vc-segment-editor-overlay');
            if (!root) return;
            root.querySelectorAll('.vc-segment-editor-tab').forEach((el) => el.classList.toggle('active', el === tab));
            root.querySelectorAll('.vc-segment-editor-panel').forEach((el) => el.classList.toggle('active', el.getAttribute('data-editor-panel') === key));
            vcSegmentEditor.activeTab = key || 'subtitle';
            vcScheduleSegmentEditorPreview(vcSegmentEditor.activeTab);
            return;
        }
        const marginBtn = e.target.closest('.vc-editor-buffer-btn');
        if (marginBtn) {
            e.preventDefault();
            vcReprocessSegmentEditorMargin(marginBtn);
            return;
        }
        const renderBtn = e.target.closest('.vc-segment-editor-render');
        if (renderBtn) {
            e.preventDefault();
            vcRenderSegmentEditorVideo(renderBtn);
        }
    }, true);

    document.body.addEventListener('input', (e) => {
        const input = e.target.closest('.vc-editor-input');
        if (!input || !vcSegmentEditor.data) return;
        const config = input.getAttribute('data-config');
        const path = input.getAttribute('data-path');
        const configs = ((vcSegmentEditor.data.state || {}).configs || {});
        if (!configs[config]) configs[config] = {};
        vcDeepSet(configs[config], path, vcReadEditorInput(input));
        vcScheduleSegmentEditorSave();
        if (['subtitle', 'watermark', 'outro'].includes(config)) vcScheduleSegmentEditorPreview(config);
    }, true);

    document.body.addEventListener('change', (e) => {
        const fileInput = e.target.closest('.vc-editor-file');
        if (fileInput) {
            vcUploadSegmentEditorAsset(fileInput);
            return;
        }
        const input = e.target.closest('.vc-editor-input');
        if (!input || !vcSegmentEditor.data) return;
        const config = input.getAttribute('data-config');
        const path = input.getAttribute('data-path');
        const configs = ((vcSegmentEditor.data.state || {}).configs || {});
        if (!configs[config]) configs[config] = {};
        vcDeepSet(configs[config], path, vcReadEditorInput(input));
        vcScheduleSegmentEditorSave();
        if (['subtitle', 'watermark', 'outro'].includes(config)) vcScheduleSegmentEditorPreview(config);
    }, true);

    document.body.addEventListener("click", async (e) => {
        const btn = e.target.closest('.apply-feature-btn');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        if (btn._vcL) return;
        const feature = btn.getAttribute('data-feature') || '';
        const project = btn.getAttribute('data-project') || '';
        const segment = btn.getAttribute('data-segment') || '';
        const label = btn.getAttribute('data-label') || '';
        const isRemoval = btn.classList.contains('applied');
        const action = isRemoval ? 'remove' : 'apply';
        if (!feature || !project || segment === '') return;
        btn._vcL = true;
        const oh = btn.innerHTML;
        const origBg = btn.style.background;
        const origColor = btn.style.color;
        const origBorder = btn.style.border;
        const origCursor = btn.style.cursor;
        const origTitle = btn.title;
        btn.style.pointerEvents = 'none';
        btn.style.opacity = '0.85';
        btn.innerHTML = '<div class="vc-spin" style="width:15px;height:15px;border-width:2px"></div><span>' + (isRemoval ? 'Removendo...' : 'Aplicando...') + '</span>';
        try {
            const r = await fetch('/apply_feature_api?project=' + project + '&segment=' + encodeURIComponent(segment) + '&feature=' + encodeURIComponent(feature) + '&action=' + encodeURIComponent(action));
            const d = await r.json();
            if (d.success) {
                let card = btn.closest('.viral-card') || btn.parentElement;
                while (card && !card.querySelector('video')) card = card.parentElement;
                vcReloadVideoInCard(card, d.video_url, d.download_name);
                // Estado "já aplicado": botão fica cinza/desativado.
                btn.classList.add('applied');
                btn.disabled = true;
                btn.style.background = '#E2E8F0';
                btn.style.color = '#94A3B8';
                btn.style.border = '1px solid #CBD5E1';
                btn.style.cursor = 'default';
                btn.style.pointerEvents = 'none';
                btn.style.opacity = '1';
                btn.style.filter = 'none';
                btn.title = 'Já aplicado neste corte';
                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg><span>' + (label || 'Aplicado') + '</span>';
                if (d.features) {
                    vcSyncFeatureButtons(card, d.features);
                } else {
                    vcSetFeatureButtonState(btn, !isRemoval);
                }
                btn.style.pointerEvents = '';
                btn.style.opacity = '1';
                btn._vcL = false;
            } else {
                console.warn('Aplicar recurso falhou:', d.error);
                btn.innerHTML = vcIcon('x', 14) + '<span>Erro</span>';
                btn.style.background = '#E11D48';
                btn.style.color = '#fff';
                btn.title = 'Erro: ' + (d.error || 'falhou');
                setTimeout(() => { btn.innerHTML = oh; btn.style.background = origBg; btn.style.color = origColor; btn.style.border = origBorder; btn.style.cursor = origCursor; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn.title = origTitle; btn._vcL = false; }, 3500);
            }
        } catch (err) {
            console.warn('Aplicar recurso erro:', err);
            btn.innerHTML = vcIcon('x', 14) + '<span>Erro</span>';
            btn.style.background = '#7f1d1d';
            btn.style.color = '#fff';
            setTimeout(() => { btn.innerHTML = oh; btn.style.background = origBg; btn.style.color = origColor; btn.style.border = origBorder; btn.style.cursor = origCursor; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn.title = origTitle; btn._vcL = false; }, 3500);
        }
    }, true);
})();
"""

# Pergunta de limpeza só na 1ª carga por inicialização do app (não repete a cada refresh).
_startup_cleanup_asked = False

with gr.Blocks(title=i18n("Viral Cutter · Church Edition")) as demo:
    gr.HTML(header.header_html)

    # --- Pergunta "limpar arquivos antigos?" ao abrir o app (preenchida em demo.load) ---
    with gr.Group(visible=False) as startup_cleanup_banner:
        gr.Markdown(i18n(
            "## Limpar arquivos antigos?\n"
            "Encontrei projetos e temporários parados há mais de **2 semanas**. Quer apagar agora "
            "para liberar espaço? Seus **assets**, as **configurações** e a **chave de API** não "
            "serão tocados."
        ))
        startup_cleanup_targets = gr.State([])
        startup_cleanup_box = gr.Textbox(label=i18n("O que pode ser apagado"), lines=8, interactive=False)
        with gr.Row():
            startup_cleanup_yes = gr.Button(i18n("Sim, limpar agora"), variant="stop")
            startup_cleanup_no = gr.Button(i18n("Agora não, manter"), variant="secondary")
        startup_cleanup_status = gr.Markdown("")

    with gr.Tabs():
        with gr.Tab(i18n("Criar Cortes")) as create_tab:
             with gr.Row():
                with gr.Column(scale=1):
                    gr.HTML(styles.step_badge(1, i18n("Escolha o vídeo")))
                    input_source = gr.Radio([(i18n("Upar vídeo"), "Upload Video"), (i18n("Link do YouTube"), "YouTube URL"), (i18n("Projeto já criado"), "Existing Project")], label=i18n("De onde vem o vídeo?"), value="Upload Video")
                    
                    video_upload = gr.File(label=i18n("Arraste seu vídeo aqui (ou clique para escolher)"), file_count="single", file_types=["video"], visible=True)
                    url_input = gr.Textbox(label=i18n("Link do YouTube"), placeholder="https://www.youtube.com/watch?v=...", visible=False)
                    
                    with gr.Group(visible=False) as youtube_group:
                        with gr.Row():
                            video_quality_input = gr.Dropdown(choices=["best", "1080p", "720p", "480p"], label=i18n("Qualidade do download"), value=ui_state.get("video_quality", "best"))
                            use_youtube_subs_input = gr.Checkbox(label=i18n("Usar legendas prontas do YouTube"), value=ui_state.get("use_youtube_subs", False), info=i18n("Mais rápido quando o vídeo já tem legenda."))

                    project_selector = gr.Dropdown(choices=[], label=i18n("Escolha o projeto"), visible=False)
                    
                    def on_source_change(source):
                        if source == "YouTube URL":
                            return gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), gr.update(value="Full"), gr.update(visible=True)
                        elif source == "Upload Video":
                            return gr.update(visible=False), gr.update(visible=False), gr.update(visible=True), gr.update(value="Full"), gr.update(visible=False)
                        else:
                            # Load projects
                            projs = library.get_existing_projects()
                            return gr.update(visible=False), gr.update(choices=projs, visible=True), gr.update(visible=False), gr.update(value="Subtitles Only"), gr.update(visible=False)
                    
                    
                    gr.HTML(styles.step_badge(2, i18n("Como cortar")))
                    gr.HTML(styles.help_banner(i18n("Cada corte vira um vídeo curto. A IA encontra os melhores momentos da pregação automaticamente.")))
                    with gr.Row():
                        segments_input = gr.Number(label=i18n("Quantos cortes você quer?"), value=ui_state.get("segments", 12), precision=0)
                        viral_input = gr.Checkbox(label=i18n("Deixar a IA escolher os melhores trechos"), value=ui_state.get("viral", True))
                    themes_input = gr.Textbox(label=i18n("Temas (opcional)"), placeholder=i18n("ex.: fé, família, esperança"), visible=False, value=ui_state.get("themes", ""))
                    viral_input.change(lambda x: gr.update(visible=not x), viral_input, themes_input)
                    hook_mode_input = gr.Checkbox(label=i18n("Gancho no 1º segundo (experimental)"), value=ui_state.get("hook_mode", False), info=i18n("Prioriza cortes que começam com frase polêmica ou inesperada (ex.: \"Pastor, fazer tatuagem é pecado?\"). Desmarcado = prompt clássico."))
                    _ai_dur_initial = bool(ui_state.get("ai_duration", False))
                    ai_duration_input = gr.Checkbox(label=i18n("Deixar a IA decidir a duração de cada corte"), value=_ai_dur_initial, info=i18n("Recomendado. Se desligar, você define a duração mínima e máxima abaixo."))
                    with gr.Row():
                        min_dur_input = gr.Number(label=i18n("Duração mínima (segundos)"), value=ui_state.get("min_duration", 60), visible=not _ai_dur_initial)
                        max_dur_input = gr.Number(label=(i18n("Teto de segurança (s)") if _ai_dur_initial else i18n("Duração máxima (segundos)")), value=ui_state.get("max_duration", 140))
                    def _toggle_ai_duration(ai):
                        # Quando a IA decide: não há mínimo — escondemos o campo Mín
                        # (sinal visível de que mudou); o Máx continua como teto de segurança.
                        return gr.update(visible=not ai), gr.update(label=(i18n("Teto de segurança (s)") if ai else i18n("Duração máxima (segundos)")))
                    ai_duration_input.change(_toggle_ai_duration, inputs=ai_duration_input, outputs=[min_dur_input, max_dur_input])
                with gr.Column(scale=1):
                    gr.HTML(styles.step_badge(3, i18n("Inteligência Artificial"), i18n("configure uma vez")))
                    gr.HTML(styles.help_banner(i18n("A IA precisa de uma chave gratuita do Google para entender a pregação. Cole sua chave abaixo uma única vez — ela fica salva.")))
                    api_key_input = gr.Textbox(label=i18n("Chave de IA (Google Gemini)"), type="password", placeholder=i18n("Cole aqui a sua chave..."))
                    api_key_status = gr.HTML(api_key_status_html())
                    gr.Markdown(i18n("Não tem uma chave? O passo a passo para conseguir (é grátis) está na aba **Sobre**."))

                    with gr.Accordion(i18n("Opções avançadas (não precisa mexer)"), open=False):
                        model_input = gr.Dropdown(["tiny", "small", "medium", "large", "large-v1", "large-v2", "large-v3", "turbo", "large-v3-turbo", "distil-large-v2", "distil-medium.en", "distil-small.en", "distil-large-v3"], label=i18n("Qualidade da transcrição"), value=ui_state.get("model", "large-v3-turbo"), info=i18n("Já está no melhor. Mude só se souber o que está fazendo."))
                        with gr.Row():
                            ai_model_input = gr.Dropdown(choices=GEMINI_MODELS, label=i18n("Modelo de IA"), value=ui_state.get("ai_model_name", GEMINI_MODELS[0]), allow_custom_value=True, visible=True, scale=5)
                            chunk_size_input = gr.Number(label=i18n("Tamanho do bloco de texto"), value=ui_state.get("chunk_size", 70000), precision=0, scale=2)
                        workflow_input = gr.Dropdown(choices=[(i18n("Vídeo completo (corte + legenda)"), "Full"), (i18n("Apenas cortar"), "Cut Only"), (i18n("Apenas legendar"), "Subtitles Only")], label=i18n("O que fazer com o vídeo?"), value=ui_state.get("workflow", "Full"))
                        manual_mode_input = gr.Checkbox(label=i18n("Curadoria manual (avançado, via JSON)"), value=ui_state.get("manual_mode", False))

                    with gr.Column(visible=ui_state.get("manual_mode", False)) as manual_review_group:
                         gr.Markdown("### " + i18n("Curadoria de IA Manual"))
                         gr.Markdown(i18n("1. Clique em 'Start Processing' para baixar/transcrever o arquivo se ainda não o fez. O prompt será gerado na caixa abaixo.\n2. Copie e cole na sua IA externa.\n3. Cole a resposta JSON na caixa inferior e salve."))
                         manual_review_prompt = gr.Textbox(label=i18n("Prompt Gerado (Copie integralmente)"), interactive=False, lines=4)
                         manual_review_json = gr.Textbox(label=i18n("Cole o Retorno (JSON) da Inteligência Artificial Aqui"), lines=8, placeholder='{"segments": [...]}')
                         
                         resume_manual_btn = gr.Button(i18n("Salvar JSON e Pular Fase 1 (Retoma edição)"), variant="primary")
                         resume_status = gr.Textbox(label="Status de Salvamento", interactive=False)
                     
                         def resume_process(project_selection, upload_file, source, jsn):
                              # Se não selecionou projeto existente, tenta deduzir se fez upload
                              proj = project_selection
                              if not proj and source == "Upload Video" and upload_file:
                                  pass
                              
                              if not proj:
                                  # Tenta pegar o diretório mais recente em VIRALS
                                  base_virals = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VIRALS")
                                  if os.path.exists(base_virals):
                                      subdirs = [os.path.join(base_virals, d) for d in os.listdir(base_virals) if os.path.isdir(os.path.join(base_virals, d))]
                                      if subdirs:
                                          proj = max(subdirs, key=os.path.getmtime)
                                          
                              if not proj:
                                  return "Nenhum projeto encontrado. Reposicione na seleção de projeto.", gr.update(), gr.update()
                                  
                              proj_name = os.path.basename(os.path.normpath(proj))
                              proj_dir = proj if os.path.isabs(proj) else os.path.join(VIRALS_DIR, proj_name)

                              # Validar/sanitizar o JSON colado ANTES de salvar
                              # (lida com cercas ```json, texto extra e JSON truncado da IA externa)
                              data = None
                              try:
                                  from scripts.create_viral_segments import clean_json_response
                                  text = (jsn or "").strip()
                                  try:
                                      parsed = json.loads(text)
                                      if isinstance(parsed, dict) and isinstance(parsed.get("segments"), list):
                                          data = parsed
                                      elif isinstance(parsed, list):
                                          data = {"segments": parsed}
                                  except (ValueError, TypeError):
                                      data = None
                                  if not (data and data.get("segments")):
                                      data = clean_json_response(text)
                              except Exception as e:
                                  return f"Erro ao interpretar o JSON: {e}", gr.update(), gr.update()

                              if not (isinstance(data, dict) and data.get("segments")):
                                  return ("Erro: não encontrei uma lista 'segments' válida no JSON colado. "
                                          "Cole no formato {\"segments\": [...]} (pode vir com cercas ```json, eu limpo).",
                                          gr.update(), gr.update())

                              try:
                                  save_path = os.path.join(proj_dir, "viral_segments.txt")
                                  with open(save_path, "w", encoding="utf-8") as f:
                                      json.dump(data, f, ensure_ascii=False, indent=2)
                              except Exception as e:
                                  return f"Erro ao escrever viral_segments: {e}", gr.update(), gr.update()
                              
                              projs = library.get_existing_projects()
                              if proj_name not in projs:
                                  projs = projs + [proj_name]
                              n = len(data["segments"])
                              return (f"OK: {n} segmento(s) salvos em '{proj_name}'.\n"
                                      "AGORA CLIQUE EM 'Start Processing' para continuar o corte!",
                                      gr.update(value="Existing Project", visible=True),
                                      gr.update(choices=projs, value=proj_name, visible=True))
        
                         resume_manual_btn.click(
                              resume_process, 
                              inputs=[project_selector, video_upload, input_source, manual_review_json], 
                              outputs=[resume_status, input_source, project_selector]
                         )

                    
                    # Hide/show AI fields when manual curation is toggled

                    def on_manual_mode_change(is_manual):
                        return gr.update(visible=not is_manual), gr.update(visible=not is_manual), gr.update(visible=not is_manual), gr.update(visible=is_manual)

                    manual_mode_input.change(on_manual_mode_change, inputs=manual_mode_input, outputs=[api_key_input, ai_model_input, chunk_size_input, manual_review_group])

                    # Update listeners now that all components are defined
                    input_source.change(on_source_change, inputs=input_source, outputs=[url_input, project_selector, video_upload, workflow_input, youtube_group])

                    # Salvar a chave de IA ao pressionar Enter (sem precisar gerar).
                    def _save_key_and_refresh(k):
                        save_api_key(k)
                        return api_key_status_html()
                    api_key_input.submit(_save_key_and_refresh, inputs=api_key_input, outputs=api_key_status)

             with gr.Accordion(i18n("Subtitle Settings (alpha)"), open=False):
                preset_input = gr.Dropdown(choices=[(i18n(k), k) for k in subs.SUBTITLE_PRESETS.keys()], label=i18n("Quick Presets"), value="Church Clear")
                use_custom_subs = gr.Checkbox(label=i18n("Enable Subtitle Customization (Includes Preset)"), value=True)
                
                # Previews (Always Visible)
                preview_html = gr.HTML(value=f"<div style='text-align:center; padding:10px; color:#666;'>{i18n('Select options or preset to preview')}</div>")
                
                with gr.Row():
                    preview_vid_btn = gr.Button(i18n("Render Animated Preview (Slow)"), size="sm")
                preview_vid = gr.Video(label=i18n("Animated Preview"), height=300, autoplay=True, interactive=False)
                
                with gr.Accordion(i18n("Advanced Settings"), open=False):
                    gr.Markdown(f"### {i18n('Appearance')}")
                    with gr.Row():
                        font_name_input = gr.Textbox(label=i18n("Font Name"), value=ui_state.get("font_name", "Montserrat"))
                        font_size_input = gr.Slider(label=i18n("Font Size (Base)"), minimum=8, maximum=80, value=ui_state.get("font_size", 30))
                        highlight_size_input = gr.Slider(label=i18n("Highlight Size"), minimum=8, maximum=80, value=ui_state.get("h_size", 30))
                    
                    with gr.Row():
                        font_color_input = gr.ColorPicker(label=i18n("Base Color"), value=ui_state.get("font_color", "#FFFFFF"))
                        highlight_color_input = gr.ColorPicker(label=i18n("Highlight Color"), value=ui_state.get("highlight_color", "#FFFFFF"))
                        outline_color_input = gr.ColorPicker(label=i18n("Outline Color"), value=ui_state.get("outline_color", "#000000"))
                        shadow_color_input = gr.ColorPicker(label=i18n("Shadow Color"), value=ui_state.get("shadow_color", "#000000"))
                    
                    gr.Markdown(f"### {i18n('Styling & Effects')}")
                    with gr.Row():
                        outline_thickness_input = gr.Slider(label=i18n("Outline Thickness"), minimum=0, maximum=10, value=ui_state.get("outline_thickness", 1))
                        shadow_size_input = gr.Slider(label=i18n("Shadow Size"), minimum=0, maximum=10, value=ui_state.get("shadow_size", 1))
                        border_style_input = gr.Dropdown(choices=[(i18n("Outline"), 1), (i18n("Opaque Box"), 3)], label=i18n("Border Style"), value=ui_state.get("border_s", 1))
                    
                    with gr.Row():
                        bold_input = gr.Checkbox(label=i18n("Bold"), value=ui_state.get("is_bold", True))
                        italic_input = gr.Checkbox(label=i18n("Italic"), value=ui_state.get("is_italic", False))
                        uppercase_input = gr.Checkbox(label=i18n("Uppercase"), value=ui_state.get("is_uppercase", False))
                        remove_punc_input = gr.Checkbox(label=i18n("Remove Punctuation"), value=ui_state.get("remove_punc", False))
                        underline_input = gr.Checkbox(label=i18n("Underline"), value=ui_state.get("under", False))
                        strikeout_input = gr.Checkbox(label=i18n("Strikeout"), value=ui_state.get("strike", False))
                        
                    gr.Markdown(f"### {i18n('Positioning & Layout')}")
                    with gr.Row():
                        vertical_pos_input = gr.Slider(label=i18n("V-Pos (Margin V)"), minimum=0, maximum=500, value=ui_state.get("vertical_pos", 115))
                        margin_h_input = gr.Slider(label=i18n("H-Pos (Margin H)"), minimum=0, maximum=300, value=ui_state.get("margin_h", 35))
                        alignment_input = gr.Dropdown(choices=[(i18n("Left"), 1), (i18n("Center"), 2), (i18n("Right"), 3)], label=i18n("Alignment"), value=ui_state.get("alignment", 2))
                        gap_limit_input = gr.Slider(label=i18n("Gap Limit"), minimum=0.0, maximum=5.0, value=ui_state.get("gap", 0.6), step=0.1)
                        mode_input = gr.Dropdown(choices=[(i18n("Highlight"), "highlight"), (i18n("Word by Word"), "word_by_word"), (i18n("No Highlight"), "no_highlight")], label=i18n("Mode"), value=ui_state.get("mode", "no_highlight"))
                        words_per_block_input = gr.Slider(label=i18n("Words per Block"), minimum=1, maximum=20, value=ui_state.get("w_block", 4), step=1)

                manual_inputs = [
                    font_name_input, font_size_input, font_color_input, highlight_color_input, 
                    outline_color_input, outline_thickness_input, shadow_color_input, shadow_size_input, 
                    bold_input, italic_input, uppercase_input,
                    highlight_size_input, words_per_block_input, gap_limit_input, mode_input,
                    underline_input, strikeout_input, border_style_input,
                    vertical_pos_input, margin_h_input, alignment_input,
                    remove_punc_input
                ]
                
                # Update manual inputs when preset changes
                preset_input.change(subs.apply_preset, inputs=[preset_input], outputs=manual_inputs)
                
                # Auto-update PREVIEW HTML on any change
                for inp in manual_inputs:
                    inp.change(subs.generate_preview_html, inputs=manual_inputs, outputs=preview_html)

                gr.on(
                    triggers=[c.change for c in manual_inputs],
                    fn=save_subtitle_settings_live, inputs=manual_inputs, outputs=None,
                    queue=False, show_progress="hidden",
                )
                
                # Render video button
                preview_vid_btn.click(
                    subs.render_preview_video,
                    inputs=manual_inputs,
                    outputs=preview_vid
                )
                
                # Initial load
                demo.load(subs.generate_preview_html, inputs=manual_inputs, outputs=preview_html, queue=False, show_progress="hidden")
                demo.load(subs.apply_preset, inputs=[preset_input], outputs=manual_inputs, queue=False, show_progress="hidden") # Apply default preset on load

             # --- Persistência viva: o que o usuário mudar vira o novo padrão ---
             _settings_components = [
                 video_quality_input, use_youtube_subs_input, segments_input, viral_input, themes_input,
                 min_dur_input, max_dur_input, ai_duration_input, model_input, manual_mode_input,
                 ai_model_input, chunk_size_input, workflow_input, margin_h_input, hook_mode_input,
             ]
             gr.on(
                 triggers=[c.change for c in _settings_components],
                 fn=save_ui_settings_live, inputs=_settings_components, outputs=None,
                 queue=False, show_progress="hidden",
             )

             def restore_default_settings():
                 d = DEFAULT_UI_SETTINGS
                 save_ui_settings_live(**d)
                 gr.Info(i18n("Configurações restauradas para o padrão."))
                 return (
                     gr.update(value=d["video_quality"]),
                     gr.update(value=d["use_youtube_subs"]),
                     gr.update(value=d["segments"]),
                     gr.update(value=d["viral"]),
                     gr.update(value=d["themes"]),
                     gr.update(value=d["min_duration"], visible=not d["ai_duration"]),
                     gr.update(value=d["max_duration"], label=i18n("Duração máxima (segundos)")),
                     gr.update(value=d["ai_duration"]),
                     gr.update(value=d["model"]),
                     gr.update(value=d["manual_mode"]),
                     gr.update(value=d["ai_model_name"]),
                     gr.update(value=d["chunk_size"]),
                     gr.update(value=d["workflow"]),
                     gr.update(value=d["margin_h"]),
                     gr.update(value=d["hook_mode"]),
                 )

             gr.HTML(styles.step_badge(4, i18n("Gerar")))
             with gr.Row():
                 start_btn = gr.Button(i18n("Gerar meus cortes"), variant="primary", scale=2)
                 stop_btn = gr.Button(i18n("Parar"), variant="stop", visible=False, scale=1)
                 active_modules_info = gr.HTML(scale=3)
             with gr.Row():
                 restore_defaults_btn = gr.Button(i18n("Restaurar configurações padrão"), variant="secondary", size="sm", scale=1)
             restore_defaults_btn.click(restore_default_settings, outputs=_settings_components, queue=False, show_progress="hidden")
             friendly_status = gr.HTML("")
             with gr.Accordion(i18n("Ver detalhes técnicos"), open=False):
                 logs_output = gr.Textbox(label=i18n("Registro do processamento"), lines=18, max_lines=18, autoscroll=True, elem_id="logs_output")
             stop_btn.click(kill_process, outputs=[logs_output])
             
             # Force scroll to bottom via JS
             logs_output.change(fn=None, inputs=[], outputs=[], js="""
                function() {
                    var ta = document.querySelector('#logs_output textarea');
                    if(ta) {
                        // Setup scroll listener once to track user intent
                        if (!ta._scrollerSetup) {
                            ta._isSticky = true; // Default to sticky
                            ta.addEventListener('scroll', function() {
                                var diff = ta.scrollHeight - ta.scrollTop - ta.clientHeight;
                                // If near bottom (<50px), enable sticky. Else disable.
                                if (diff <= 50) {
                                     ta._isSticky = true;
                                } else {
                                     ta._isSticky = false;
                                }
                            });
                            ta._scrollerSetup = true;
                        }
                        
                        // Apply scroll only if sticky
                        if(ta._isSticky === undefined || ta._isSticky === true) {
                            ta.scrollTop = ta.scrollHeight;
                        }

                        // Status amigável: traduz o log técnico para linguagem simples.
                        try {
                            var box = document.getElementById('vc_status');
                            if (box) {
                                // Só a cauda: barato mesmo se muitos .change dispararem
                                // de uma vez quando a janela volta ao foco.
                                var t = (ta.value || '').slice(-6000).toLowerCase();
                                var stages = [
                                    ['baixando', 'download', 'Baixando o vídeo...'],
                                    ['download', 'download', 'Baixando o vídeo...'],
                                    ['transcre', 'edit', 'Transcrevendo o áudio...'],
                                    ['transcrib', 'edit', 'Transcrevendo o áudio...'],
                                    ['viral', 'sparkles', 'Encontrando os melhores momentos...'],
                                    ['segmento', 'sparkles', 'Encontrando os melhores momentos...'],
                                    ['cortando', 'scissors', 'Cortando os vídeos...'],
                                    ['cutting', 'scissors', 'Cortando os vídeos...'],
                                    ['editing', 'film', 'Montando os cortes verticais...'],
                                    ['editando', 'film', 'Montando os cortes verticais...'],
                                    ['legenda', 'message', 'Gerando as legendas...'],
                                    ['subtitle', 'message', 'Gerando as legendas...'],
                                    ['conclu', 'done', ''],
                                    ['sucesso', 'done', ''],
                                    ['completed', 'done', '']
                                ];
                                var stage = null, done = false;
                                for (var i=0;i<stages.length;i++){
                                    if (t.indexOf(stages[i][0])>=0){
                                        if (stages[i][1]==='done'){ done = true; stage = vcIcon('check', 18) + '<span>Pronto! Seus cortes estão prontos.</span>'; }
                                        else { stage = vcIcon(stages[i][1], 18) + '<span>' + stages[i][2] + '</span>'; }
                                    }
                                }
                                var err = (t.indexOf('traceback')>=0);
                                if (err) { stage = vcIcon('alert', 18) + '<span>Algo deu errado - abra "Ver detalhes técnicos" abaixo.</span>'; }
                                if (stage) {
                                    var bg = err ? 'rgba(225,29,72,.10)' : 'var(--vc-surface-soft)';
                                    var col = err ? 'var(--vc-error)' : 'var(--vc-primary-deep)';
                                    var bd = err ? 'rgba(225,29,72,.30)' : 'var(--vc-border)';
                                    var spin = (!done && !err) ? '<span class="vc-spin" style="width:16px;height:16px;border-width:2px;margin-right:4px;"></span>' : '';
                                    var html = '<div style="display:flex;align-items:center;gap:8px;padding:12px 16px;border-radius:12px;background:'+bg+';color:'+col+';font-weight:600;border:1px solid '+bd+';">'+spin+stage+'</div>';
                                    // Não reescreve o DOM se nada mudou — evita
                                    // travamento ao drenar a fila de updates.
                                    if (box._vcLast !== html) { box.innerHTML = html; box._vcLast = html; }
                                }
                            }
                        } catch(e) {}
                    }
                }
             """)
             
             results_html = gr.HTML(label=i18n("Results"))
             
             

             
             # MUST pass all all new inputs to the run function
             start_btn.click(run_viral_cutter, inputs=[
                 input_source, project_selector, url_input, video_upload, segments_input, viral_input, hook_mode_input, themes_input, min_dur_input, max_dur_input, ai_duration_input,
                 model_input, manual_mode_input, api_key_input, ai_model_input, chunk_size_input, workflow_input,
                 use_custom_subs,
                 # Subtitle styling inputs
                 font_name_input, font_size_input, font_color_input, highlight_color_input,
                 outline_color_input, outline_thickness_input, shadow_color_input, shadow_size_input,
                 bold_input, italic_input, uppercase_input, vertical_pos_input, margin_h_input, alignment_input,
                 highlight_size_input, words_per_block_input, gap_limit_input, mode_input,
                 underline_input, strikeout_input, border_style_input, remove_punc_input,
                 video_quality_input, use_youtube_subs_input
             ], outputs=[logs_output, start_btn, stop_btn, friendly_status, results_html, manual_review_group, manual_review_prompt])


        with gr.Tab(i18n("Identidade da Igreja")):
            gr.HTML(styles.help_banner(i18n("Configure a identidade visual e sonora da sua igreja uma única vez. Tudo isso é aplicado automaticamente nos seus cortes.")))
            with gr.Tabs():
                with gr.Tab(i18n("Logo / Marca d'água")) as watermark_tab:
                    gr.Markdown("### " + i18n("Configuração de Marca d'água"))
                    gr.HTML(styles.help_banner(i18n("Coloque o logo da sua igreja por cima de todos os cortes. Envie uma imagem PNG com fundo transparente e ajuste posição e tamanho na pré-visualização.")))
            
                    watermark_cfg = watermark_handler.load_watermark_config()
                    watermark_image_state = gr.State(value=watermark_cfg.get("watermark_image_path", None))
            
                    with gr.Row():
                        with gr.Column(scale=1):
                            watermark_enabled_input = gr.Checkbox(label=i18n("Ativar Marca d'água"), value=watermark_cfg.get("enabled", False))
                            watermark_image_input = gr.File(label=i18n("Upload Imagem da Marca d'água (PNG/JPG com fundo transparente)"), file_types=[".png", ".jpg", ".jpeg", "image"])
                            watermark_saved_assets = gr.HTML(_watermark_asset_from_state(watermark_cfg.get("watermark_image_path")))

                            gr.Markdown("#### " + i18n("Posição e Escala da Marca d'água"))
                            watermark_x_input = gr.Slider(label=i18n("Posição X"), minimum=-1080, maximum=1080, value=watermark_cfg.get("position_x", 480), step=1)
                            watermark_y_input = gr.Slider(label=i18n("Posição Y"), minimum=-1920, maximum=1920, value=watermark_cfg.get("position_y", 0), step=1)
                            watermark_scale_input = gr.Slider(label=i18n("Escala (%)"), minimum=1, maximum=500, value=watermark_cfg.get("scale", 15), step=1)
                            watermark_opacity_input = gr.Slider(label=i18n("Opacidade (%)"), minimum=0, maximum=100, value=watermark_cfg.get("opacity", 30), step=1)
                    
                            watermark_save_btn = gr.Button(i18n("Salvar Marca d'água"), variant="primary")
                            watermark_status_txt = gr.Textbox(label=i18n("Status"), interactive=False)
                            watermark_refresh_preview_btn = gr.Button(i18n("Atualizar Preview Manualmente"))

                        with gr.Column(scale=1):
                            gr.Markdown("#### " + i18n("Preview da Marca d'água (Fundo Demonstrativo)"))
                            watermark_preview_img = gr.Image(label=i18n("Preview"), interactive=False)
            
                    watermark_inputs = [watermark_image_input, watermark_image_state, watermark_x_input, watermark_y_input, watermark_scale_input, watermark_opacity_input]
                    watermark_triggers = [watermark_image_input, watermark_x_input, watermark_y_input, watermark_scale_input, watermark_opacity_input]
             
                    for w_inp in watermark_triggers:
                        w_inp.change(_watermark_preview_from_saved, inputs=watermark_inputs, outputs=watermark_preview_img, queue=False, show_progress="hidden")
             
                    watermark_refresh_preview_btn.click(_watermark_preview_from_saved, inputs=watermark_inputs, outputs=watermark_preview_img, queue=False)
             
                    watermark_save_btn.click(
                        _save_watermark_config_and_state,
                        inputs=[watermark_enabled_input, watermark_image_input, watermark_x_input, watermark_y_input, watermark_scale_input, watermark_opacity_input],
                        outputs=[watermark_status_txt, watermark_image_state]
                    ).then(
                        _watermark_asset_from_state, inputs=[watermark_image_state], outputs=watermark_saved_assets, queue=False, show_progress="hidden"
                    ).then(get_active_modules_html, inputs=[], outputs=active_modules_info, queue=False, show_progress="hidden")

                    watermark_tab.select(_watermark_preview_from_saved, inputs=watermark_inputs, outputs=watermark_preview_img, queue=False, show_progress="hidden")
                    watermark_tab.select(_watermark_asset_from_state, inputs=[watermark_image_state], outputs=watermark_saved_assets, queue=False, show_progress="hidden")

                with gr.Tab(i18n("Trilha sonora")) as audio_tab:
                    gr.Markdown("### " + i18n("Configuração de Áudio BGM (Background Music)"))
                    gr.HTML(styles.help_banner(i18n("Toca uma música de fundo baixinha durante os cortes. Envie um arquivo de áudio e ajuste o volume — dá para ouvir a prévia antes de salvar.")))
            
                    audio_cfg = audio_handler.load_audio_config()
                    _outro_music_cfg = audio_cfg.get("outro_music", {})
                    audio_file_state = gr.State(value=audio_cfg.get("audio_file_path", None))
                    outro_music_file_state = gr.State(value=_outro_music_cfg.get("audio_file_path", None))
            
                    with gr.Row():
                        with gr.Column(scale=1):
                            audio_enabled_input = gr.Checkbox(label=i18n("Ativar Áudio de Fundo"), value=audio_cfg.get("enabled", False))
                            audio_file_input = gr.File(label=i18n("Upload de Áudio (MP3, WAV, etc.)"), file_types=["audio"])
                            audio_saved_assets = gr.HTML(_audio_assets_from_state(audio_cfg.get("audio_file_path"), _outro_music_cfg.get("audio_file_path")))

                            gr.Markdown("#### " + i18n("Ajustes Globais"))
                            audio_base_volume_input = gr.Slider(label=i18n("Volume Base (%)"), minimum=0, maximum=100, value=audio_cfg.get("base_volume", 12), step=1)
                            audio_loop_input = gr.Checkbox(label=i18n("Loop: Repetir áudio até o final do vídeo"), value=audio_cfg.get("loop_to_end", True))
                    
                            with gr.Row():
                                audio_fade_in_input = gr.Slider(label=i18n("Fade-in Inicial (s)"), minimum=0.0, maximum=10.0, value=audio_cfg.get("fade_in_duration", 0.5), step=0.5)
                                audio_fade_out_input = gr.Slider(label=i18n("Fade-out Final (s)"), minimum=0.0, maximum=10.0, value=audio_cfg.get("fade_out_duration", 0.5), step=0.5)

                        with gr.Column(scale=1):
                            gr.Markdown("#### " + i18n("Opções de Fim de Vídeo"))
                            gr.Markdown(i18n("Aumente ou reduza o volume do áudio de fundo automaticamente nos últimos segundos do vídeo."))
                            audio_stop_before_outro_input = gr.Checkbox(label=i18n("Parar Áudio BGM antes do Encerramento / Outro começar"), value=audio_cfg.get("stop_before_outro", True), info="Use se o seu Outro já possuir música própria.")
                            audio_use_ending_volume_input = gr.Checkbox(label=i18n("Ativar Variação de Volume no Final"), value=audio_cfg.get("use_ending_volume", True))
                            audio_sync_outro_input = gr.Checkbox(label=i18n("Sincronizar tempo de Volume automaticamente com o Encerramento / Outro"), value=audio_cfg.get("sync_with_outro", True))
                            audio_ending_volume_input = gr.Slider(label=i18n("Volume Secundário / Final (%)"), minimum=0, maximum=100, value=audio_cfg.get("ending_volume", 20), step=1)
                    
                            audio_ending_start_time_input = gr.Slider(label=i18n("Iniciar quantos segundos antes de acabar? (Ignorado se 'Sincronizar' estiver ativo)"), minimum=0, maximum=60, value=audio_cfg.get("ending_start_time", 10), step=1, visible=not audio_cfg.get("sync_with_outro", True))
                            audio_crossfade_input = gr.Slider(label=i18n("Suavização da Variação (s) (Ignorado se 'Sincronizar' estiver ativo)"), minimum=0.0, maximum=10.0, value=audio_cfg.get("crossfade_duration", 3.0), step=0.5, visible=not audio_cfg.get("sync_with_outro", True))

                    gr.Markdown("---")
                    gr.Markdown("### " + i18n("Música de Encerramento (Outro Music)"))
                    gr.Markdown(i18n("Toca uma música específica durante a vinheta de encerramento. A BGM fará fade-out na transição e esta música fará fade-in no mesmo momento."))

                    with gr.Row():
                        with gr.Column(scale=1):
                            outro_music_enabled_input = gr.Checkbox(
                                label=i18n("Ativar Música de Encerramento"),
                                value=_outro_music_cfg.get("enabled", False),
                                info=i18n("Requer que o Outro/Encerramento esteja ativo."),
                            )
                            outro_music_file_input = gr.File(
                                label=i18n("Upload da Música de Encerramento (MP3, WAV, etc.)"),
                                file_types=["audio"],
                            )
                            outro_music_volume_input = gr.Slider(
                                label=i18n("Volume da Música de Encerramento (%)"),
                                minimum=0, maximum=100,
                                value=_outro_music_cfg.get("volume", 50),
                                step=1,
                            )
                            outro_music_start_from_input = gr.Dropdown(
                                label=i18n("Usar trecho do arquivo"),
                                choices=[
                                    (i18n("Início do arquivo"), "start"),
                                    (i18n("Final do arquivo"), "end"),
                                ],
                                value=_outro_music_cfg.get("start_from", "end"),
                                info=i18n("Ex: música de 40s, Outro de 10s → 'Início' usa os primeiros 10s, 'Final' usa os últimos 10s."),
                            )

                        with gr.Column(scale=1):
                            outro_music_fade_in_input = gr.Slider(
                                label=i18n("Fade-in da Música de Encerramento (s)"),
                                minimum=0.0, maximum=10.0,
                                value=_outro_music_cfg.get("fade_in_duration", 1),
                                step=0.5,
                            )
                            outro_music_fade_out_enabled_input = gr.Checkbox(
                                label=i18n("Ativar Fade-out no final da Música de Encerramento"),
                                value=_outro_music_cfg.get("fade_out_enabled", True),
                            )
                            outro_music_fade_out_input = gr.Slider(
                                label=i18n("Fade-out da Música de Encerramento (s)"),
                                minimum=0.0, maximum=10.0,
                                value=_outro_music_cfg.get("fade_out_duration", 1),
                                step=0.5,
                                visible=_outro_music_cfg.get("fade_out_enabled", True),
                            )

                    with gr.Row():
                        audio_save_btn = gr.Button(i18n("Salvar Configurações de Áudio"), variant="primary")
                    audio_status_txt = gr.Textbox(label=i18n("Status"), interactive=False)
            
                    gr.Markdown("---")
                    gr.Markdown("### " + i18n("Preview do Volume Base em Tempo Real"))
                    with gr.Row():
                        with gr.Column():
                            audio_preview_video_input = gr.File(label=i18n("Upload de um Vídeo Teste (Para servir de base)"), file_types=["video"], file_count="single")
                        with gr.Column():
                            audio_preview_html = gr.HTML('<div style="color:#888; padding: 20px; text-align:center;">' + i18n('Adicione o arquivo de Áudio (acima) e um Vídeo de teste (ao lado) para ouvir o volume tocar de fundo junto com o vídeo.') + '</div>')
                    
                    # Helper to hide/show manual sliders based on sync checkbox
                    def toggle_sync_visibility(is_sync):
                        return gr.update(visible=not is_sync), gr.update(visible=not is_sync)

                    def toggle_outro_fade_out_visibility(enabled):
                        return gr.update(visible=enabled)
                
                    audio_sync_outro_input.change(toggle_sync_visibility, inputs=audio_sync_outro_input, outputs=[audio_ending_start_time_input, audio_crossfade_input], queue=False, show_progress="hidden")

                    outro_music_fade_out_enabled_input.change(
                        toggle_outro_fade_out_visibility,
                        inputs=outro_music_fade_out_enabled_input,
                        outputs=outro_music_fade_out_input,
                        queue=False,
                        show_progress="hidden",
                    )
            
                    def _save_audio_config_with_outro(
                        enabled, audio_file_path, base_volume, loop_to_end,
                        fade_in_duration, fade_out_duration, crossfade_duration,
                        use_ending_volume, stop_before_outro, sync_with_outro,
                        ending_volume, ending_start_time,
                        outro_music_enabled, outro_music_file, outro_music_volume,
                        outro_music_start_from, outro_music_fade_in,
                        outro_music_fade_out_enabled, outro_music_fade_out,
                    ):
                        status = audio_handler.save_audio_config(
                            enabled=enabled,
                            audio_file_path=audio_file_path,
                            base_volume=base_volume,
                            loop_to_end=loop_to_end,
                            fade_in_duration=fade_in_duration,
                            fade_out_duration=fade_out_duration,
                            crossfade_duration=crossfade_duration,
                            use_ending_volume=use_ending_volume,
                            stop_before_outro=stop_before_outro,
                            sync_with_outro=sync_with_outro,
                            ending_volume=ending_volume,
                            ending_start_time=ending_start_time,
                            source_video_volume=None,  # preserve existing value
                            outro_music_enabled=outro_music_enabled,
                            outro_music_file=outro_music_file,
                            outro_music_volume=outro_music_volume,
                            outro_music_start_from=outro_music_start_from,
                            outro_music_fade_in=outro_music_fade_in,
                            outro_music_fade_out_enabled=outro_music_fade_out_enabled,
                            outro_music_fade_out=outro_music_fade_out,
                        )
                        cfg = audio_handler.load_audio_config()
                        outro_music_cfg = cfg.get("outro_music", {}) or {}
                        return status, cfg.get("audio_file_path"), outro_music_cfg.get("audio_file_path")

                    audio_save_btn.click(
                        _save_audio_config_with_outro,
                        inputs=[
                            audio_enabled_input, audio_file_input, audio_base_volume_input, audio_loop_input,
                            audio_fade_in_input, audio_fade_out_input, audio_crossfade_input,
                            audio_use_ending_volume_input, audio_stop_before_outro_input, audio_sync_outro_input,
                            audio_ending_volume_input, audio_ending_start_time_input,
                            outro_music_enabled_input,
                            outro_music_file_input,
                            outro_music_volume_input,
                            outro_music_start_from_input,
                            outro_music_fade_in_input,
                            outro_music_fade_out_enabled_input,
                            outro_music_fade_out_input,
                        ],
                        outputs=[audio_status_txt, audio_file_state, outro_music_file_state]
                    ).then(
                        _audio_assets_from_state, inputs=[audio_file_state, outro_music_file_state], outputs=audio_saved_assets, queue=False, show_progress="hidden"
                    ).then(get_active_modules_html, inputs=[], outputs=active_modules_info, queue=False, show_progress="hidden")

            
                    # Preview Triggers
                    audio_preview_video_input.change(
                        _audio_preview_from_saved,
                        inputs=[audio_preview_video_input, audio_file_input, audio_file_state, audio_base_volume_input, audio_loop_input],
                        outputs=audio_preview_html,
                        queue=False,
                    )
                    audio_file_input.change(
                        _audio_preview_from_saved,
                        inputs=[audio_preview_video_input, audio_file_input, audio_file_state, audio_base_volume_input, audio_loop_input],
                        outputs=audio_preview_html,
                        queue=False,
                    )
            
                    # Real-time Volume Adjustment via JS (only affects the preview HTML logic, doesn't reload the file)
                    audio_base_volume_input.change(
                        None,
                        inputs=[audio_base_volume_input],
                        outputs=None,
                        js="(vol) => { let a = document.getElementById('audio_preview_aud'); if(a) { a.volume = parseFloat(vol)/100.0; } }"
                    )


                with gr.Tab(i18n("Volume do vídeo")) as original_volume_tab:
                    gr.Markdown("### " + i18n("Visualização em Tempo Real do Volume Original"))
                    gr.HTML(styles.help_banner(i18n("Controla o volume da voz original do vídeo nos cortes. Use se a pregação ficou baixa ou alta demais.")))
                    gr.Markdown(i18n("Ajuste o volume final do áudio original do vídeo. Este valor será aplicado na exportação, mesmo sem BGM."))

                    source_volume_cfg = audio_handler.load_audio_config()
                    try:
                        source_volume_default = float(source_volume_cfg.get("source_video_volume", 200.0))
                    except (TypeError, ValueError):
                        source_volume_default = 200.0
                    source_volume_default = max(0.0, min(200.0, source_volume_default))

                    with gr.Row():
                        with gr.Column(scale=1):
                            source_video_volume_input = gr.Slider(
                                label=i18n("Volume do Vídeo Original (%)"),
                                minimum=0,
                                maximum=200,
                                value=source_volume_default,
                                step=1,
                                info=i18n("0% = mudo, 100% = original, acima de 100% amplifica o áudio.")
                            )
                            gr.Markdown(f"**{i18n('Volume Atual')}: <span id='original_volume_slider_value'>{int(round(source_volume_default))}%</span>**")
                            source_preview_video_input = gr.File(
                                label=i18n("Upload de um Vídeo Teste (Prévia do Áudio Original)"),
                                file_types=["video"],
                                file_count="single"
                            )
                            source_volume_save_btn = gr.Button(i18n("Salvar Volume Original"), variant="primary")
                            source_volume_status_txt = gr.Textbox(label=i18n("Status"), interactive=False)
                        with gr.Column(scale=1):
                            source_preview_html = gr.HTML(
                                '<div style="color:#888; padding: 20px; text-align:center;">' +
                                i18n("Carregue um vídeo para pré-visualizar o áudio original em tempo real.") +
                                '</div>'
                            )

                    source_preview_video_input.change(
                        original_volume_handler.generate_original_volume_preview,
                        inputs=[source_preview_video_input, source_video_volume_input],
                        outputs=source_preview_html
                    )

                    source_video_volume_input.change(
                        None,
                        inputs=[source_video_volume_input],
                        outputs=None,
                        js="(vol) => { const safe = Math.max(0, Math.min(200, Number(vol) || 0)); const sliderLabel = document.getElementById('original_volume_slider_value'); if (sliderLabel) { sliderLabel.textContent = Math.round(safe) + '%'; } if (window.vcUpdateOriginalVolume) { window.vcUpdateOriginalVolume(safe); } }"
                    )

                    source_volume_save_btn.click(
                        audio_handler.save_source_video_volume,
                        inputs=[source_video_volume_input],
                        outputs=source_volume_status_txt
                    ).then(get_active_modules_html, inputs=[], outputs=active_modules_info)

                with gr.Tab(i18n("Encerramento")) as outro_tab:
                    gr.Markdown(f"### {i18n('Configuração de Outro/Encerramento')}")
                    gr.HTML(styles.help_banner(i18n("Adiciona uma vinheta no fim de cada corte (ex.: convite para seguir a igreja). Envie um vídeo curto e, se quiser, uma imagem por cima.")))
            
                    outro_cfg = outro_handler.load_outro_config()
                    outro_video_state = gr.State(value=outro_cfg.get("outro_video_path", None))
                    outro_image_state = gr.State(value=outro_cfg.get("overlay_image_path", None))
            
                    with gr.Row():
                        with gr.Column(scale=1):
                            outro_enabled_input = gr.Checkbox(label=i18n("Ativar Outro / Encerramento"), value=outro_cfg.get("enabled", False))
                            outro_video_input = gr.File(label=i18n("Upload Vídeo de Encerramento (MP4)"), file_types=[".mp4", ".mov", "video"])
                            outro_image_input = gr.File(label=i18n("Upload Imagem Overlay (PNG/JPG)"), file_types=[".png", ".jpg", ".jpeg", "image"])
                            outro_saved_assets = gr.HTML(_outro_assets_from_state(outro_cfg.get("outro_video_path"), outro_cfg.get("overlay_image_path")))

                            outro_fade_input = gr.Slider(label=i18n("Duração do Fade (s)"), minimum=0.0, maximum=3.0, value=outro_cfg.get("fade_duration", 1), step=0.1)
                            outro_volume_input = gr.Slider(
                                label=i18n("Volume do Vídeo de Encerramento (%)"),
                                minimum=0, maximum=200, value=outro_cfg.get("outro_volume", 40), step=5,
                                info=i18n("Só tem efeito quando o vídeo de Outro possui áudio próprio. 100% = volume original, 0% = mudo.")
                            )

                            gr.Markdown(f"#### {i18n('Posição e Escala da Imagem')}")
                            outro_x_input = gr.Slider(label=i18n("Posição X"), minimum=-1080, maximum=1080, value=outro_cfg.get("position_x", 179), step=1)
                            outro_y_input = gr.Slider(label=i18n("Posição Y"), minimum=-1920, maximum=1920, value=outro_cfg.get("position_y", 886), step=1)
                            outro_scale_input = gr.Slider(label=i18n("Escala (%)"), minimum=1, maximum=500, value=outro_cfg.get("scale", 42), step=1)
                            outro_rounded_corners_input = gr.Slider(label=i18n("Bordas Arredondadas (%)"), minimum=0, maximum=50, value=outro_cfg.get("rounded_corners", 10), step=1)
                    
                            outro_save_btn = gr.Button(i18n("Salvar Configurações"), variant="primary")
                            outro_status_txt = gr.Textbox(label=i18n("Status"), interactive=False)
                            outro_refresh_preview_btn = gr.Button(i18n("Atualizar Preview Manualmente"))

                        with gr.Column(scale=1):
                            gr.Markdown(f"#### {i18n('Preview da Composição')}")
                            outro_preview_img = gr.Image(label=i18n("Preview"), interactive=False)
            
                    outro_inputs = [outro_video_input, outro_video_state, outro_image_input, outro_image_state, outro_x_input, outro_y_input, outro_scale_input, outro_rounded_corners_input]
                    outro_triggers = [outro_video_input, outro_image_input, outro_x_input, outro_y_input, outro_scale_input, outro_rounded_corners_input]
             
                    for o_inp in outro_triggers:
                        o_inp.change(_outro_preview_from_saved, inputs=outro_inputs, outputs=outro_preview_img, queue=False, show_progress="hidden")
             
                    outro_refresh_preview_btn.click(_outro_preview_from_saved, inputs=outro_inputs, outputs=outro_preview_img, queue=False)
             
                    outro_save_btn.click(
                        _save_outro_config_and_state,
                        inputs=[outro_enabled_input, outro_video_input, outro_image_input, outro_x_input, outro_y_input, outro_scale_input, outro_fade_input, outro_rounded_corners_input, outro_volume_input],
                        outputs=[outro_status_txt, outro_video_state, outro_image_state]
                    ).then(
                        _outro_assets_from_state, inputs=[outro_video_state, outro_image_state], outputs=outro_saved_assets, queue=False, show_progress="hidden"
                    ).then(get_active_modules_html, inputs=[], outputs=active_modules_info, queue=False, show_progress="hidden")

                    outro_tab.select(_outro_preview_from_saved, inputs=outro_inputs, outputs=outro_preview_img, queue=False, show_progress="hidden")
                    outro_tab.select(_outro_assets_from_state, inputs=[outro_video_state, outro_image_state], outputs=outro_saved_assets, queue=False, show_progress="hidden")

        with gr.Tab(i18n("Ajustar Legendas")) as subtitle_editor_tab:
            gr.Markdown(f"### {i18n('Ajustar legendas')}")
            gr.HTML(styles.help_banner(i18n("Corrija o texto das legendas à mão: escolha o projeto e o corte, edite na tabela e clique em renderizar para aplicar.")))
            
            with gr.Group():
                editor_project_dropdown = gr.Dropdown(choices=[], label=i18n("Select Project"), value=None)
                editor_refresh_btn = gr.Button(i18n("Refresh"), size="sm")
            
            with gr.Group():
                editor_file_dropdown = gr.Dropdown(choices=[], label=i18n("Select Subtitle File"), interactive=True)
                editor_load_btn = gr.Button(i18n("Load Subtitles"), variant="secondary")

            # Hidden state to store full path of currently loaded JSON
            current_json_path = gr.State()

            # The Dataframe Editor
            # Headers: Start, End, Text
            subtitle_dataframe = gr.Dataframe(
                headers=["Start", "End", "Text"],
                datatype=["str", "str", "str"],
                col_count=(3, "fixed"),
                interactive=True,
                label=i18n("Subtitle Segments"),
                wrap=True
            )

            with gr.Row():
                editor_save_btn = gr.Button(i18n("Save Changes"), variant="primary")
                editor_render_single_btn = gr.Button(i18n("Render This Segment (Very-Fast)"), variant="secondary")
                editor_render_all_btn = gr.Button(i18n("Render All (Fast)"), variant="stop")
            
            editor_status = gr.Textbox(label=i18n("Status"), interactive=False)

            # --- Callbacks for Editor ---
            editor_refresh_btn.click(library.refresh_projects, outputs=editor_project_dropdown, queue=False, show_progress="hidden")
            subtitle_editor_tab.select(library.refresh_projects, outputs=editor_project_dropdown, queue=False, show_progress="hidden")

            def update_file_list(proj_name):
                if not proj_name: return gr.update(choices=[])
                proj_path = os.path.join(VIRALS_DIR, proj_name)
                files = editor.list_editable_files(proj_path)
                return gr.update(choices=files, value=files[0] if files else None)

            editor_project_dropdown.change(update_file_list, inputs=editor_project_dropdown, outputs=editor_file_dropdown, queue=False, show_progress="hidden")

            def load_subs(proj_name, file_name):
                if not proj_name or not file_name:
                    return [], None, i18n("Please select project and file.")
                
                full_path = os.path.join(VIRALS_DIR, proj_name, 'subs', file_name)
                data = editor.load_transcription_for_editor(full_path)
                return data, full_path, i18n("Loaded {} segments.").format(len(data))

            editor_load_btn.click(load_subs, inputs=[editor_project_dropdown, editor_file_dropdown], outputs=[subtitle_dataframe, current_json_path, editor_status])

            def save_subs(json_path, df):
                if not json_path: return i18n("No file loaded.")
                data_list = df.values.tolist() if hasattr(df, 'values') else df
                msg = editor.save_editor_changes(json_path, data_list)
                return msg

            editor_save_btn.click(save_subs, inputs=[current_json_path, subtitle_dataframe], outputs=editor_status)

            def render_single(json_path, use_custom, font_name, font_size, font_color, highlight_color, 
                              outline_color, outline_thickness, shadow_color, shadow_size, 
                              is_bold, is_italic, is_uppercase, 
                              h_size, w_block, gap, mode, under, strike, border_s, 
                              vertical_pos, margin_h, alignment, remove_punc):
                
                if not json_path: return i18n("No file loaded.")
                
                subtitle_config_path = os.path.join(WORKING_DIR, "temp_subtitle_config.json")
                
                # Save config if custom subs enabled
                if use_custom:
                    subtitle_config = {
                        "font": font_name, "base_size": int(font_size), 
                        "base_color": convert_color_to_ass(font_color), 
                        "highlight_color": convert_color_to_ass(highlight_color),
                        "outline_color": convert_color_to_ass(outline_color), 
                        "outline_thickness": outline_thickness, 
                        "shadow_color": convert_color_to_ass(shadow_color),
                        "shadow_size": shadow_size, "vertical_position": vertical_pos, 
                        "margin_h": margin_h, "alignment": alignment, "bold": 1 if is_bold else 0, 
                        "italic": 1 if is_italic else 0, 
                        "underline": 1 if under else 0, "strikeout": 1 if strike else 0, 
                        "border_style": border_s, "words_per_block": int(w_block), 
                        "gap_limit": gap, "mode": mode, "highlight_size": int(h_size),
                        "uppercase": 1 if is_uppercase else 0,
                        "remove_punctuation": remove_punc
                    }
                    try:
                        with open(subtitle_config_path, "w", encoding="utf-8") as f:
                            json.dump(subtitle_config, f, indent=4)
                    except Exception as e:
                        print(f"Warning: failed to save subtitle config for single render: {e}")
                else:
                    # Remove temp config if it exists to ensure defaults are used
                    try:
                        if os.path.exists(subtitle_config_path):
                            os.remove(subtitle_config_path)
                    except Exception as e:
                        print(f"Warning: failed to remove temp subtitle config: {e}")
                
                # We expect user to SAVE first, but we could auto-save.
                # For now assume saved.
                msg = editor.render_specific_video(json_path)
                return msg

            editor_render_single_btn.click(
                render_single, 
                inputs=[current_json_path, use_custom_subs] + manual_inputs, 
                outputs=editor_status
            )

            def render_all(proj_name, use_custom, font_name, font_size, font_color, highlight_color, 
                           outline_color, outline_thickness, shadow_color, shadow_size, 
                           is_bold, is_italic, is_uppercase, 
                           h_size, w_block, gap, mode, under, strike, border_s, 
                           vertical_pos, margin_h, alignment, remove_punc):
                if not proj_name: return i18n("No project selected.")
                
                # Save config
                if use_custom:
                    subtitle_config = {
                        "font": font_name, "base_size": int(font_size), 
                        "base_color": convert_color_to_ass(font_color), 
                        "highlight_color": convert_color_to_ass(highlight_color),
                        "outline_color": convert_color_to_ass(outline_color), 
                        "outline_thickness": outline_thickness, 
                        "shadow_color": convert_color_to_ass(shadow_color),
                        "shadow_size": shadow_size, "vertical_position": vertical_pos, 
                        "margin_h": margin_h, "alignment": alignment, "bold": 1 if is_bold else 0, 
                        "italic": 1 if is_italic else 0, 
                        "underline": 1 if under else 0, "strikeout": 1 if strike else 0, 
                        "border_style": border_s, "words_per_block": int(w_block), 
                        "gap_limit": gap, "mode": mode, "highlight_size": int(h_size),
                        "uppercase": 1 if is_uppercase else 0,
                        "remove_punctuation": remove_punc
                    }
                    subtitle_config_path = os.path.join(WORKING_DIR, "temp_subtitle_config.json")
                    try:
                        with open(subtitle_config_path, "w", encoding="utf-8") as f:
                            json.dump(subtitle_config, f, indent=4)
                    except Exception as e:
                        print(f"Warning: failed to save subtitle config for full render: {e}")

                proj_path = os.path.join(VIRALS_DIR, proj_name)
                
                # IMPORTANT: Pass the config file path to the command
                subtitle_config_path = os.path.join(WORKING_DIR, "temp_subtitle_config.json")
                cmd = [sys.executable, MAIN_SCRIPT_PATH, "--project-path", proj_path, "--workflow", "3", "--skip-prompts"]
                
                if use_custom and os.path.exists(subtitle_config_path):
                     cmd.extend(["--subtitle-config", subtitle_config_path])

                try:
                    # Sem isso o usuário (principalmente no Colab) não tem como
                    # acompanhar nem diagnosticar o render em segundo plano.
                    log_path = os.path.join(proj_path, "render_all.log")
                    log_file = open(log_path, "w", encoding="utf-8")
                    subprocess.Popen(cmd, cwd=WORKING_DIR, stdout=log_file, stderr=subprocess.STDOUT)
                    return i18n("Render All started in background... Check terminal/logs.") + f"\nLog: {log_path}"
                except Exception as e:
                    return i18n("Error starting render: {}").format(e)

            editor_render_all_btn.click(
                render_all, 
                inputs=[editor_project_dropdown, use_custom_subs] + manual_inputs, 
                outputs=editor_status
            )


        with gr.Tab(i18n("Meus Vídeos")) as library_tab:
            gr.Markdown(f"### {i18n('Seus cortes prontos')}")
            gr.HTML(styles.help_banner(i18n("Escolha um projeto para ver os cortes gerados. Em cada corte você pode baixar, corrigir a legenda com IA, aplicar logo/trilha/encerramento e ajustar a margem.")))
            with gr.Row():
                project_dropdown = gr.Dropdown(choices=[], label=i18n("Select Project"), value=None)
                refresh_btn = gr.Button(i18n("Refresh List"))
            project_gallery_html = gr.HTML()
            refresh_btn.click(library.refresh_projects, outputs=project_dropdown, queue=False, show_progress="hidden")
            def on_select_project(proj_name): return library.generate_project_gallery(proj_name)
            project_dropdown.change(on_select_project, project_dropdown, project_gallery_html)
            library_tab.select(library.refresh_projects, outputs=project_dropdown, queue=False, show_progress="hidden")

            with gr.Accordion(i18n("Limpar Lixo (arquivos gerados)"), open=False):
                gr.Markdown(i18n(
                    "Apaga **todos os projetos em VIRALS**, vídeos de teste, temporários e previews. "
                    "**NÃO** apaga os assets enviados (outro/logo/música), as configurações nem a "
                    "chave de API.\n\n"
                    "**Passo 1:** clique em *Analisar* para ver o que será apagado. "
                    "**Passo 2:** confirme em *Apagar tudo*."
                ))
                cleanup_preview_box = gr.Textbox(label=i18n("Prévia (o que será apagado)"), lines=10, interactive=False)
                with gr.Row():
                    cleanup_scan_btn = gr.Button(i18n("Analisar"))
                    cleanup_confirm_btn = gr.Button(i18n("Apagar tudo"), variant="stop", visible=False)
                cleanup_status = gr.Textbox(label=i18n("Status"), interactive=False)

                def _scan_garbage():
                    text, targets = library.preview_garbage()
                    return text, gr.update(visible=len(targets) > 0), ""
                cleanup_scan_btn.click(_scan_garbage, outputs=[cleanup_preview_box, cleanup_confirm_btn, cleanup_status])

                def _do_clean():
                    return library.clean_garbage(), gr.update(visible=False), ""
                cleanup_confirm_btn.click(
                    _do_clean, outputs=[cleanup_status, cleanup_confirm_btn, cleanup_preview_box]
                ).then(library.refresh_projects, outputs=project_dropdown, queue=False, show_progress="hidden")

        with gr.Tab(i18n("Sobre / Ajuda")) as about_tab:
            gr.HTML(header.about_html)

        demo.load(get_active_modules_html, inputs=[], outputs=active_modules_info, queue=False, show_progress="hidden")

        # Ao abrir o app: pergunta (1x por inicialização) se quer limpar arquivos antigos.
        def _startup_cleanup_check():
            global _startup_cleanup_asked
            if _startup_cleanup_asked:
                return gr.update(visible=False), "", []
            _startup_cleanup_asked = True
            text, targets = library.preview_stale_garbage()
            return gr.update(visible=bool(targets)), text, targets
        demo.load(
            _startup_cleanup_check,
            outputs=[startup_cleanup_banner, startup_cleanup_box, startup_cleanup_targets],
            queue=False, show_progress="hidden",
        )

        def _startup_clean_yes(targets):
            return library.clean_garbage(targets), gr.update(visible=False)
        startup_cleanup_yes.click(
            _startup_clean_yes, inputs=startup_cleanup_targets,
            outputs=[startup_cleanup_status, startup_cleanup_banner]
        ).then(library.refresh_projects, outputs=project_dropdown, queue=False, show_progress="hidden")

        def _startup_clean_no():
            library.snooze_cleanup()
            return gr.update(visible=False)
        startup_cleanup_no.click(_startup_clean_no, outputs=startup_cleanup_banner, queue=False)
    
    gr.HTML(f"""
        <div style='text-align: center; font-size: 0.85em; color: #94A3B8; padding: 16px 0 6px; margin-top: 8px; border-top: 1px solid {PALETTE['border']};'>
            Viral Cutter · Church Edition &nbsp;•&nbsp; {i18n('100% local • código aberto • sem mensalidade')}
        </div>
        """)
if __name__ == "__main__":
    import webbrowser
    import threading
    import time
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--colab", action="store_true", help="Run in Google Colab mode")
    parser.add_argument("--server-port", type=int, default=7860, help="Port for the WebUI server")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically on Windows")
    args = parser.parse_args()

    is_windows = (os.name == 'nt')

    # Common setup for ALL environments (Colab / Windows / Linux)
    library.set_url_mode("fastapi")
    library.set_gallery_limit(os.environ.get("VC_LIBRARY_MAX_CARDS"))
    allowed_dirs = ALLOWED_DIRS
    try:
        gr.set_static_paths(paths=allowed_dirs)
    except AttributeError:
        pass

    from fastapi.responses import FileResponse
    from fastapi import BackgroundTasks

    # Helper to attach routes to any FastAPI app (whether created by Gradio or us)
    # Defined at the top level so ALL branches (Colab, Windows, Linux) can call it.
    def attach_extra_routes(fastapi_app):
        fastapi_app.mount("/virals", StaticFiles(directory=VIRALS_DIR), name="virals")
        
        def _load_gemini_config():
            """Read Gemini api_key and model from api_config.json."""
            cfg_path = os.path.join(WORKING_DIR, "api_config.json")
            if not os.path.exists(cfg_path):
                return None, None
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                gem = cfg.get("gemini", {}) or {}
                return gem.get("api_key") or None, gem.get("model") or "gemini-3.6-flash"
            except Exception:
                return None, None

        def _segment_index_from_json(json_path):
            base = os.path.basename(json_path)
            match = re.search(r"^(\d+)_", base) or re.search(r"output(\d+)", base)
            return int(match.group(1)) if match else None

        def _video_url_for_path(path):
            if not path or not os.path.exists(path):
                return None
            abs_video = os.path.abspath(path)
            abs_virals = os.path.abspath(VIRALS_DIR)
            if not (abs_video == abs_virals or abs_video.startswith(abs_virals + os.sep)):
                return None
            rel_path = os.path.relpath(abs_video, abs_virals).replace("\\", "/")
            return f"/virals/{urllib.parse.quote(rel_path, safe='/')}?t={int(time.time() * 1000)}"

        def _rendered_video_for_json(project_folder, json_path):
            base_name = os.path.splitext(os.path.basename(json_path))[0]
            candidates = [
                os.path.join(project_folder, "burned_sub", f"{base_name}_subtitled.mp4"),
            ]
            if base_name.endswith("_processed"):
                candidates.append(
                    os.path.join(project_folder, "burned_sub", f"{base_name.replace('_processed', '')}_subtitled.mp4")
                )
            existing = [p for p in candidates if os.path.exists(p)]
            if not existing:
                return None
            try:
                return max(existing, key=lambda p: os.path.getmtime(p))
            except OSError:
                return existing[0]

        def _video_payload(path):
            url = _video_url_for_path(path)
            if not url:
                return {}
            return {
                "video_url": url,
                "download_name": os.path.basename(path),
            }

        def _safe_project_path(project):
            safe_project = os.path.basename(project or "")
            project_path = os.path.join(VIRALS_DIR, safe_project)
            if not safe_project or not os.path.exists(project_path):
                return None, safe_project
            return project_path, safe_project

        def _segment_record(project_path, segment):
            viral_path = os.path.join(project_path, "viral_segments.txt")
            data = {}
            if os.path.exists(viral_path):
                try:
                    with open(viral_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            segments = data.get("segments", []) if isinstance(data.get("segments"), list) else []
            if 0 <= int(segment) < len(segments) and isinstance(segments[int(segment)], dict):
                return segments[int(segment)]
            return {}

        def _editor_video_for_segment(project_path, segment, json_path=None):
            if json_path:
                rendered_video = _rendered_video_for_json(project_path, json_path)
                if rendered_video:
                    return rendered_video
            try:
                seg = _segment_record(project_path, segment)
                return library._find_segment_video(project_path, int(segment), seg)
            except Exception:
                return None

        def _base_video_for_segment(project_path, segment):
            try:
                segment = int(segment)
                seg = _segment_record(project_path, segment)
                idx_str = f"{segment:03d}"
                base_name = library._safe_segment_base_name(segment, seg)

                candidates = []
                raw_path = seg.get("filepath")
                if raw_path:
                    raw_candidates = [raw_path]
                    if not os.path.isabs(raw_path):
                        raw_candidates.append(os.path.join(project_path, raw_path))
                    for raw_candidate in raw_candidates:
                        if raw_candidate and "burned_sub" not in os.path.normpath(raw_candidate).split(os.sep):
                            candidates.append(raw_candidate)

                search_groups = [
                    [
                        os.path.join(project_path, "final", f"{base_name}.mp4"),
                        os.path.join(project_path, "final", f"final-output{idx_str}_processed.mp4"),
                        os.path.join(project_path, f"final-output{idx_str}_processed.mp4"),
                    ],
                    [
                        os.path.join(project_path, "cuts", f"{base_name}_original_scale.mp4"),
                        os.path.join(project_path, "cuts", f"{base_name}.mp4"),
                        os.path.join(project_path, "cuts", f"output{idx_str}_original_scale.mp4"),
                        os.path.join(project_path, "cuts", f"segment_{idx_str}.mp4"),
                        os.path.join(project_path, "cuts", f"{idx_str}.mp4"),
                        os.path.join(project_path, f"output{idx_str}_original_scale.mp4"),
                        os.path.join(project_path, f"output{idx_str}.mp4"),
                    ],
                ]
                if candidates:
                    found = library._newest_existing(candidates)
                    if found:
                        return found
                for group in search_groups:
                    found = library._newest_existing(group)
                    if found:
                        return found
                for folder_name in ("final", "cuts"):
                    folder = os.path.join(project_path, folder_name)
                    if not os.path.isdir(folder):
                        continue
                    found = library._newest_existing([
                        os.path.join(folder, f)
                        for f in os.listdir(folder)
                        if f.lower().endswith(".mp4") and (f.startswith(f"{idx_str}_") or f"output{idx_str}" in f)
                    ])
                    if found:
                        return found
            except Exception:
                pass
            return _editor_video_for_segment(project_path, segment)

        def _segment_editor_payload(project_path, safe_project, segment, state, json_path=None):
            seg = _segment_record(project_path, segment)
            video_path = _editor_video_for_segment(project_path, segment, json_path)
            applied_features = {}
            try:
                applied_features = render_state.get_segment_features(project_path, int(segment))
            except Exception:
                pass
            return {
                "success": True,
                "project": safe_project,
                "segment": int(segment),
                "title": seg.get("title", f"Segmento {int(segment) + 1}"),
                "buffer_start_used": int(seg.get("buffer_start_used", seg.get("buffer_seconds", 0)) or 0),
                "buffer_end_used": int(seg.get("buffer_end_used", seg.get("buffer_seconds", 0)) or 0),
                "state": state,
                "applied_features": applied_features,
                **_video_payload(video_path),
            }

        def _set_nested_value(data, dotted_key, value):
            cur = data
            parts = str(dotted_key or "").split(".")
            for part in parts[:-1]:
                nxt = cur.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[part] = nxt
                cur = nxt
            if parts:
                cur[parts[-1]] = value

        def _safe_uploaded_name(filename):
            base, ext = os.path.splitext(filename or "asset")
            safe_base = re.sub(r"[^A-Za-z0-9_-]", "_", base).strip("_") or "asset"
            safe_ext = re.sub(r"[^A-Za-z0-9.]", "", ext.lower()) or ".bin"
            return f"{safe_base}_{int(time.time())}_{uuid.uuid4().hex[:8]}{safe_ext}"

        def _asset_category_for_field(field):
            if field in {"audio_file_path", "outro_music.audio_file_path"}:
                return "audio"
            if field == "watermark_image_path":
                return "watermark"
            return "outro"

        @fastapi_app.get("/segment_editor_state_api")
        def segment_editor_state_api(project: str, segment: int):
            try:
                project_path, safe_project = _safe_project_path(project)
                if not project_path:
                    return {"success": False, "error": f"Projeto nÃ£o encontrado: {safe_project}"}
                state = segment_editor_state.get_segment_state(project_path, int(segment), create=True)
                try:
                    from scripts.polish_segment_subs import find_segment_json
                    json_path = find_segment_json(project_path, int(segment))
                except Exception:
                    json_path = None
                return _segment_editor_payload(project_path, safe_project, int(segment), state, json_path)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        @fastapi_app.post("/segment_editor_save_api")
        def segment_editor_save_api(payload: dict = Body(...)):
            try:
                project_path, safe_project = _safe_project_path(payload.get("project"))
                if not project_path:
                    return {"success": False, "error": f"Projeto nÃ£o encontrado: {safe_project}"}
                segment = int(payload.get("segment", 0))
                current = segment_editor_state.get_segment_state(project_path, segment, create=True)
                configs = payload.get("configs") if isinstance(payload.get("configs"), dict) else current.get("configs", {})
                features = segment_editor_state.features_from_configs(configs)
                state = segment_editor_state.update_segment_state(project_path, segment, configs=configs, features=features)
                return _segment_editor_payload(project_path, safe_project, segment, state)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        @fastapi_app.post("/segment_editor_preview_api")
        def segment_editor_preview_api(payload: dict = Body(...)):
            try:
                project_path, safe_project = _safe_project_path(payload.get("project"))
                if not project_path:
                    return {"success": False, "error": f"Projeto nao encontrado: {safe_project}"}
                segment = int(payload.get("segment", 0))
                kind = str(payload.get("kind") or "subtitle")
                current = segment_editor_state.get_segment_state(project_path, segment, create=True)
                configs = payload.get("configs") if isinstance(payload.get("configs"), dict) else current.get("configs", {})
                configs = segment_editor_state.normalize_configs(project_path, configs)

                try:
                    from scripts.polish_segment_subs import find_segment_json
                    json_path = find_segment_json(project_path, segment)
                except Exception:
                    json_path = None

                preview_path = segment_editor_preview.render_preview(
                    project_path,
                    segment,
                    kind,
                    configs,
                    video_path=_base_video_for_segment(project_path, segment),
                    json_path=json_path,
                )
                preview_url = _video_url_for_path(preview_path)
                if not preview_url:
                    return {"success": False, "error": "Preview gerado fora da pasta VIRALS."}
                labels = {
                    "subtitle": "Preview da legenda atualizado.",
                    "watermark": "Preview da marca d'agua atualizado.",
                    "outro": "Preview do Outro atualizado.",
                }
                return {
                    "success": True,
                    "project": safe_project,
                    "segment": segment,
                    "kind": kind,
                    "preview_url": preview_url,
                    "message": labels.get(kind, "Preview atualizado."),
                }
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        @fastapi_app.post("/segment_editor_render_api")
        def segment_editor_render_api(payload: dict = Body(...)):
            try:
                project_path, safe_project = _safe_project_path(payload.get("project"))
                if not project_path:
                    return {"success": False, "error": f"Projeto nÃ£o encontrado: {safe_project}"}
                segment = int(payload.get("segment", 0))
                current = segment_editor_state.get_segment_state(project_path, segment, create=True)
                configs = payload.get("configs") if isinstance(payload.get("configs"), dict) else current.get("configs", {})
                features = segment_editor_state.features_from_configs(configs)
                state = segment_editor_state.update_segment_state(project_path, segment, configs=configs, features=features)

                from scripts.polish_segment_subs import find_segment_json
                json_path = find_segment_json(project_path, segment)
                if not json_path:
                    return {"success": False, "error": f"Sem JSON de legenda para o segmento {segment}."}

                from subtitle_editor import render_specific_video
                msg = render_specific_video(json_path, feature_overrides=features, config_overrides=state.get("configs", {}))
                if not (isinstance(msg, str) and msg.strip().lower().startswith("success")):
                    return {"success": False, "error": msg or "Falha ao renderizar."}

                applied_features = render_state.get_segment_features(project_path, segment)
                state = segment_editor_state.update_segment_state(project_path, segment, configs=state.get("configs", {}), features=applied_features)
                return {
                    **_segment_editor_payload(project_path, safe_project, segment, state, json_path),
                    "message": msg,
                    "features": applied_features,
                }
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        @fastapi_app.post("/segment_editor_upload_asset_api")
        async def segment_editor_upload_asset_api(
            project: str = Form(...),
            segment: int = Form(...),
            config_key: str = Form(...),
            field: str = Form(...),
            file: UploadFile = File(...),
        ):
            try:
                project_path, safe_project = _safe_project_path(project)
                if not project_path:
                    return {"success": False, "error": f"Projeto nÃ£o encontrado: {safe_project}"}
                if config_key not in {"watermark", "audio", "outro"}:
                    return {"success": False, "error": f"Config invÃ¡lida: {config_key}"}

                category = _asset_category_for_field(field)
                target_dir = os.path.join(WEBUI_ASSETS_DIR, category)
                os.makedirs(target_dir, exist_ok=True)
                target_name = _safe_uploaded_name(file.filename)
                target_path = os.path.join(target_dir, target_name)
                content = await file.read()
                if not content:
                    return {"success": False, "error": "Arquivo vazio."}
                with open(target_path, "wb") as f:
                    f.write(content)

                rel_path = os.path.relpath(target_path, WORKING_DIR).replace("\\", "/")
                current = segment_editor_state.get_segment_state(project_path, int(segment), create=True)
                configs = current.get("configs", {})
                cfg = configs.get(config_key) if isinstance(configs.get(config_key), dict) else {}
                cfg = copy.deepcopy(cfg)
                _set_nested_value(cfg, field, rel_path)
                configs[config_key] = cfg
                features = segment_editor_state.features_from_configs(configs)
                state = segment_editor_state.update_segment_state(project_path, int(segment), configs=configs, features=features)
                return {
                    **_segment_editor_payload(project_path, safe_project, int(segment), state),
                    "path": rel_path,
                    "config_key": config_key,
                    "field": field,
                }
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        def _polish_and_rerender(project_folder, json_path):
            """Polish one subtitle JSON and re-burn the corresponding video.
            Returns a dict with success/error."""
            from scripts.polish_segment_subs import polish_json_file
            api_key, model_name = _load_gemini_config()
            if not api_key:
                return {"success": False, "error": "Gemini API key not configured in api_config.json."}

            polish_result = polish_json_file(json_path, api_key, model_name=model_name)
            if not polish_result.get("success"):
                return {"success": False, "error": polish_result.get("error") or "Polish failed."}

            # Re-render the subtitled video so the burned legend reflects the fix.
            try:
                from subtitle_editor import render_specific_video
                render_msg = render_specific_video(json_path)
                if isinstance(render_msg, str) and render_msg.strip().lower().startswith("success"):
                    seg_index = _segment_index_from_json(json_path)
                    if seg_index is not None:
                        features = render_state.get_segment_features(project_folder, seg_index)
                        state = segment_editor_state.default_segment_state(project_folder, seg_index)
                        segment_editor_state.update_segment_state(
                            project_folder,
                            seg_index,
                            configs=state.get("configs", {}),
                            features=features,
                        )
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Polished JSON but failed to re-render video: {e}",
                    "applied": polish_result.get("applied"),
                    "total": polish_result.get("total"),
                }

            rendered_video = _rendered_video_for_json(project_folder, json_path)
            return {
                "success": True,
                "applied": polish_result.get("applied"),
                "total": polish_result.get("total"),
                "render": render_msg,
                "segment": _segment_index_from_json(json_path),
                **_video_payload(rendered_video),
            }

        @fastapi_app.get("/polish_segment_api")
        def polish_segment_api(project: str, segment: int):
            try:
                safe_project = os.path.basename(project)
                project_path = os.path.join(VIRALS_DIR, safe_project)
                if not os.path.exists(project_path):
                    return {"success": False, "error": f"Project not found: {safe_project}"}

                from scripts.polish_segment_subs import find_segment_json
                json_path = find_segment_json(project_path, segment)
                if not json_path:
                    return {"success": False, "error": f"No subtitle JSON for segment {segment}."}

                return _polish_and_rerender(project_path, json_path)
            except Exception as e:
                return {"success": False, "error": str(e)}

        @fastapi_app.get("/polish_all_segments_api")
        def polish_all_segments_api(project: str):
            try:
                safe_project = os.path.basename(project)
                project_path = os.path.join(VIRALS_DIR, safe_project)
                if not os.path.exists(project_path):
                    return {"success": False, "error": f"Project not found: {safe_project}"}

                from scripts.polish_segment_subs import list_segment_jsons
                json_paths = list_segment_jsons(project_path)
                if not json_paths:
                    return {"success": False, "error": "No subtitle JSONs found."}

                results = []
                for jp in json_paths:
                    r = _polish_and_rerender(project_path, jp)
                    results.append({
                        "file": os.path.basename(jp),
                        "success": r.get("success", False),
                        "error": r.get("error"),
                        "applied": r.get("applied"),
                        "total": r.get("total"),
                        "segment": r.get("segment"),
                        "video_url": r.get("video_url"),
                        "download_name": r.get("download_name"),
                    })
                ok = sum(1 for r in results if r["success"])
                return {
                    "success": ok > 0,
                    "polished": ok,
                    "total": len(results),
                    "results": results,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        def _recut_segment_buffer(project_path, segment, buffer_start, buffer_end):
            """Re-cut one segment from input.mp4 with signed start/end margin
            adjustments, re-crop it to 9:16 in final/, re-cut the subtitle JSON and
            persist the new times + margin to viral_segments.txt. Does NOT burn
            subtitles or touch the per-segment editor state -- callers render
            afterwards so they choose which configs to apply. Returns a dict with
            the paths/times or {"success": False, "error": ...}."""
            import subprocess as sp

            adjust_limit = 600
            buffer_start = max(-adjust_limit, min(adjust_limit, int(buffer_start)))
            buffer_end = max(-adjust_limit, min(adjust_limit, int(buffer_end)))

            # 1. Load viral_segments.txt
            json_path = os.path.join(project_path, "viral_segments.txt")
            if not os.path.exists(json_path):
                return {"success": False, "error": "viral_segments.txt not found."}

            with open(json_path, "r", encoding="utf-8") as f:
                segments_data = json.load(f)

            segments_list = segments_data.get("segments", [])
            if segment < 0 or segment >= len(segments_list):
                return {"success": False, "error": f"Segment index {segment} out of range (0-{len(segments_list)-1})."}

            seg = segments_list[segment]

            # Require original timestamps
            original_start = seg.get("original_start_time")
            original_end = seg.get("original_end_time")
            if original_start is None or original_end is None:
                return {"success": False, "error": "Segment missing original_start_time/original_end_time. Re-process the project first."}
            try:
                original_start = float(original_start)
                original_end = float(original_end)
            except (TypeError, ValueError):
                return {"success": False, "error": "Invalid original_start_time/original_end_time values."}

            # Calculate new buffered times (independent start/end)
            new_start = max(0, original_start - buffer_start)
            new_end = original_end + buffer_end
            new_duration = new_end - new_start
            if new_duration <= 0.05:
                return {"success": False, "error": "Ajuste inválido: o corte ficaria sem duração."}

            # 2. Re-cut the raw video from input.mp4
            input_video = os.path.join(project_path, "input.mp4")
            if not os.path.exists(input_video):
                input_video_legacy = os.path.join(project_path, "input_video.mp4")
                if os.path.exists(input_video_legacy):
                    input_video = input_video_legacy
                else:
                    return {"success": False, "error": "input.mp4 not found in project folder."}

            # Determine filenames (same logic as cut_segments.py)
            title = seg.get("title", f"Segment_{segment}")
            safe_title = "".join([c for c in title if c.isalnum() or c in " _-"]).strip()
            safe_title = safe_title.replace(" ", "_")[:60]
            base_name = f"{segment:03d}_{safe_title}"

            cuts_folder = os.path.join(project_path, "cuts")
            os.makedirs(cuts_folder, exist_ok=True)
            output_video = os.path.join(cuts_folder, f"{base_name}_original_scale.mp4")

            # Check NVENC
            try:
                enc_result = sp.run(["ffmpeg", "-encoders"], capture_output=True, text=True)
                video_codec = "h264_nvenc" if "h264_nvenc" in enc_result.stdout else "libx264"
            except Exception:
                video_codec = "libx264"

            # Read outro pad duration
            outro_config_path = os.path.join(WORKING_DIR, "outro_config.json")
            pad_duration = 0.0
            if os.path.exists(outro_config_path):
                try:
                    with open(outro_config_path, "r", encoding="utf-8") as f:
                        outro_cfg = json.load(f)
                    if outro_cfg.get("enabled", False):
                        pad_duration = float(outro_cfg.get("fade_duration", 0.0))
                except Exception:
                    pass

            video_duration = max(0.05, new_duration + pad_duration)

            cmd = [
                "ffmpeg", "-y",
                "-loglevel", "error", "-hide_banner",
                "-ss", f"{new_start:.3f}",
                "-i", input_video,
                "-t", f"{video_duration:.3f}",
                "-c:v", video_codec
            ]
            if video_codec == "h264_nvenc":
                cmd.extend(["-preset", "p1", "-b:v", "5M"])
            else:
                cmd.extend(["-preset", "ultrafast", "-crf", "23"])
            cmd.extend(["-c:a", "aac", "-b:a", "128k", output_video])

            result = sp.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                return {"success": False, "error": f"ffmpeg re-cut failed: {result.stderr or result.stdout}"}

            # 2b. Re-cropar ESTE segmento para o 9:16 vertical em final/ usando os
            # novos pontos de corte. Sem isso, render_specific_video acharia o crop
            # ANTIGO em final/ e o vídeo renderizado não mudaria de verdade.
            try:
                from scripts import edit_video
                final_folder = os.path.join(project_path, "final")
                os.makedirs(final_folder, exist_ok=True)
                temp_no_audio = os.path.join(final_folder, f"temp_video_no_audio_{segment}.mp4")
                edit_video.generate_short_fallback(
                    output_video, temp_no_audio, segment, project_path, final_folder, no_face_mode="zoom"
                )
                generated_final = os.path.join(final_folder, f"final-output{segment:03d}_processed.mp4")
                final_target = os.path.join(final_folder, f"{base_name}.mp4")
                if os.path.exists(generated_final):
                    if os.path.exists(final_target):
                        os.remove(final_target)
                    os.rename(generated_final, final_target)
                else:
                    return {"success": False, "error": f"Re-crop did not generate {os.path.basename(generated_final)}."}
            except Exception as crop_err:
                return {"success": False, "error": f"Re-crop failed: {crop_err}"}

            # 3. Re-cut subtitle JSON
            input_json_path = os.path.join(project_path, "input.json")
            subs_folder = os.path.join(project_path, "subs")
            os.makedirs(subs_folder, exist_ok=True)
            json_output_path = os.path.join(subs_folder, f"{base_name}_processed.json")

            if os.path.exists(input_json_path):
                from scripts.cut_json import cut_json_transcript
                cut_json_transcript(input_json_path, json_output_path, new_start, new_end)

            # 4. Persist the new cut points + margin to viral_segments.txt
            seg["start_time"] = new_start
            seg["end_time"] = new_end
            seg["duration"] = new_duration
            seg["buffer_start_used"] = buffer_start
            seg["buffer_end_used"] = buffer_end

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(segments_data, f, ensure_ascii=False, indent=2)

            return {
                "success": True,
                "json_output_path": json_output_path,
                "final_target": final_target,
                "output_video": output_video,
                "new_start": new_start,
                "new_end": new_end,
                "new_duration": new_duration,
                "buffer_start_used": buffer_start,
                "buffer_end_used": buffer_end,
            }

        @fastapi_app.get("/adjust_buffer_api")
        def adjust_buffer_api(project: str, segment: int, buffer_start: int, buffer_end: int):
            """Re-cut a segment with signed start/end adjustments (library card)."""
            try:
                safe_project = os.path.basename(project)
                project_path = os.path.join(VIRALS_DIR, safe_project)
                if not os.path.exists(project_path):
                    return {"success": False, "error": f"Project not found: {safe_project}"}

                recut = _recut_segment_buffer(project_path, int(segment), buffer_start, buffer_end)
                if not recut.get("success"):
                    return recut

                json_output_path = recut["json_output_path"]
                # Re-render burned subtitles (includes watermark, outro, audio)
                if os.path.exists(json_output_path):
                    try:
                        from subtitle_editor import render_specific_video
                        render_msg = render_specific_video(json_output_path)
                        print(f"[BUFFER] Re-render result: {render_msg}")
                    except Exception as render_err:
                        return {"success": False, "error": f"Re-render failed: {render_err}"}
                    if not (isinstance(render_msg, str) and render_msg.strip().lower().startswith("success")):
                        return {"success": False, "error": render_msg or "Re-render failed."}
                    try:
                        features = render_state.get_segment_features(project_path, int(segment))
                        state = segment_editor_state.default_segment_state(project_path, int(segment))
                        segment_editor_state.update_segment_state(
                            project_path,
                            int(segment),
                            configs=state.get("configs", {}),
                            features=features,
                        )
                    except Exception as editor_state_err:
                        print(f"[segment_editor_state] nao foi possivel sincronizar estado do buffer: {editor_state_err}")

                rendered_video = _rendered_video_for_json(project_path, json_output_path)
                if not rendered_video:
                    final_target = recut.get("final_target")
                    rendered_video = final_target if final_target and os.path.exists(final_target) else recut["output_video"]

                return {
                    "success": True,
                    "message": f"Buffer adjusted: start={recut['buffer_start_used']}s, end={recut['buffer_end_used']}s",
                    "new_start": round(recut["new_start"], 3),
                    "new_end": round(recut["new_end"], 3),
                    "new_duration": round(recut["new_duration"], 3),
                    "buffer_start_used": recut["buffer_start_used"],
                    "buffer_end_used": recut["buffer_end_used"],
                    **_video_payload(rendered_video),
                }

            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        @fastapi_app.post("/segment_editor_buffer_api")
        def segment_editor_buffer_api(payload: dict = Body(...)):
            """Re-cut a segment with a new safety margin from the unified editor,
            re-rendering with THIS video's per-segment configs so the editor's
            customizations (subtitle style, watermark, audio, outro) survive the
            re-cut -- unlike the library card, which resets to defaults."""
            try:
                project_path, safe_project = _safe_project_path(payload.get("project"))
                if not project_path:
                    return {"success": False, "error": f"Projeto nao encontrado: {safe_project}"}
                segment = int(payload.get("segment", 0))
                try:
                    buffer_start = int(payload.get("buffer_start", 0) or 0)
                    buffer_end = int(payload.get("buffer_end", 0) or 0)
                except (TypeError, ValueError):
                    return {"success": False, "error": "Margem invalida."}

                current = segment_editor_state.get_segment_state(project_path, segment, create=True)
                configs = payload.get("configs") if isinstance(payload.get("configs"), dict) else current.get("configs", {})
                features = segment_editor_state.features_from_configs(configs)
                state = segment_editor_state.update_segment_state(project_path, segment, configs=configs, features=features)

                recut = _recut_segment_buffer(project_path, segment, buffer_start, buffer_end)
                if not recut.get("success"):
                    return recut

                json_output_path = recut["json_output_path"]
                if not os.path.exists(json_output_path):
                    return {"success": False, "error": f"Sem JSON de legenda para o segmento {segment}."}

                from subtitle_editor import render_specific_video
                msg = render_specific_video(json_output_path, feature_overrides=features, config_overrides=state.get("configs", {}))
                if not (isinstance(msg, str) and msg.strip().lower().startswith("success")):
                    return {"success": False, "error": msg or "Falha ao renderizar."}

                applied_features = render_state.get_segment_features(project_path, segment)
                state = segment_editor_state.update_segment_state(project_path, segment, configs=state.get("configs", {}), features=applied_features)
                return {
                    **_segment_editor_payload(project_path, safe_project, segment, state, json_output_path),
                    "message": msg,
                    "features": applied_features,
                }
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        @fastapi_app.get("/apply_feature_api")
        def apply_feature_api(project: str, segment: int, feature: str, action: str = "apply"):
            """Aplica um recurso desativável (watermark/outro/audio_bgm/outro_music) a UM
            corte, re-renderizando do zero a partir da fonte limpa (reaplica o recurso +
            tudo que estiver ativado, sem empilhar). Reusa render_specific_video, que também
            atualiza o render_state.json do corte (cinza = já aplicado)."""
            try:
                action = (action or "apply").strip().lower()
                if action not in {"apply", "remove"}:
                    return {"success": False, "error": f"Acao invalida: {action}"}

                valid = {"watermark", "outro", "audio_bgm", "outro_music"}
                if feature not in valid:
                    return {"success": False, "error": f"Recurso inválido: {feature}"}

                safe_project = os.path.basename(project)
                project_path = os.path.join(VIRALS_DIR, safe_project)
                if not os.path.exists(project_path):
                    return {"success": False, "error": f"Projeto não encontrado: {safe_project}"}

                # O recurso precisa estar ativado e configurado (ex.: marca d'água com imagem).
                try:
                    import render_state
                except ImportError:
                    from webui import render_state
                if action == "apply":
                    ok, reason = render_state.feature_enabled_and_configured(WORKING_DIR, feature)
                    if not ok:
                        return {"success": False, "error": reason}

                # Localizar o JSON de legenda deste segmento.
                from scripts.polish_segment_subs import find_segment_json
                json_path = find_segment_json(project_path, segment)
                if not json_path:
                    return {"success": False, "error": f"Sem JSON de legenda para o segmento {segment}."}

                current_features = render_state.get_segment_features(project_path, segment)
                enabled_now = render_state.compute_enabled_features(WORKING_DIR)
                target_features = {
                    "subtitles": True,
                    "watermark": bool(current_features.get("watermark", False)),
                    "outro": bool(current_features.get("outro", False)),
                    "audio_bgm": bool(current_features.get("audio_bgm", False)),
                    "outro_music": bool(current_features.get("outro_music", False)),
                    "source_volume": bool(current_features.get("source_volume", False)),
                }

                if action == "apply":
                    target_features[feature] = True
                    if feature == "outro_music":
                        target_features["outro"] = True
                    if feature in {"audio_bgm", "outro_music"} and enabled_now.get("source_volume", False):
                        target_features["source_volume"] = True
                else:
                    target_features[feature] = False
                    if feature == "outro":
                        target_features["outro_music"] = False

                if target_features.get("outro_music", False) and not target_features.get("outro", False):
                    target_features["outro_music"] = False

                for key in ("watermark", "outro", "audio_bgm", "outro_music", "source_volume"):
                    target_features[key] = bool(target_features.get(key, False)) and bool(enabled_now.get(key, False))

                # Re-render do zero com o conjunto desejado para este corte.
                from subtitle_editor import render_specific_video
                msg = render_specific_video(json_path, feature_overrides=target_features)
                if isinstance(msg, str) and msg.strip().lower().startswith("success"):
                    rendered_video = _rendered_video_for_json(project_path, json_path)
                    features = render_state.get_segment_features(project_path, segment)
                    try:
                        state = segment_editor_state.default_segment_state(project_path, segment)
                        segment_editor_state.update_segment_state(
                            project_path,
                            segment,
                            configs=state.get("configs", {}),
                            features=features,
                        )
                    except Exception as editor_state_err:
                        print(f"[segment_editor_state] nao foi possivel sincronizar estado: {editor_state_err}")
                    return {"success": True, "message": msg, "features": features, **_video_payload(rendered_video)}
                return {"success": False, "error": msg or "Falha ao renderizar."}
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        print(f"Mounted /virals to {VIRALS_DIR}")

    # ------------------------------------------------------------------
    # Branching: Colab / Windows / Linux
    # ------------------------------------------------------------------
    if args.colab:
        print("Running in Colab mode. Generating public link with full FastAPI routes...")
        if not os.environ.get("VC_LIBRARY_MAX_CARDS"):
            library.set_gallery_limit(24)

        # Configure queue with moderate parallelism. Lightweight UI callbacks
        # are unqueued; heavy processing jobs still use the queue.
        try:
            demo.queue(default_concurrency_limit=8, max_size=64)
        except TypeError:
            # Older Gradio versions don't accept these kwargs
            demo.queue()

        # Launch with prevent_thread_lock so we can mount our routes
        # ON THE SAME FastAPI app that Gradio created. Both the local
        # URL and the share=True tunnel forward to this app, so the API
        # endpoints become available through the public share link too.
        app, local_url, share_url = demo.launch(
            share=True,
            allowed_paths=allowed_dirs,
            prevent_thread_lock=True,
            ssr_mode=False,
            theme=build_theme(),
            css=css,
            js=_global_js,
            server_name="0.0.0.0",
            server_port=args.server_port,
            show_error=True,
            quiet=False,
        )

        # CRITICAL: attach the same routes that Windows/Linux get.
        # Without this, every button in the Library tab (Apply Audio,
        # Polish Subs, Adjust Buffer, Export XML) returns 404 and the
        # gallery hangs when the user switches to that tab.
        attach_extra_routes(app)
        print("All API routes mounted (apply_feature, polish_segment, adjust_buffer).")
        if share_url:
            print(f"Public URL: {share_url}")

        demo.block_thread()
    elif is_windows:
        print("Running in Windows environment (using Gradio launch for convenience).")
        # Windows: Use demo.launch() for convenience (auto-browser, etc)
        app, local_url, share_url = demo.queue().launch(
            share=False,
            allowed_paths=allowed_dirs,
            inbrowser=not args.no_browser,
            server_name="0.0.0.0",
            server_port=args.server_port,
            prevent_thread_lock=True,
            theme=build_theme(),
            css=css,
            js=_global_js
        )
        attach_extra_routes(app)
        demo.block_thread()
    else:
        print("Running in Linux/Container environment (using Uvicorn for stability).")
        # Linux/HF: Use Uvicorn for explicit loop control
        app = FastAPI()
        attach_extra_routes(app)
        # Disable SSR to prevent Node proxying issues on HF Spaces
        app = gr.mount_gradio_app(
            app,
            demo.queue(),
            path="/",
            allowed_paths=allowed_dirs,
            ssr_mode=False,
            theme=build_theme(),
            css=css,
            js=_global_js,
        )
        uvicorn.run(app, host="0.0.0.0", port=args.server_port)
