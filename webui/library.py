import os
import shutil
import json
import urllib.parse
import html
import gradio as gr
try:
    from media_utils import build_file_url, build_file_url_candidates
except ImportError:
    from webui.media_utils import build_file_url, build_file_url_candidates
try:
    import render_state
except ImportError:
    from webui import render_state
try:
    from theme import PALETTE
except ImportError:
    from webui.theme import PALETTE
try:
    from icons import icon
except ImportError:
    from webui.icons import icon

# Setup Virals Dir relative to this file
# This file is in webui/library.py
# VIRALS dir is in ../VIRALS (root of project)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.append(BASE_DIR)
from i18n.i18n import I18nAuto
i18n = I18nAuto(language="pt_BR")

VIRALS_DIR = os.path.join(BASE_DIR, "VIRALS")

# No Colab a pasta "Cortes IPB" (vídeos finais) fica DENTRO de VIRALS (no Drive).
# Ela nunca deve aparecer como "projeto" nem entrar na limpeza.
from scripts.export_paths import CORTES_IPB_NAME, is_colab

PROTECTED_VIRALS_NAMES = {CORTES_IPB_NAME, "_configuracoes", "_webui_assets"}


# URL Mode: "fastapi" (default) or "gradio"
URL_MODE = "fastapi"
GALLERY_MAX_CARDS = None
PYCACHE_CLEANUP_THRESHOLD_BYTES = 256 * 1024 * 1024


def _video_notice_html(message):
    return (
        '<div style="position:absolute; top:0; left:0; width:100%; height:100%; '
        'display:flex; flex-direction:column; align-items:center; justify-content:center; '
        'gap:8px; background:var(--vc-surface-soft); color:var(--vc-text-muted); '
        'text-align:center; padding:18px;">'
        f'{icon("alert-triangle", 26)}<span>{message}</span></div>'
    )

def set_url_mode(mode):
    global URL_MODE
    URL_MODE = mode

def set_gallery_limit(limit):
    global GALLERY_MAX_CARDS
    try:
        parsed = int(limit) if limit not in (None, "", "None", "none") else None
    except (TypeError, ValueError):
        parsed = None
    GALLERY_MAX_CARDS = parsed if parsed and parsed > 0 else None

def get_existing_projects():
    if not os.path.exists(VIRALS_DIR):
        return []
    try:
        projects = []
        with os.scandir(VIRALS_DIR) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=True):
                    continue
                if entry.name in PROTECTED_VIRALS_NAMES:
                    continue
                try:
                    modified = entry.stat(follow_symlinks=True).st_mtime
                except OSError:
                    modified = 0
                projects.append((entry.name, modified))
        projects.sort(key=lambda item: item[1], reverse=True)
        return [name for name, _ in projects]
    except:
        return []

def refresh_projects():
    projs = get_existing_projects()
    return gr.update(choices=projs, value=None)


def _safe_segment_base_name(index, seg):
    title = seg.get("title", f"{i18n('Segment')} {index + 1}")
    safe_title = "".join([c for c in title if c.isalnum() or c in " _-"]).strip()
    safe_title = safe_title.replace(" ", "_")[:60]
    return f"{index:03d}_{safe_title}" if safe_title else f"{index:03d}_Segment_{index}"


def _newest_existing(paths):
    existing = [p for p in paths if p and os.path.exists(p)]
    if not existing:
        return None
    try:
        return max(existing, key=lambda p: os.path.getmtime(p))
    except OSError:
        return existing[0]


def _find_segment_video(project_folder_path, index, seg):
    idx_str = f"{index:03d}"
    base_name = _safe_segment_base_name(index, seg)

    raw_path = seg.get("filepath", None)
    if raw_path:
        candidates = [raw_path]
        if not os.path.isabs(raw_path):
            candidates.append(os.path.join(project_folder_path, raw_path))
        found = _newest_existing(candidates)
        if found:
            return found

    if isinstance(seg.get("filename"), str):
        found = _newest_existing([
            os.path.join(project_folder_path, "burned_sub", seg["filename"]),
            os.path.join(project_folder_path, seg["filename"]),
        ])
        if found:
            return found

    search_groups = [
        [
            os.path.join(project_folder_path, "burned_sub", f"{base_name}_processed_subtitled.mp4"),
            os.path.join(project_folder_path, "burned_sub", f"{base_name}_subtitled.mp4"),
            os.path.join(project_folder_path, "burned_sub", f"final-output{idx_str}_processed_subtitled.mp4"),
            os.path.join(project_folder_path, "burned_sub", f"output{idx_str}.mp4"),
        ],
        [
            os.path.join(project_folder_path, "final", f"{base_name}.mp4"),
            os.path.join(project_folder_path, "final", f"final-output{idx_str}_processed.mp4"),
            os.path.join(project_folder_path, f"final-output{idx_str}_processed.mp4"),
        ],
        [
            os.path.join(project_folder_path, "cuts", f"{base_name}_original_scale.mp4"),
            os.path.join(project_folder_path, f"output{idx_str}_original_scale.mp4"),
            os.path.join(project_folder_path, f"output{idx_str}.mp4"),
            os.path.join(project_folder_path, "cuts", f"output{idx_str}_original_scale.mp4"),
            os.path.join(project_folder_path, "cuts", f"segment_{idx_str}.mp4"),
            os.path.join(project_folder_path, "cuts", f"{idx_str}.mp4"),
        ],
    ]
    for candidates in search_groups:
        found = _newest_existing(candidates)
        if found:
            return found

    for folder_name in ("burned_sub", "final", "cuts"):
        folder = os.path.join(project_folder_path, folder_name)
        if not os.path.isdir(folder):
            continue
        candidates = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.endswith(".mp4") and (f.startswith(f"{idx_str}_") or f"output{idx_str}" in f)
        ]
        found = _newest_existing(candidates)
        if found:
            return found

    return None


# ---------------------------------------------------------------------------
# Limpeza de "lixo" (arquivos gerados). Apaga SOMENTE o lixo óbvio e nunca
# toca em: a pasta "Cortes IPB" (fica fora do projeto, no Desktop), no código,
# .venv, models, WEBUI_ASSETS (assets enviados), *_config.json, ui_settings.json,
# api_config.json, nem no backup VC-ChurchEdition.
# ---------------------------------------------------------------------------
def _human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024

def _path_size(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total

def _is_safe_to_delete(p):
    """Defesa em profundidade: só permite apagar DENTRO do projeto e nunca as
    pastas-raiz importantes (raiz, VIRALS, código, .venv, models, WEBUI_ASSETS,
    VC-ChurchEdition)."""
    ap = os.path.abspath(p)
    base = os.path.abspath(BASE_DIR)
    if not (ap == base or ap.startswith(base + os.sep)):
        return False
    protected_exact = {base, os.path.abspath(VIRALS_DIR)}
    protected_exact |= {os.path.abspath(os.path.join(base, d)) for d in ("scripts", "webui", "i18n")}
    if ap in protected_exact:
        return False
    forbidden_roots = [os.path.abspath(os.path.join(base, d))
                       for d in (".venv", "models", "VC-ChurchEdition", "WEBUI_ASSETS")]
    for fr in forbidden_roots:
        if ap == fr or ap.startswith(fr + os.sep):
            return False
    return True

def get_garbage_targets():
    """Lista (somente) o 'lixo óbvio' a ser apagado."""
    targets = []
    # 1) Todos os projetos/arquivos dentro de VIRALS (exceto "Cortes IPB",
    #    que no Colab guarda os vídeos finais do usuário no Drive)
    if os.path.isdir(VIRALS_DIR):
        for name in sorted(os.listdir(VIRALS_DIR)):
            if name in PROTECTED_VIRALS_NAMES:
                continue
            targets.append(os.path.join(VIRALS_DIR, name))
    # 2) Vídeos de teste/saída e temporários soltos na raiz
    for name in ("out_test_vid.mp4", "test_vid.mp4", "test_vid_no_audio.mp4",
                 "test_audio.mp3", "temp_subtitle_config.json"):
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            targets.append(p)
    # 3) Previews do WebUI
    preview_dir = os.path.join(BASE_DIR, "webui", "PREVIEW")
    if os.path.isdir(preview_dir):
        for name in sorted(os.listdir(preview_dir)):
            targets.append(os.path.join(preview_dir, name))
    # 4) Caches __pycache__ do projeto: normalmente sao pequenos, entao so
    # entram na limpeza se algum crescer demais.
    for sub in ("", "scripts", "webui", "i18n"):
        p = os.path.join(BASE_DIR, sub, "__pycache__")
        if os.path.isdir(p) and _path_size(p) >= PYCACHE_CLEANUP_THRESHOLD_BYTES:
            targets.append(p)
    # Filtro de segurança final
    return [t for t in targets if _is_safe_to_delete(t)]

def preview_garbage():
    """Retorna (texto_para_exibir, lista_de_alvos) SEM apagar nada."""
    targets = get_garbage_targets()
    if not targets:
        return i18n("Nada para limpar — já está tudo limpo."), []
    lines = []
    total = 0
    for p in targets:
        sz = _path_size(p)
        total += sz
        kind = "[pasta]" if os.path.isdir(p) else "[arquivo]"
        rel = os.path.relpath(p, BASE_DIR)
        lines.append(f"  {kind} {rel}  ({_human_size(sz)})")
    header = (
        f"{len(targets)} item(ns) serão apagados — {_human_size(total)} no total.\n"
        "NÃO serão tocados: a pasta 'Cortes IPB', seus assets enviados, "
        "as configurações e a chave de API.\n"
    )
    if is_colab():
        header += (
            "ATENÇÃO (Colab): os projetos em VIRALS estão no seu Google Drive — "
            "apagar aqui apaga do Drive também.\n"
        )
    header += "\n"
    return header + "\n".join(lines), targets

def clean_garbage():
    """Apaga o lixo óbvio (re-escaneia no momento do clique). Retorna relatório."""
    targets = get_garbage_targets()
    if not targets:
        return i18n("Nada para limpar — já está tudo limpo.")
    deleted = 0
    freed = 0
    errors = []
    for p in targets:
        if not _is_safe_to_delete(p):  # trava redundante por segurança
            continue
        try:
            sz = _path_size(p)
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            freed += sz
            deleted += 1
        except Exception as e:
            errors.append(f"{os.path.relpath(p, BASE_DIR)}: {e}")
    os.makedirs(VIRALS_DIR, exist_ok=True)  # mantém a pasta VIRALS (vazia)
    msg = f"OK: limpeza concluída: {deleted} item(ns) apagados, {_human_size(freed)} liberados."
    if errors:
        msg += ("\n\nAtenção: alguns itens não puderam ser apagados (talvez em uso por outro "
                "programa):\n" + "\n".join(errors[:20]))
    return msg

def generate_project_gallery(project_path_name, is_full_path=False):
    """
    Generates HTML gallery for a given project folder using FastAPI Static Files mounting.
    """
    if not project_path_name:
        return f'<div style="padding: 20px; text-align: center;">{i18n("No project selected.")}</div>'
    
    # Determine absolute path to project folder
    if is_full_path:
        project_folder_path = project_path_name
    else:
        project_folder_path = os.path.join(VIRALS_DIR, project_path_name)

    if not os.path.exists(project_folder_path):
        return f'<div style="padding: 20px; text-align: center;">{i18n("Project path not found: {}").format(project_folder_path)}</div>'

    try:
        # Load JSON
        json_path = os.path.join(project_folder_path, "viral_segments.txt")
        segments_data = {}
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                segments_data = json.load(f)
        
        segments_list = segments_data.get("segments", [])
        
        # Fallback if list is empty
        if not segments_list:
             found_files = []
             for subdir in ["burned_sub", "cuts", "."]:
                 d = os.path.join(project_folder_path, subdir)
                 if os.path.exists(d):
                     for f in os.listdir(d):
                         if f.endswith(".mp4") and "input" not in f.lower():
                             found_files.append(os.path.join(d, f))
             found_files = sorted(list(set(found_files)))
             segments_list = [{"title": os.path.basename(f), "score": "N/A", "description": "No metadata found.", "filepath": f} for f in found_files]

        html_cards = ""
        total_segments = len(segments_list)
        render_segments = segments_list
        limit_notice = ""
        if GALLERY_MAX_CARDS and total_segments > GALLERY_MAX_CARDS:
            render_segments = segments_list[:GALLERY_MAX_CARDS]
            limit_notice = (
                f'<div style="padding: 8px 12px; margin: 0 6px 12px 6px; '
                f'border: 1px solid {PALETTE["border_strong"]}; border-radius: 10px; color: {PALETTE["primary_deeper"]}; '
                f'background: {PALETTE["surface_soft"]};">'
                f'{i18n("Mostrando os primeiros {} de {} segmentos no Colab para evitar travamentos.").format(GALLERY_MAX_CARDS, total_segments)}'
                f'</div>'
            )
        
        for i, seg in enumerate(render_segments):
            title = seg.get("title", f"{i18n('Segment')} {i+1}")
            score = seg.get("score", "N/A")
            description = seg.get("description", i18n("No description available."))
            
            video_path = _find_segment_video(project_folder_path, i, seg)

            video_tag = ""
            download_link = ""
            if video_path:
                try:
                    abs_video = os.path.abspath(video_path)
                    
                    if URL_MODE == "gradio":
                         video_src = build_file_url(abs_video)
                         video_src_candidates = json.dumps(build_file_url_candidates(abs_video))
                         
                         if os.path.exists(abs_video):
                             print(f"DEBUG:   File Exists.")
                         else:
                             print(f"DEBUG:   File NOT FOUND.")
                             
                         video_tag = f"""
                        <video controls preload="none" playsinline data-candidates='{video_src_candidates}' data-src-index="0" onerror="(function(v){{try{{let c=JSON.parse(v.dataset.candidates||'[]');let i=Number(v.dataset.srcIndex||0)+1;let s=v.querySelector('source');if(i<c.length){{if(s){{s.src=c[i];}}else{{v.src=c[i];}}v.dataset.srcIndex=String(i);v.load();}}}}catch(e){{console.warn('Video fallback setup failed',e);}}}})(this);" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: contain;">
                            <source src="{video_src}" type="video/mp4">
                            Your browser does not support the video tag.
                        </video>
                        """
                         download_link = f'<a href="{video_src}" target="_blank" download="{os.path.basename(video_path)}" style="color: var(--vc-text-muted); display: flex; align-items: center; justify-content: center; padding: 5px; border-radius: 50%; transition: color 0.2s;" title="Download" onmouseover="this.style.color=\'var(--vc-primary-deep)\'" onmouseout="this.style.color=\'var(--vc-text-muted)\'">{icon("download", 22)}</a>'

                    else:
                        # Use Relative Path through /virals mount
                        # Calculate relative path from VIRALS_DIR
                        # video_path needs to be under VIRALS_DIR for this to work
                        abs_virals = os.path.abspath(VIRALS_DIR)
                        
                        if abs_video.startswith(abs_virals):
                            rel_path = os.path.relpath(abs_video, abs_virals)
                            # Replace backslashes for URL
                            url_path = rel_path.replace("\\", "/")
                            url_path = urllib.parse.quote(url_path)
                            
                            # Add timestamp to force cache refresh
                            import time
                            timestamp = int(time.time())
                            video_src = f"/virals/{url_path}?t={timestamp}"
                            
                            video_tag = f"""
                            <video controls preload="none" playsinline style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: contain;">
                                <source src="{video_src}" type="video/mp4">
                                Your browser does not support the video tag.
                            </video>
                            """
                            
                            
                            download_link = f'<a href="{video_src}" download="{os.path.basename(video_path)}" style="color: var(--vc-text-muted); display: flex; align-items: center; justify-content: center; padding: 5px; border-radius: 50%; transition: color 0.2s;" title="Download" onmouseover="this.style.color=\'var(--vc-primary-deep)\'" onmouseout="this.style.color=\'var(--vc-text-muted)\'">{icon("download", 22)}</a>'
                            
                        else:
                            video_tag = _video_notice_html(i18n("External Video"))
                except Exception as e:
                    video_tag = _video_notice_html(i18n("Error: {}").format(str(e)))

            else:
                video_tag = _video_notice_html(i18n("Not Found"))
            
            # Score
            score_color = PALETTE["primary_deep"]
            try:
                if isinstance(score, int) or (isinstance(score, str) and score.isdigit()):
                    val = int(score)
                    if val < 70: score_color = PALETTE["error"]
                    elif val < 85: score_color = PALETTE["warning"]
            except: pass

            # Polish Subs Button (AI correction for this segment's subtitles)
            try:
                proj_name_polish = urllib.parse.quote(os.path.basename(project_path_name), safe="")
                polish_svg = icon("wand", 22)
                polish_btn_title = i18n("Corrigir legenda com IA")
                escaped_polish_title = html.escape(polish_btn_title, quote=True)
                polish_btn = f'<button type="button" class="polish-subs-btn" data-project="{proj_name_polish}" data-segment="{i}" style="color: var(--vc-text-muted); display: flex; align-items: center; justify-content: center; padding: 5px; border-radius: 50%; transition: color 0.2s; cursor: pointer; background: transparent; border: none; margin: 0;" title="{escaped_polish_title}" aria-label="{escaped_polish_title}">{polish_svg}</button>'
            except Exception:
                polish_btn = ""

            # Buffer/Margin Control (only if original times exist)
            buffer_control_html = ""
            has_buffer_data = "original_start_time" in seg
            if has_buffer_data:
                # Padrão atual é corte limpo (buffer 0 = saldo cheio); só projetos
                # legados com buffer embutido trazem buffer_seconds explícito.
                buf_start = int(seg.get("buffer_start_used", seg.get("buffer_seconds", 0)))
                buf_end = int(seg.get("buffer_end_used", seg.get("buffer_seconds", 0)))
                saldo_start = 5 - buf_start
                saldo_end = 5 - buf_end
                proj_name_buffer = urllib.parse.quote(os.path.basename(project_path_name), safe="")

                input_style = "width: 56px; height: 26px; background: var(--vc-surface); color: var(--vc-text); border: 1px solid var(--vc-border-strong); border-radius: 5px; text-align: center; font-size: 13px; font-family: sans-serif; -moz-appearance: textfield;"
                label_style = "color: var(--vc-text-soft); font-size: 11px; font-family: sans-serif; white-space: nowrap;"
                saldo_style = "color: var(--vc-text-muted); font-size: 10px; font-family: sans-serif; white-space: nowrap;"
                row_style = "display: flex; align-items: center; gap: 6px; justify-content: space-between;"

                # Unique IDs for JS to find sibling inputs
                uid = f"buf_{i}"

                buffer_control_html = f'''
                    <div style="margin-top: 8px; padding: 8px 6px; background: var(--vc-surface-soft); border-radius: 10px; border: 1px solid var(--vc-border); display: flex; flex-direction: column; gap: 5px;">
                        <div style="display: flex; align-items: center; gap: 4px; justify-content: center; margin-bottom: 2px;">
                            <span class="vc-icon-inline" style="color: var(--vc-text-soft); font-size: 11px; font-family: sans-serif;">{icon("refresh", 13)}<span>Margem de segurança</span></span>
                        </div>
                        <div style="color: var(--vc-text-muted); font-size: 10px; font-family: sans-serif; text-align: center;">+ amplia, - corta</div>
                        <div style="{row_style}">
                            <span style="{label_style}">Início:</span>
                            <input type="number" class="buffer-start-input" id="{uid}_start" min="-600" max="600" step="1" value="{buf_start}" style="{input_style}" title="+ amplia para antes, - corta o inicio" onchange="if(window.vcUpdateBufferSaldo)window.vcUpdateBufferSaldo(this)" oninput="if(window.vcClampBufferInput)window.vcClampBufferInput(this)">
                            <span style="{label_style}">s</span>
                            <span class="saldo-start" style="{saldo_style}">(saldo: {saldo_start}s)</span>
                        </div>
                        <div style="{row_style}">
                            <span style="{label_style}">Final:</span>
                            <input type="number" class="buffer-end-input" id="{uid}_end" min="-600" max="600" step="1" value="{buf_end}" style="{input_style}" title="+ amplia depois, - corta o final" onchange="if(window.vcUpdateBufferSaldo)window.vcUpdateBufferSaldo(this)" oninput="if(window.vcClampBufferInput)window.vcClampBufferInput(this)">
                            <span style="{label_style}">s</span>
                            <span class="saldo-end" style="{saldo_style}">(saldo: {saldo_end}s)</span>
                        </div>
                        <button type="button" class="reprocess-buffer-btn" data-project="{proj_name_buffer}" data-segment="{i}" data-start-id="{uid}_start" data-end-id="{uid}_end" style="margin-top: 3px; padding: 5px 10px; background: var(--vc-grad); color: #fff; font-weight: 700; font-size: 12px; font-family: sans-serif; border: none; border-radius: 8px; cursor: pointer; transition: filter 0.2s; display: flex; align-items: center; justify-content: center; gap: 5px;" onmouseover="this.style.filter='brightness(1.1)'" onmouseout="this.style.filter='brightness(1)'">{icon("refresh", 13)}<span>Reprocessar</span></button>
                    </div>
                '''

            # --- Botões "Aplicar X" por recurso desativável (estado por corte) ---
            # Ativo (colorido) = ainda não embutido neste corte; Cinza = já aplicado.
            try:
                feats = render_state.get_segment_features(project_folder_path, i)
            except Exception:
                feats = {}
            proj_name_apply = urllib.parse.quote(os.path.basename(project_path_name), safe="")
            apply_features = [
                ("watermark", i18n("Marca d'Água"), i18n("Aplicar Marca d'Água")),
                ("outro", i18n("Outro"), i18n("Aplicar Outro / Encerramento")),
                ("audio_bgm", i18n("Áudio"), i18n("Aplicar Áudio BGM")),
                ("outro_music", i18n("Música"), i18n("Aplicar Música de Encerramento")),
            ]
            feature_accent = {"watermark": "#0ea5e9", "outro": "#a855f7", "audio_bgm": "#22c55e", "outro_music": "#f59e0b"}
            plus_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>'
            check_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
            x_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="m15 9-6 6"></path><path d="m9 9 6 6"></path></svg>'
            apply_btns = ""
            for fkey, short_label, full_title in apply_features:
                esc_label = html.escape(short_label, quote=True)
                accent = feature_accent.get(fkey, "#3b82f6")
                apply_title = html.escape(full_title, quote=True)
                remove_title = html.escape(f"{i18n('Remover')} {short_label}", quote=True)
                if bool(feats.get(fkey, False)):
                    apply_btns += (
                        f'<button type="button" class="apply-feature-btn applied" '
                        f'data-feature="{fkey}" data-project="{proj_name_apply}" data-segment="{i}" data-label="{esc_label}" '
                        f'data-accent="{accent}" data-apply-title="{apply_title}" data-remove-title="{remove_title}" '
                        f'style="display:inline-flex; align-items:center; gap:5px; padding:5px 9px; border-radius:8px; '
                        f'background:#E2E8F0; color:#94A3B8; border:1px solid #CBD5E1; cursor:pointer; '
                        f'font-size:11.5px; font-weight:600; font-family:sans-serif;" title="{remove_title}">'
                        f'<span class="vc-feature-icon-current">{check_svg}</span><span class="vc-feature-icon-remove">{x_svg}</span><span class="vc-feature-label">{esc_label}</span></button>'
                    )
                else:
                    accent = feature_accent.get(fkey, "#3b82f6")
                    apply_btns += (
                        f'<button type="button" class="apply-feature-btn" '
                        f'data-feature="{fkey}" data-project="{proj_name_apply}" data-segment="{i}" data-label="{esc_label}" '
                        f'data-accent="{accent}" data-apply-title="{apply_title}" data-remove-title="{remove_title}" '
                        f'style="display:inline-flex; align-items:center; gap:5px; padding:5px 9px; border-radius:7px; '
                        f'background:{accent}; color:#fff; border:none; cursor:pointer; '
                        f'font-size:11.5px; font-weight:600; font-family:sans-serif; transition:filter .2s;" '
                        f'title="{html.escape(full_title, quote=True)}" onmouseover="this.style.filter=\'brightness(1.12)\'" onmouseout="this.style.filter=\'brightness(1)\'">'
                        f'{plus_svg}<span class="vc-feature-label">{esc_label}</span></button>'
                    )
            apply_buttons_html = f'<div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; justify-content:center;">{apply_btns}</div>'

            # Card HTML - Dark Grid Style like Opus.pro (Inline Styles)
            card_html = f"""
            <div class="viral-card" data-segment="{i}" style="display: flex; flex-direction: column; background: transparent; overflow: visible;">
                
                <!-- Video Player Container (9:16 Aspect Ratio) -->
                <div class="vc-video-wrap" style="position: relative; width: 100%; padding-top: 177.77%; background: #0F172A; border-radius: 14px; overflow: hidden; margin-bottom: 12px; border: 1px solid {PALETTE['border_strong']}; box-shadow: 0 6px 16px rgba(52,126,102,0.10); transition: box-shadow .2s ease;">
                    {video_tag}
                </div>
                
                <!-- Info Area -->
                <div style="display: flex; flex-direction: column; gap: 6px; padding: 0 4px;">
                    <!-- Top Row: Score and Actions -->
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 28px; font-weight: 900; line-height: 1; color: {score_color}; font-family: sans-serif;">{score}</span>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            {polish_btn}
                            {download_link}
                        </div>
                    </div>
                    
                    <!-- Title -->
                    <h4 style="margin: 4px 0 0 0; color: {PALETTE['text']}; font-size: 15px; font-weight: 600; line-height: 1.4; font-family: sans-serif; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-align: center;" title="{title}">{title}</h4>

                    <!-- Aplicar recursos por corte -->
                    {apply_buttons_html}

                    <!-- Buffer/Margin Control -->
                    {buffer_control_html}
                </div>
            </div>
            """
            html_cards += card_html
        
        if not html_cards:
             return f'<div style="padding: 40px; text-align: center; color: #888; font-size: 1.2em;">{i18n("No viral segments found.")}</div>'

        # Global toolbar above the grid: "Polish all subtitles with AI"
        proj_name_polish_all = urllib.parse.quote(os.path.basename(project_path_name), safe="")
        polish_all_title = html.escape(i18n("Corrigir todas as legendas com IA"), quote=True)
        polish_all_label = i18n("Corrigir todas as legendas com IA")
        toolbar_html = f"""
        <div style="display: flex; justify-content: flex-end; align-items: center; gap: 8px; padding: 0 6px 10px 6px;">
            <button type="button" class="polish-all-subs-btn" data-project="{proj_name_polish_all}" title="{polish_all_title}" style="display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 10px; background: {PALETTE['grad']}; color: #fff; border: none; cursor: pointer; font-size: 13px; font-weight: 600; box-shadow: 0 4px 12px rgba(16,185,129,0.30); transition: filter 0.2s;" onmouseover="this.style.filter='brightness(1.1)'" onmouseout="this.style.filter='brightness(1)'">
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"></path><path d="M20 3v4"></path><path d="M22 5h-4"></path><path d="M4 17v2"></path><path d="M5 18H3"></path></svg>
                <span class="polish-all-label">{polish_all_label}</span>
            </button>
        </div>
        """

        # Gallery Container
        return f"""
        {toolbar_html}
        {limit_notice}
        <div class="vc-fade" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 30px; width: 100%; padding: 10px 0;">
            {html_cards}
        </div>
        """

    except Exception as e:
        return i18n("Error loading gallery: {}").format(e)
