import os
import json
import urllib.parse
import html
import gradio as gr
try:
    from media_utils import build_file_url, build_file_url_candidates
except ImportError:
    from webui.media_utils import build_file_url, build_file_url_candidates

# Setup Virals Dir relative to this file
# This file is in webui/library.py
# VIRALS dir is in ../VIRALS (root of project)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.append(BASE_DIR)
from i18n.i18n import I18nAuto
i18n = I18nAuto()

VIRALS_DIR = os.path.join(BASE_DIR, "VIRALS")


# URL Mode: "fastapi" (default) or "gradio"
URL_MODE = "fastapi"
GALLERY_MAX_CARDS = None

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
                f'border: 1px solid #3f3f46; border-radius: 8px; color: #d4d4d8; '
                f'background: #18181b;">'
                f'{i18n("Mostrando os primeiros {} de {} segmentos no Colab para evitar travamentos.").format(GALLERY_MAX_CARDS, total_segments)}'
                f'</div>'
            )
        
        for i, seg in enumerate(render_segments):
            export_link = ""
            title = seg.get("title", f"{i18n('Segment')} {i+1}")
            score = seg.get("score", "N/A")
            description = seg.get("description", i18n("No description available."))
            
            video_path = seg.get("filepath", None)
            
            # Smart search
            if not video_path:
                idx_str = f"{i:03d}"
                potential_paths = [
                    os.path.join(project_folder_path, "burned_sub", f"final-output{idx_str}_processed_subtitled.mp4"),
                    os.path.join(project_folder_path, "burned_sub", f"output{idx_str}.mp4"),
                    os.path.join(project_folder_path, f"final-output{idx_str}_processed.mp4"),
                    os.path.join(project_folder_path, f"output{idx_str}_original_scale.mp4"),
                    os.path.join(project_folder_path, f"output{idx_str}.mp4"),
                    os.path.join(project_folder_path, "cuts", f"output{idx_str}_original_scale.mp4"),
                    os.path.join(project_folder_path, "cuts", f"segment_{idx_str}.mp4"),
                    os.path.join(project_folder_path, "cuts", f"{idx_str}.mp4")
                ]
                if isinstance(seg.get("filename"), str):
                    potential_paths.insert(0, os.path.join(project_folder_path, seg["filename"]))
                    potential_paths.insert(0, os.path.join(project_folder_path, "burned_sub", seg["filename"]))

                for p in potential_paths:
                    if os.path.exists(p):
                        video_path = p
                        break
            
            # Loose search
            if not video_path:
                 sub_dirs = [os.path.join(project_folder_path, "burned_sub"), os.path.join(project_folder_path, "cuts")]
                 for sd in sub_dirs:
                     if os.path.exists(sd):
                         for f in sorted(os.listdir(sd)):
                             idx_str = f"{i:03d}"
                             if f.endswith(".mp4") and idx_str in f:
                                 video_path = os.path.join(sd, f)
                                 break
                     if video_path: break

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
                         download_link = f'<a href="{video_src}" target="_blank" download="{os.path.basename(video_path)}" style="color: #aaa; display: flex; align-items: center; justify-content: center; padding: 5px; border-radius: 50%; transition: color 0.2s;" title="Download" onmouseover="this.style.color=\'#fff\'" onmouseout="this.style.color=\'#aaa\'"><svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg></a>'

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
                            
                            
                            download_link = f'<a href="{video_src}" download="{os.path.basename(video_path)}" style="color: #aaa; display: flex; align-items: center; justify-content: center; padding: 5px; border-radius: 50%; transition: color 0.2s;" title="Download" onmouseover="this.style.color=\'#fff\'" onmouseout="this.style.color=\'#aaa\'"><svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg></a>'
                            
                            # Export XML Link
                            # project_path_name might be full path or folder name
                            proj_name_api = urllib.parse.quote(os.path.basename(project_path_name), safe="")
                            
                            def make_export_btn(fmt, label, color_hover, svg_path):
                                fmt_q = urllib.parse.quote(str(fmt), safe="")
                                src = f"/export_xml_api?project={proj_name_api}&segment={i}&format={fmt_q}"
                                return f'<a href="{src}" target="_blank" style="color: #aaa; display: flex; align-items: center; justify-content: center; padding: 5px; border-radius: 50%; transition: color 0.2s;" title="{label}" onmouseover="this.style.color=\'{color_hover}\'" onmouseout="this.style.color=\'#aaa\'"><svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{svg_path}</svg></a>'

                            # Premiere (Pr)
                            export_pr = make_export_btn("premiere", "Export Premiere XML (Split Screen – known bug)", "#d064ff", '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M9 15h6"></path><path d="M12 12v6"></path>')
                            
                            # Resolve (Dv)
                            # export_dv = make_export_btn("resolve", "Export DaVinci Resolve XML", "#ff6464", '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><circle cx="12" cy="14" r="3"></circle>')
                            
                            # Final Cut (Fc)
                            # export_fc = make_export_btn("final-cut-pro", "Export FCP XML", "#64d0ff", '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M10 12l4 2l-4 2z"></path>')

                            export_link = f"{export_pr}" #{export_dv}{export_fc}"

                        else:
                            video_tag = f'<div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #222; color: #666;"><span>⚠️</span><br>{i18n("External Video")}</div>'
                except Exception as e:
                    video_tag = f'<div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #222; color: #666;"><span>⚠️</span><br>{i18n("Error: {}").format(str(e))}</div>'

            else:
                video_tag = f'<div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #222; color: #666;"><span>⚠️</span><br>{i18n("Not Found")}</div>'
            
            # Score
            score_color = "#22c55e"
            try:
                if isinstance(score, int) or (isinstance(score, str) and score.isdigit()):
                    val = int(score)
                    if val < 70: score_color = "#ef4444" 
                    elif val < 85: score_color = "#eab308"
            except: pass

            # Audio Button
            if video_path:
                try:
                    abs_video = os.path.abspath(video_path)
                    encoded_abs = urllib.parse.quote(abs_video, safe="")
                    # SVG is a musical note icon
                    audio_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>'
                    audio_btn_title = i18n("Aplicar Áudio BGM")
                    escaped_audio_btn_title = html.escape(audio_btn_title, quote=True)
                    audio_btn = f'<button type="button" class="apply-audio-btn" data-video-path="{encoded_abs}" style="color: #aaa; display: flex; align-items: center; justify-content: center; padding: 5px; border-radius: 50%; transition: color 0.2s; text-decoration: none; cursor: pointer; background: transparent; border: none; margin: 0;" title="{escaped_audio_btn_title}" aria-label="{escaped_audio_btn_title}">{audio_svg}</button>'
                except:
                    audio_btn = ""
            else:
                audio_btn = ""

            # Polish Subs Button (AI correction for this segment's subtitles)
            try:
                proj_name_polish = urllib.parse.quote(os.path.basename(project_path_name), safe="")
                polish_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"></path><path d="M20 3v4"></path><path d="M22 5h-4"></path><path d="M4 17v2"></path><path d="M5 18H3"></path></svg>'
                polish_btn_title = i18n("Corrigir legenda com IA")
                escaped_polish_title = html.escape(polish_btn_title, quote=True)
                polish_btn = f'<button type="button" class="polish-subs-btn" data-project="{proj_name_polish}" data-segment="{i}" style="color: #aaa; display: flex; align-items: center; justify-content: center; padding: 5px; border-radius: 50%; transition: color 0.2s; cursor: pointer; background: transparent; border: none; margin: 0;" title="{escaped_polish_title}" aria-label="{escaped_polish_title}">{polish_svg}</button>'
            except Exception:
                polish_btn = ""

            # Buffer/Margin Control (only if original times exist)
            buffer_control_html = ""
            has_buffer_data = "original_start_time" in seg
            if has_buffer_data:
                buf_start = int(seg.get("buffer_start_used", seg.get("buffer_seconds", 5)))
                buf_end = int(seg.get("buffer_end_used", seg.get("buffer_seconds", 5)))
                saldo_start = 5 - buf_start
                saldo_end = 5 - buf_end
                proj_name_buffer = urllib.parse.quote(os.path.basename(project_path_name), safe="")

                input_style = "width: 44px; height: 26px; background: #1a1a1a; color: #e5e5e5; border: 1px solid #444; border-radius: 5px; text-align: center; font-size: 13px; font-family: sans-serif; -moz-appearance: textfield;"
                label_style = "color: #aaa; font-size: 11px; font-family: sans-serif; white-space: nowrap;"
                saldo_style = "color: #666; font-size: 10px; font-family: sans-serif; white-space: nowrap;"
                row_style = "display: flex; align-items: center; gap: 6px; justify-content: space-between;"

                # Unique IDs for JS to find sibling inputs
                uid = f"buf_{i}"

                buffer_control_html = f'''
                    <div style="margin-top: 8px; padding: 8px 6px; background: #161616; border-radius: 8px; border: 1px solid #2a2a2a; display: flex; flex-direction: column; gap: 5px;">
                        <div style="display: flex; align-items: center; gap: 4px; justify-content: center; margin-bottom: 2px;">
                            <span style="color: #888; font-size: 11px; font-family: sans-serif;">⏱️ Margem de segurança</span>
                        </div>
                        <div style="{row_style}">
                            <span style="{label_style}">Início:</span>
                            <input type="number" class="buffer-start-input" id="{uid}_start" min="0" max="5" step="1" value="{buf_start}" style="{input_style}" onchange="var s=this.parentElement.querySelector('.saldo-start');if(s)s.textContent='(saldo: '+(5-Math.max(0,Math.min(5,parseInt(this.value)||0)))+'s)'" oninput="this.value=Math.max(0,Math.min(5,parseInt(this.value)||0))">
                            <span style="{label_style}">s</span>
                            <span class="saldo-start" style="{saldo_style}">(saldo: {saldo_start}s)</span>
                        </div>
                        <div style="{row_style}">
                            <span style="{label_style}">Final:</span>
                            <input type="number" class="buffer-end-input" id="{uid}_end" min="0" max="5" step="1" value="{buf_end}" style="{input_style}" onchange="var s=this.parentElement.querySelector('.saldo-end');if(s)s.textContent='(saldo: '+(5-Math.max(0,Math.min(5,parseInt(this.value)||0)))+'s)'" oninput="this.value=Math.max(0,Math.min(5,parseInt(this.value)||0))">
                            <span style="{label_style}">s</span>
                            <span class="saldo-end" style="{saldo_style}">(saldo: {saldo_end}s)</span>
                        </div>
                        <button type="button" class="reprocess-buffer-btn" data-project="{proj_name_buffer}" data-segment="{i}" data-start-id="{uid}_start" data-end-id="{uid}_end" style="margin-top: 3px; padding: 5px 10px; background: linear-gradient(135deg, #f59e0b, #d97706); color: #000; font-weight: 700; font-size: 12px; font-family: sans-serif; border: none; border-radius: 6px; cursor: pointer; transition: filter 0.2s; display: flex; align-items: center; justify-content: center; gap: 5px;" onmouseover="this.style.filter='brightness(1.15)'" onmouseout="this.style.filter='brightness(1)'">🔄 Reprocessar</button>
                    </div>
                '''

            # Card HTML - Dark Grid Style like Opus.pro (Inline Styles)
            card_html = f"""
            <div class="viral-card" style="display: flex; flex-direction: column; background: transparent; overflow: visible;">
                
                <!-- Video Player Container (9:16 Aspect Ratio) -->
                <div style="position: relative; width: 100%; padding-top: 177.77%; background: #111; border-radius: 12px; overflow: hidden; margin-bottom: 12px; border: 1px solid #333; box-shadow: 0 4px 10px rgba(0,0,0,0.3);">
                    {video_tag}
                </div>
                
                <!-- Info Area -->
                <div style="display: flex; flex-direction: column; gap: 6px; padding: 0 4px;">
                    <!-- Top Row: Score and Actions -->
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 28px; font-weight: 900; line-height: 1; color: {score_color}; font-family: sans-serif;">{score}</span>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            {polish_btn}
                            {audio_btn}
                            {export_link}
                            {download_link}
                        </div>
                    </div>
                    
                    <!-- Title -->
                    <h4 style="margin: 4px 0 0 0; color: #e5e5e5; font-size: 15px; font-weight: 600; line-height: 1.4; font-family: sans-serif; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-align: center;" title="{title}">{title}</h4>
                    
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
            <button type="button" class="polish-all-subs-btn" data-project="{proj_name_polish_all}" title="{polish_all_title}" style="display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 8px; background: linear-gradient(135deg, #7c3aed, #4f46e5); color: #fff; border: none; cursor: pointer; font-size: 13px; font-weight: 600; box-shadow: 0 2px 6px rgba(124,58,237,0.35); transition: filter 0.2s;" onmouseover="this.style.filter='brightness(1.1)'" onmouseout="this.style.filter='brightness(1)'">
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"></path><path d="M20 3v4"></path><path d="M22 5h-4"></path><path d="M4 17v2"></path><path d="M5 18H3"></path></svg>
                <span class="polish-all-label">{polish_all_label}</span>
            </button>
        </div>
        """

        # Gallery Container
        return f"""
        {toolbar_html}
        {limit_notice}
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 30px; width: 100%; padding: 10px 0;">
            {html_cards}
        </div>
        """

    except Exception as e:
        return i18n("Error loading gallery: {}").format(e)
