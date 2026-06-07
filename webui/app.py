import gradio as gr
import subprocess
import os
import sys
import json
import psutil
import shutil
import datetime
import time
import urllib.parse
from fastapi import FastAPI
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
if not os.path.exists(VIRALS_DIR):
    os.makedirs(VIRALS_DIR, exist_ok=True)
if not os.path.exists(MODELS_DIR):
    os.makedirs(MODELS_DIR, exist_ok=True)

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
    'gemini-3.5-flash',
    'gemini-3-flash-preview'
]

# Subtitle logic moved to subtitle_handler.py


def run_viral_cutter(input_source, project_name, url, video_file, segments, viral, themes, min_duration, max_duration, ai_duration, model, manual_mode, api_key, ai_model_name, chunk_size, workflow,
                     use_custom_subs, font_name, font_size, font_color, highlight_color, outline_color, outline_thickness, shadow_color, shadow_size, is_bold, is_italic, is_uppercase, vertical_pos, margin_h, alignment,
                     h_size, w_block, gap, mode, under, strike, border_s, remove_punc, video_quality, use_youtube_subs):

    global current_process

    # --- SAVE UI STATE ---
    ui_state_to_save = {
        "video_quality": video_quality, "use_youtube_subs": use_youtube_subs,
        "segments": segments, "viral": viral, "themes": themes, "min_duration": min_duration, "max_duration": max_duration, "ai_duration": ai_duration,
        "model": model, "manual_mode": manual_mode, "ai_model_name": ai_model_name, "chunk_size": chunk_size, "workflow": workflow,
        "margin_h": margin_h
    }
    try:
        with open(os.path.join(WORKING_DIR, "ui_settings.json"), "w", encoding="utf-8") as f:
            json.dump(ui_state_to_save, f, indent=4)
    except: pass
    # Persiste a chave de IA (digita 1x e fica salva em api_config.json).
    save_api_key(api_key)
    # ---------------------

    yield "", gr.update(value=i18n("Gerando..."), interactive=False), gr.update(visible=True), None, gr.update(visible=False), None

    cmd = [sys.executable, MAIN_SCRIPT_PATH]
    cmd.extend(["--language", "pt"])
    
    # Input Source Logic
    if input_source == "Existing Project":
        if not project_name:
             yield i18n("Error: No project selected."), gr.update(value=i18n("✨ Gerar meus cortes"), interactive=True), gr.update(visible=False), None, gr.update(visible=False), None
             return
        full_project_path = os.path.join(VIRALS_DIR, project_name)
        cmd.extend(["--project-path", full_project_path])
    elif input_source == "Upload Video":
        if not video_file:
             yield i18n("Error: No video file uploaded."), gr.update(value=i18n("✨ Gerar meus cortes"), interactive=True), gr.update(visible=False), None, gr.update(visible=False), None
             return
        
        # Determine project name from filename
        original_filename = os.path.basename(video_file)
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
        shutil.copy(video_file, target_path)
        
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
    if themes: cmd.extend(["--themes", themes])
    cmd.extend(["--min-duration", str(int(min_duration))])
    cmd.extend(["--max-duration", str(int(max_duration))])
    if ai_duration: cmd.append("--ai-duration")
    cmd.extend(["--model", model])
    if manual_mode: cmd.append("--manual-webui")
    if api_key: cmd.extend(["--api-key", api_key])

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
    
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        current_process = subprocess.Popen(cmd, cwd=WORKING_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True, env=env)
        logs = ""
        project_folder_path = None
        if input_source == "Existing Project" and project_name:
             # If using existing project, we already know the path, but let's see if logs confirm it
             project_folder_path = os.path.join(VIRALS_DIR, project_name)

        last_update_time = time.time()
        
        while True:
            line = current_process.stdout.readline()
            if not line and current_process.poll() is not None:
                break
            
            if line:
                logs += line
                if "Project Folder:" in line:
                    parts = line.split("Project Folder:")
                    if len(parts) > 1: project_folder_path = parts[1].strip()
                
                # Throttle updates to avoid browser freeze (0.2s interval)
                current_time = time.time()
                if current_time - last_update_time > 0.2:
                    yield logs, gr.update(visible=True, interactive=False), gr.update(visible=True), None, gr.update(visible=False), None
                    last_update_time = current_time
        
        # Final yield to ensure all logs are shown
        yield logs, gr.update(visible=True, interactive=False), gr.update(visible=True), None, gr.update(visible=False), None
    except Exception as e:
        logs += f"\nError running process: {str(e)}\n"
        yield logs, gr.update(visible=True, interactive=False), gr.update(visible=True), None, gr.update(), gr.update()
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
            
        yield logs, gr.update(value=i18n("✨ Gerar meus cortes"), interactive=True), gr.update(visible=False), None, gr.update(visible=True), prompt_content
        return

    html_output = ""
    if project_folder_path and os.path.exists(project_folder_path):
        html_output = library.generate_project_gallery(project_folder_path, is_full_path=True)
    else:
        html_output = f"<h3>{i18n('Error: Project folder could not be determined from logs.')}</h3>"
    yield logs, gr.update(value=i18n("✨ Gerar meus cortes"), interactive=True), gr.update(visible=False), html_output, gr.update(visible=False), None

# Tema e estilos da marca (Church Edition) — paleta esmeralda + branco.
import styles
from styles import CSS as css
from theme import build_theme, PALETTE

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
        return (f"<div style='color:{PALETTE['primary_deep']};font-size:0.9rem;font-weight:600;'>"
                f"✅ {i18n('Chave de IA salva — não precisa digitar de novo.')}</div>")
    return (f"<div style='color:{PALETTE['text_muted']};font-size:0.9rem;'>"
            f"{i18n('Nenhuma chave salva ainda.')}</div>")

UI_SETTINGS_PATH = os.path.join(WORKING_DIR, "ui_settings.json")

# Padrão de fábrica das configurações de corte. O botão "Restaurar padrões"
# volta tudo para cá; e o que o usuário muda é salvo ao vivo como novo padrão.
DEFAULT_UI_SETTINGS = {
    "video_quality": "best",
    "use_youtube_subs": False,
    "segments": 12,
    "viral": True,
    "themes": "",
    "min_duration": 60,
    "max_duration": 120,
    "ai_duration": False,
    "model": "large-v3-turbo",
    "manual_mode": False,
    "ai_model_name": GEMINI_MODELS[0],
    "chunk_size": 70000,
    "workflow": "Full",
    "margin_h": 35,
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
                          ai_model_name, chunk_size, workflow, margin_h):
    """Salva ao vivo o que o usuário mudou — vira o novo padrão na próxima abertura."""
    data = {
        "video_quality": video_quality, "use_youtube_subs": use_youtube_subs,
        "segments": segments, "viral": viral, "themes": themes,
        "min_duration": min_duration, "max_duration": max_duration, "ai_duration": ai_duration,
        "model": model, "manual_mode": manual_mode, "ai_model_name": ai_model_name,
        "chunk_size": chunk_size, "workflow": workflow, "margin_h": margin_h,
    }
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
            active.append("💧 " + i18n("Marca d'água"))
    except: pass

    try:
        cfg = audio_handler.load_audio_config()
        if cfg.get("enabled", False):
            active.append("🎵 " + i18n("Áudio BGM"))
        try:
            source_volume = float(cfg.get("source_video_volume", 200.0))
        except (TypeError, ValueError):
            source_volume = 200.0
        if abs(source_volume - 100.0) > 0.001:
            active.append("🔊 " + i18n("Volume Original ({}%)").format(int(round(source_volume))))
    except: pass

    try:
        cfg = outro_handler.load_outro_config()
        if cfg.get("enabled", False):
            active.append("🎬 " + i18n("Outro"))
    except: pass
    
    if active:
        items = ', '.join(active)
        return f"<div style='flex-grow: 1; padding: 8px 15px; background-color: {PALETTE['surface_soft']}; border: 1px solid {PALETTE['border_strong']}; border-radius: 10px; color: {PALETTE['primary_deeper']}; font-size: 0.95em; font-weight: 600; display: flex; align-items: center; justify-content: center;'><b>{i18n('Módulos Ativos')}:</b>&nbsp;{items}</div>"
    else:
        return f"<div style='flex-grow: 1; padding: 8px 15px; background-color: {PALETTE['canvas']}; border: 1px solid {PALETTE['border']}; border-radius: 10px; color: {PALETTE['text_muted']}; font-size: 0.95em; display: flex; align-items: center; justify-content: center;'>{i18n('Nenhum módulo extra ativo para este projeto.')}</div>"

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
                f"<div style='color:{PALETTE['primary_deep']};'>✅ {desc}: <b>{os.path.basename(path)}</b></div>"
            )
        else:
            html_rows.append(
                f"<div style='color:{PALETTE['text_muted']};'>— {desc}: {i18n('nenhum arquivo salvo')}</div>"
            )
    return (
        f"<div style='font-size:0.85em; line-height:1.5; padding:6px 10px; "
        f"background:{PALETTE['surface_soft']}; border:1px solid {PALETTE['border']}; border-radius:10px;'>"
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
    st.textContent = '@keyframes vc-spin{to{transform:rotate(360deg)}}.vc-spin{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border:2px solid rgba(16,185,129,0.25);border-top-color:#10B981;border-radius:50%;animation:vc-spin .8s linear infinite}.vc-ok{color:#10B981!important;transform:scale(1.3);transition:all .3s}.vc-err{color:#E11D48!important;transform:scale(1.3);transition:all .3s}';
    document.head.appendChild(st);
    // Helper: reload the <video> tag in a card so the new burned subtitle is visible.
    function vcReloadVideoInCard(cardEl) {
        if (!cardEl) return;
        const v = cardEl.querySelector('video');
        if (!v) return;
        const srcEl = v.querySelector('source');
        const srcFromSource = srcEl ? (srcEl.getAttribute('src') || srcEl.src || '') : '';
        const baseSrc = (v.currentSrc || srcFromSource || v.getAttribute('src') || '').split('?')[0];
        if (!baseSrc) return;
        const nextSrc = baseSrc + '?t=' + Date.now();
        if (srcEl) {
            srcEl.src = nextSrc;
            v.removeAttribute('src');
        } else {
            v.src = nextSrc;
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
                vcReloadVideoInCard(card);
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
                // Reload every video in the gallery
                document.querySelectorAll('.viral-card').forEach(c => vcReloadVideoInCard(c));
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

        const bufStart = Math.max(0, Math.min(5, parseInt(startInput.value) || 0));
        const bufEnd = Math.max(0, Math.min(5, parseInt(endInput.value) || 0));

        btn._vcL = true;
        const oh = btn.innerHTML;
        btn.innerHTML = '<div class="vc-spin" style="width:16px;height:16px;border-width:2px"></div> Reprocessando...';
        btn.style.pointerEvents = 'none';
        btn.style.opacity = '0.85';
        startInput.disabled = true;
        endInput.disabled = true;
        try {
            const r = await fetch('/adjust_buffer_api?project=' + project + '&segment=' + segment + '&buffer_start=' + bufStart + '&buffer_end=' + bufEnd);
            const d = await r.json();
            if (d.success) {
                btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg> Pronto!';
                btn.classList.add('vc-ok');
                // Reload video
                let card = btn.closest('.viral-card') || btn.parentElement;
                while (card && !card.querySelector('video')) card = card.parentElement;
                vcReloadVideoInCard(card);
                setTimeout(() => { btn.innerHTML = oh; btn.classList.remove('vc-ok'); btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; startInput.disabled = false; endInput.disabled = false; }, 2500);
            } else {
                console.warn('Buffer reprocess failed:', d.error);
                btn.innerHTML = '✗ Falhou';
                btn.classList.add('vc-err');
                btn.title = 'Erro: ' + (d.error || 'falhou');
                setTimeout(() => { btn.innerHTML = oh; btn.classList.remove('vc-err'); btn.title = ''; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; startInput.disabled = false; endInput.disabled = false; }, 3500);
            }
        } catch (err) {
            console.warn('Buffer reprocess error:', err);
            btn.innerHTML = '✗ Erro';
            btn.classList.add('vc-err');
            setTimeout(() => { btn.innerHTML = oh; btn.classList.remove('vc-err'); btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn._vcL = false; startInput.disabled = false; endInput.disabled = false; }, 3500);
        }
    }, true);

    // Aplicar um recurso desativável (marca d'água/outro/áudio/música) a UM corte.
    document.body.addEventListener("click", async (e) => {
        const btn = e.target.closest('.apply-feature-btn');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        if (btn._vcL || btn.classList.contains('applied')) return;
        const feature = btn.getAttribute('data-feature') || '';
        const project = btn.getAttribute('data-project') || '';
        const segment = btn.getAttribute('data-segment') || '';
        const label = btn.getAttribute('data-label') || '';
        if (!feature || !project || segment === '') return;
        btn._vcL = true;
        const oh = btn.innerHTML;
        const origBg = btn.style.background;
        const origTitle = btn.title;
        btn.style.pointerEvents = 'none';
        btn.style.opacity = '0.85';
        btn.innerHTML = '<div class="vc-spin" style="width:15px;height:15px;border-width:2px"></div><span>Aplicando…</span>';
        try {
            const r = await fetch('/apply_feature_api?project=' + project + '&segment=' + encodeURIComponent(segment) + '&feature=' + encodeURIComponent(feature));
            const d = await r.json();
            if (d.success) {
                let card = btn.closest('.viral-card') || btn.parentElement;
                while (card && !card.querySelector('video')) card = card.parentElement;
                vcReloadVideoInCard(card);
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
                btn._vcL = false;
            } else {
                console.warn('Aplicar recurso falhou:', d.error);
                btn.innerHTML = '<span>✗ Erro</span>';
                btn.style.background = '#E11D48';
                btn.style.color = '#fff';
                btn.title = 'Erro: ' + (d.error || 'falhou');
                setTimeout(() => { btn.innerHTML = oh; btn.style.background = origBg; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn.title = origTitle; btn._vcL = false; }, 3500);
            }
        } catch (err) {
            console.warn('Aplicar recurso erro:', err);
            btn.innerHTML = '<span>✗ Erro</span>';
            btn.style.background = '#7f1d1d';
            btn.style.color = '#fff';
            setTimeout(() => { btn.innerHTML = oh; btn.style.background = origBg; btn.style.pointerEvents = ''; btn.style.opacity = '1'; btn.title = origTitle; btn._vcL = false; }, 3500);
        }
    }, true);
})();
"""

# Pergunta de limpeza só na 1ª carga por inicialização do app (não repete a cada refresh).
_startup_cleanup_asked = False

with gr.Blocks(title=i18n("Viral Cutter · Church Edition"), theme=build_theme(), css=css, js=_global_js) as demo:
    gr.HTML(header.header_html)

    # --- Pergunta "limpar arquivos antigos?" ao abrir o app (preenchida em demo.load) ---
    with gr.Group(visible=False) as startup_cleanup_banner:
        gr.Markdown(i18n(
            "## 🧹 Limpar arquivos antigos?\n"
            "Encontrei projetos e temporários de execuções anteriores. Quer apagar agora para "
            "começar limpo? A pasta **Cortes IPB** (seus vídeos finais), seus **assets**, as "
            "**configurações** e a **chave de API** não serão tocados."
        ))
        startup_cleanup_box = gr.Textbox(label=i18n("O que pode ser apagado"), lines=8, interactive=False)
        with gr.Row():
            startup_cleanup_yes = gr.Button(i18n("🗑️ Sim, limpar agora"), variant="stop")
            startup_cleanup_no = gr.Button(i18n("Agora não, manter"), variant="secondary")
        startup_cleanup_status = gr.Markdown("")

    with gr.Tabs():
        with gr.Tab(i18n("🎬 Criar Cortes")) as create_tab:
             with gr.Row():
                with gr.Column(scale=1):
                    gr.HTML(styles.step_badge(1, i18n("Escolha o vídeo")))
                    input_source = gr.Radio([(i18n("📁 Upar vídeo"), "Upload Video"), (i18n("▶️ Link do YouTube"), "YouTube URL"), (i18n("🗂️ Projeto já criado"), "Existing Project")], label=i18n("De onde vem o vídeo?"), value="Upload Video")
                    
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
                    _ai_dur_initial = bool(ui_state.get("ai_duration", False))
                    ai_duration_input = gr.Checkbox(label=i18n("Deixar a IA decidir a duração de cada corte"), value=_ai_dur_initial, info=i18n("Recomendado. Se desligar, você define a duração mínima e máxima abaixo."))
                    with gr.Row():
                        min_dur_input = gr.Number(label=i18n("Duração mínima (segundos)"), value=ui_state.get("min_duration", 60), interactive=not _ai_dur_initial)
                        max_dur_input = gr.Number(label=(i18n("Teto de segurança (s)") if _ai_dur_initial else i18n("Duração máxima (segundos)")), value=ui_state.get("max_duration", 120))
                    def _toggle_ai_duration(ai):
                        # Quando a IA decide: não há mínimo (campo Mín desabilitado);
                        # o campo Máx continua valendo, mas como teto de segurança.
                        return gr.update(interactive=not ai), gr.update(label=(i18n("Teto de segurança (s)") if ai else i18n("Duração máxima (segundos)")))
                    ai_duration_input.change(_toggle_ai_duration, inputs=ai_duration_input, outputs=[min_dur_input, max_dur_input])
                with gr.Column(scale=1):
                    gr.HTML(styles.step_badge(3, i18n("Inteligência Artificial"), i18n("configure uma vez")))
                    gr.HTML(styles.help_banner(i18n("A IA precisa de uma chave gratuita do Google para entender a pregação. Cole sua chave abaixo uma única vez — ela fica salva.")))
                    api_key_input = gr.Textbox(label=i18n("Chave de IA (Google Gemini)"), type="password", placeholder=i18n("Cole aqui a sua chave..."))
                    api_key_status = gr.HTML(api_key_status_html())
                    gr.Markdown(i18n("Não tem uma chave? O passo a passo para conseguir (é grátis) está na aba **Sobre**."))

                    with gr.Accordion(i18n("⚙️ Opções avançadas (não precisa mexer)"), open=False):
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
                         
                         resume_manual_btn = gr.Button(i18n("💾 Salvar JSON e Pular Fase 1 (Retoma edição)"), variant="primary")
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
                                  return ("❌ Não encontrei uma lista 'segments' válida no JSON colado. "
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
                              return (f"✅ {n} segmento(s) salvos em '{proj_name}'.\n"
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
                    preview_vid_btn = gr.Button(i18n("🎬 Render Animated Preview (Slow)"), size="sm")
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
                        vertical_pos_input = gr.Slider(label=i18n("V-Pos (Margin V)"), minimum=0, maximum=500, value=ui_state.get("vertical_pos", 140))
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
                 ai_model_input, chunk_size_input, workflow_input, margin_h_input,
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
                     gr.update(value=d["min_duration"], interactive=not d["ai_duration"]),
                     gr.update(value=d["max_duration"], label=i18n("Duração máxima (segundos)")),
                     gr.update(value=d["ai_duration"]),
                     gr.update(value=d["model"]),
                     gr.update(value=d["manual_mode"]),
                     gr.update(value=d["ai_model_name"]),
                     gr.update(value=d["chunk_size"]),
                     gr.update(value=d["workflow"]),
                     gr.update(value=d["margin_h"]),
                 )

             gr.HTML(styles.step_badge(4, i18n("Gerar")))
             with gr.Row():
                 start_btn = gr.Button(i18n("✨ Gerar meus cortes"), variant="primary", scale=2)
                 stop_btn = gr.Button(i18n("Parar"), variant="stop", visible=False, scale=1)
                 active_modules_info = gr.HTML(scale=3)
             with gr.Row():
                 restore_defaults_btn = gr.Button(i18n("↩️ Restaurar configurações padrão"), variant="secondary", size="sm", scale=1)
             restore_defaults_btn.click(restore_default_settings, outputs=_settings_components, queue=False, show_progress="hidden")
             friendly_status = gr.HTML('<div id="vc_status"></div>')
             with gr.Accordion(i18n("Ver detalhes técnicos"), open=False):
                 logs_output = gr.Textbox(label=i18n("Registro do processamento"), lines=10, autoscroll=True, elem_id="logs_output")
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
                                var t = (ta.value || '').toLowerCase();
                                var stages = [
                                    ['baixando', '⬇️ Baixando o vídeo...'],
                                    ['download', '⬇️ Baixando o vídeo...'],
                                    ['transcre', '📝 Transcrevendo o áudio...'],
                                    ['transcrib', '📝 Transcrevendo o áudio...'],
                                    ['viral', '✨ Encontrando os melhores momentos...'],
                                    ['segmento', '✨ Encontrando os melhores momentos...'],
                                    ['cortando', '✂️ Cortando os vídeos...'],
                                    ['cutting', '✂️ Cortando os vídeos...'],
                                    ['editing', '🎬 Montando os cortes verticais...'],
                                    ['editando', '🎬 Montando os cortes verticais...'],
                                    ['legenda', '💬 Gerando as legendas...'],
                                    ['subtitle', '💬 Gerando as legendas...'],
                                    ['conclu', 'done'],
                                    ['sucesso', 'done'],
                                    ['completed', 'done']
                                ];
                                var stage = null, done = false;
                                for (var i=0;i<stages.length;i++){
                                    if (t.indexOf(stages[i][0])>=0){
                                        if (stages[i][1]==='done'){ done = true; stage = '🎉 Pronto! Seus cortes estão prontos.'; }
                                        else { stage = stages[i][1]; }
                                    }
                                }
                                var err = (t.indexOf('traceback')>=0);
                                if (err) { stage = '⚠️ Algo deu errado — abra "Ver detalhes técnicos" abaixo.'; }
                                if (stage) {
                                    var bg = err ? '#FEF2F2' : '#ECFDF5';
                                    var col = err ? '#E11D48' : '#047857';
                                    var bd = err ? '#FECDD3' : '#D1FAE5';
                                    var spin = (!done && !err) ? '<span class="vc-spin" style="width:16px;height:16px;border-width:2px;margin-right:4px;"></span>' : '';
                                    box.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:12px 16px;border-radius:12px;background:'+bg+';color:'+col+';font-weight:600;border:1px solid '+bd+';">'+spin+'<span>'+stage+'</span></div>';
                                }
                            }
                        } catch(e) {}
                    }
                }
             """)
             
             results_html = gr.HTML(label=i18n("Results"))
             
             

             
             # MUST pass all all new inputs to the run function
             start_btn.click(run_viral_cutter, inputs=[
                 input_source, project_selector, url_input, video_upload, segments_input, viral_input, themes_input, min_dur_input, max_dur_input, ai_duration_input,
                 model_input, manual_mode_input, api_key_input, ai_model_input, chunk_size_input, workflow_input,
                 use_custom_subs,
                 # Subtitle styling inputs
                 font_name_input, font_size_input, font_color_input, highlight_color_input,
                 outline_color_input, outline_thickness_input, shadow_color_input, shadow_size_input,
                 bold_input, italic_input, uppercase_input, vertical_pos_input, margin_h_input, alignment_input,
                 highlight_size_input, words_per_block_input, gap_limit_input, mode_input,
                 underline_input, strikeout_input, border_style_input, remove_punc_input,
                 video_quality_input, use_youtube_subs_input
             ], outputs=[logs_output, start_btn, stop_btn, results_html, manual_review_group, manual_review_prompt])


        with gr.Tab(i18n("🎨 Identidade da Igreja")):
            gr.HTML(styles.help_banner(i18n("Configure a identidade visual e sonora da sua igreja uma única vez. Tudo isso é aplicado automaticamente nos seus cortes.")))
            with gr.Tabs():
                with gr.Tab(i18n("💧 Logo / Marca d'água")) as watermark_tab:
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
                    
                            watermark_save_btn = gr.Button(i18n("💾 Salvar Marca d'água"), variant="primary")
                            watermark_status_txt = gr.Textbox(label=i18n("Status"), interactive=False)
                            watermark_refresh_preview_btn = gr.Button(i18n("🔄 Atualizar Preview Manualmente"))

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

                with gr.Tab(i18n("🎵 Trilha sonora")) as audio_tab:
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
                            audio_stop_before_outro_input = gr.Checkbox(label=i18n("💥 Parar Áudio BGM antes do Encerramento / Outro começar"), value=audio_cfg.get("stop_before_outro", True), info="Use se o seu Outro já possuir música própria.")
                            audio_use_ending_volume_input = gr.Checkbox(label=i18n("Ativar Variação de Volume no Final"), value=audio_cfg.get("use_ending_volume", True))
                            audio_sync_outro_input = gr.Checkbox(label=i18n("Sincronizar tempo de Volume automaticamente com o Encerramento / Outro"), value=audio_cfg.get("sync_with_outro", True))
                            audio_ending_volume_input = gr.Slider(label=i18n("Volume Secundário / Final (%)"), minimum=0, maximum=100, value=audio_cfg.get("ending_volume", 20), step=1)
                    
                            audio_ending_start_time_input = gr.Slider(label=i18n("Iniciar quantos segundos antes de acabar? (Ignorado se 'Sincronizar' estiver ativo)"), minimum=0, maximum=60, value=audio_cfg.get("ending_start_time", 10), step=1, visible=not audio_cfg.get("sync_with_outro", True))
                            audio_crossfade_input = gr.Slider(label=i18n("Suavização da Variação (s) (Ignorado se 'Sincronizar' estiver ativo)"), minimum=0.0, maximum=10.0, value=audio_cfg.get("crossfade_duration", 3.0), step=0.5, visible=not audio_cfg.get("sync_with_outro", True))

                    gr.Markdown("---")
                    gr.Markdown("### 🎵 " + i18n("Música de Encerramento (Outro Music)"))
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
                        audio_save_btn = gr.Button(i18n("💾 Salvar Configurações de Áudio"), variant="primary")
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


                with gr.Tab(i18n("🔊 Volume do vídeo")) as original_volume_tab:
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
                            source_volume_save_btn = gr.Button(i18n("💾 Salvar Volume Original"), variant="primary")
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

                with gr.Tab(i18n("🎬 Encerramento")) as outro_tab:
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
                                label=i18n("🔊 Volume do Vídeo de Encerramento (%)"),
                                minimum=0, maximum=200, value=outro_cfg.get("outro_volume", 100), step=5,
                                info=i18n("Só tem efeito quando o vídeo de Outro possui áudio próprio. 100% = volume original, 0% = mudo.")
                            )

                            gr.Markdown(f"#### {i18n('Posição e Escala da Imagem')}")
                            outro_x_input = gr.Slider(label=i18n("Posição X"), minimum=-1080, maximum=1080, value=outro_cfg.get("position_x", 179), step=1)
                            outro_y_input = gr.Slider(label=i18n("Posição Y"), minimum=-1920, maximum=1920, value=outro_cfg.get("position_y", 886), step=1)
                            outro_scale_input = gr.Slider(label=i18n("Escala (%)"), minimum=1, maximum=500, value=outro_cfg.get("scale", 42), step=1)
                            outro_rounded_corners_input = gr.Slider(label=i18n("Bordas Arredondadas (%)"), minimum=0, maximum=50, value=outro_cfg.get("rounded_corners", 10), step=1)
                    
                            outro_save_btn = gr.Button(i18n("💾 Salvar Configurações"), variant="primary")
                            outro_status_txt = gr.Textbox(label=i18n("Status"), interactive=False)
                            outro_refresh_preview_btn = gr.Button(i18n("🔄 Atualizar Preview Manualmente"))

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

        with gr.Tab(i18n("✏️ Ajustar Legendas")) as subtitle_editor_tab:
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
                editor_save_btn = gr.Button(i18n("💾 Save Changes"), variant="primary")
                editor_render_single_btn = gr.Button(i18n("⚡ Render This Segment (Very-Fast)"), variant="secondary")
                editor_render_all_btn = gr.Button(i18n("🎬 Render All (Fast)"), variant="stop")
            
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
                    subprocess.Popen(cmd, cwd=WORKING_DIR)
                    return i18n("Render All started in background... Check terminal/logs.")
                except Exception as e:
                    return i18n("Error starting render: {}").format(e)

            editor_render_all_btn.click(
                render_all, 
                inputs=[editor_project_dropdown, use_custom_subs] + manual_inputs, 
                outputs=editor_status
            )


        with gr.Tab(i18n("📁 Meus Vídeos")) as library_tab:
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

            with gr.Accordion(i18n("🧹 Limpar Lixo (arquivos gerados)"), open=False):
                gr.Markdown(i18n(
                    "Apaga **todos os projetos em VIRALS**, vídeos de teste, temporários e previews. "
                    "**NÃO** apaga a pasta 'Cortes IPB' (seus vídeos finais), os assets enviados "
                    "(outro/logo/música), as configurações nem a chave de API.\n\n"
                    "**Passo 1:** clique em *Analisar* para ver o que será apagado. "
                    "**Passo 2:** confirme em *Apagar tudo*."
                ))
                cleanup_preview_box = gr.Textbox(label=i18n("Prévia (o que será apagado)"), lines=10, interactive=False)
                with gr.Row():
                    cleanup_scan_btn = gr.Button(i18n("🔎 Analisar"))
                    cleanup_confirm_btn = gr.Button(i18n("🗑️ Apagar tudo"), variant="stop", visible=False)
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

        with gr.Tab(i18n("❓ Sobre / Ajuda")) as about_tab:
            gr.HTML(header.about_html)

        demo.load(get_active_modules_html, inputs=[], outputs=active_modules_info, queue=False, show_progress="hidden")

        # Ao abrir o app: pergunta (1x por inicialização) se quer limpar arquivos antigos.
        def _startup_cleanup_check():
            global _startup_cleanup_asked
            if _startup_cleanup_asked:
                return gr.update(visible=False), ""
            _startup_cleanup_asked = True
            text, targets = library.preview_garbage()
            return gr.update(visible=bool(targets)), (text if targets else "")
        demo.load(_startup_cleanup_check, outputs=[startup_cleanup_banner, startup_cleanup_box], queue=False, show_progress="hidden")

        def _startup_clean_yes():
            return library.clean_garbage(), gr.update(visible=False)
        startup_cleanup_yes.click(
            _startup_clean_yes, outputs=[startup_cleanup_status, startup_cleanup_banner]
        ).then(library.refresh_projects, outputs=project_dropdown, queue=False, show_progress="hidden")

        startup_cleanup_no.click(lambda: gr.update(visible=False), outputs=startup_cleanup_banner, queue=False)
    
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
                return gem.get("api_key") or None, gem.get("model") or "gemini-3.5-flash"
            except Exception:
                return None, None

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
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Polished JSON but failed to re-render video: {e}",
                    "applied": polish_result.get("applied"),
                    "total": polish_result.get("total"),
                }

            return {
                "success": True,
                "applied": polish_result.get("applied"),
                "total": polish_result.get("total"),
                "render": render_msg,
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

        @fastapi_app.get("/adjust_buffer_api")
        def adjust_buffer_api(project: str, segment: int, buffer_start: int, buffer_end: int):
            """Re-cut a segment with independent start/end buffer margins (0–5 seconds each)."""
            try:
                import subprocess as sp

                # Validate buffer ranges
                buffer_start = max(0, min(5, buffer_start))
                buffer_end = max(0, min(5, buffer_end))

                safe_project = os.path.basename(project)
                project_path = os.path.join(VIRALS_DIR, safe_project)
                if not os.path.exists(project_path):
                    return {"success": False, "error": f"Project not found: {safe_project}"}

                # 1. Load and update viral_segments.txt
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

                # Calculate new buffered times (independent start/end)
                new_start = max(0, original_start - buffer_start)
                new_end = original_end + buffer_end
                new_duration = new_end - new_start

                # Update segment in JSON
                seg["start_time"] = new_start
                seg["end_time"] = new_end
                seg["duration"] = new_duration
                seg["buffer_start_used"] = buffer_start
                seg["buffer_end_used"] = buffer_end

                # Save updated JSON
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(segments_data, f, ensure_ascii=False, indent=2)

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
                        print(f"[BUFFER] Re-crop não gerou {generated_final}; render pode usar fonte antiga.")
                except Exception as crop_err:
                    print(f"[BUFFER] Re-crop falhou (non-fatal): {crop_err}")

                # 3. Re-cut subtitle JSON
                input_json_path = os.path.join(project_path, "input.json")
                subs_folder = os.path.join(project_path, "subs")
                os.makedirs(subs_folder, exist_ok=True)
                json_output_path = os.path.join(subs_folder, f"{base_name}_processed.json")

                if os.path.exists(input_json_path):
                    from scripts.cut_json import cut_json_transcript
                    cut_json_transcript(input_json_path, json_output_path, new_start, new_end)

                # 4. Re-render burned subtitles (includes watermark, outro, audio)
                if os.path.exists(json_output_path):
                    try:
                        from subtitle_editor import render_specific_video
                        render_msg = render_specific_video(json_output_path)
                        print(f"[BUFFER] Re-render result: {render_msg}")
                    except Exception as render_err:
                        print(f"[BUFFER] Re-render failed (non-fatal): {render_err}")
                        # Non-fatal: raw video was already re-cut

                return {
                    "success": True,
                    "message": f"Buffer adjusted: start={buffer_start}s, end={buffer_end}s",
                    "new_start": round(new_start, 3),
                    "new_end": round(new_end, 3),
                    "new_duration": round(new_duration, 3)
                }

            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "error": str(e)}

        @fastapi_app.get("/apply_feature_api")
        def apply_feature_api(project: str, segment: int, feature: str):
            """Aplica um recurso desativável (watermark/outro/audio_bgm/outro_music) a UM
            corte, re-renderizando do zero a partir da fonte limpa (reaplica o recurso +
            tudo que estiver ativado, sem empilhar). Reusa render_specific_video, que também
            atualiza o render_state.json do corte (cinza = já aplicado)."""
            try:
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
                ok, reason = render_state.feature_enabled_and_configured(WORKING_DIR, feature)
                if not ok:
                    return {"success": False, "error": reason}

                # Localizar o JSON de legenda deste segmento.
                from scripts.polish_segment_subs import find_segment_json
                json_path = find_segment_json(project_path, segment)
                if not json_path:
                    return {"success": False, "error": f"Sem JSON de legenda para o segmento {segment}."}

                # Re-render do zero (aplica o recurso + tudo ativado e grava o estado).
                from subtitle_editor import render_specific_video
                msg = render_specific_video(json_path)
                if isinstance(msg, str) and msg.strip().lower().startswith("success"):
                    return {"success": True, "message": msg}
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
        print(f"✅ All API routes mounted (apply_feature, polish_segment, adjust_buffer).")
        if share_url:
            print(f"🌐 Public URL: {share_url}")

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
            prevent_thread_lock=True
        )
        attach_extra_routes(app)
        demo.block_thread()
    else:
        print("Running in Linux/Container environment (using Uvicorn for stability).")
        # Linux/HF: Use Uvicorn for explicit loop control
        app = FastAPI()
        attach_extra_routes(app)
        # Disable SSR to prevent Node proxying issues on HF Spaces
        app = gr.mount_gradio_app(app, demo.queue(), path="/", allowed_paths=allowed_dirs, ssr_mode=False)
        uvicorn.run(app, host="0.0.0.0", port=args.server_port)
