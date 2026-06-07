import os
import sys

# Suppress unnecessary logs before importing heavy libs
os.environ["ORT_LOGGING_LEVEL"] = "3" 
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import warnings
warnings.filterwarnings("ignore")

import json
import shutil
import subprocess
import argparse
import time
from scripts import (
    download_video,
    transcribe_video,
    create_viral_segments,
    cut_segments,
    edit_video,
    transcribe_cuts,
    adjust_subtitles,
    burn_subtitles,
    save_json,
    organize_output,
)
from i18n.i18n import I18nAuto

# Inicializa sistema de tradução
i18n = I18nAuto()
#
# Configurações de Legenda (ASS Style)
# Cores no formato BGR (Blue-Green-Red) para o ASS
COLORS = {
    "red": "0000FF",  # Red
    "yellow": "00FFFF",   # Yellow
    "green": "00FF00",     # Green
    "white": "FFFFFF",    # White
    "black": "000000",     # Black
    "grey": "808080",     # Grey
}

def get_subtitle_config(config_path=None):
    """
    Returns the subtitle configuration dictionary.
    Can be expanded to load from a JSON/YAML file in the future.
    """
    # Default Config
    base_color_transparency = "00"
    outline_transparency = "00" 
    highlight_color_transparency = "00"
    shadow_color_transparency = "00"
    
    config = {
        "font": "Montserrat",
        "base_size": 30,
        "base_color": f"&H{base_color_transparency}{COLORS['white']}&",
        "highlight_size": 30,
        "words_per_block": 4,
        "gap_limit": 0.6,
        "mode": 'no_highlight', # Options: 'no_highlight', 'word_by_word', 'highlight'
        "highlight_color": f"&H{highlight_color_transparency}{COLORS['white']}&",
        "vertical_position": 140, # 1=170(top), ... 4=60(default)
        "margin_h": 35,
        "alignment": 2, # 2=Center
        "bold": 1,
        "italic": 0,
        "underline": 0,
        "strikeout": 0,
        "border_style": 1, # 1=outline, 3=box
        "outline_thickness": 1,
        "outline_color": f"&H{outline_transparency}{COLORS['black']}&",
        "shadow_size": 1,
        "shadow_color": f"&H{shadow_color_transparency}{COLORS['black']}&",
        "uppercase": 0,
        "remove_punctuation": False,
    }

    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                config.update(loaded_config)
                print(i18n("Loaded subtitle config from {}").format(config_path))
        except Exception as e:
            print(i18n("Error loading subtitle config: {}. Using defaults.").format(e))
    
    return config

def interactive_input_int(prompt_text):
    """Solicita um inteiro ao usuário via terminal."""
    while True:
        try:
            value = int(input(i18n(prompt_text)))
            if value > 0:
                return value
            print(i18n("\nError: Number must be greater than 0."))
        except ValueError:
            print(i18n("\nError: The value you entered is not an integer. Please try again."))

def _load_viral_segments_file(path):
    """Carrega viral_segments.txt de forma tolerante.

    O arquivo pode conter um JSON limpo (gerado pelo pipeline) OU um JSON colado
    por uma IA externa no Modo Manual (curadoria), que costuma vir com cercas
    markdown (```json ... ```), texto explicativo antes/depois, ou até truncado.
    Em vez de um json.load() cru (que quebra nesses casos), tentamos:
      1) json.loads estrito (preserva exatamente arquivos já válidos);
      2) clean_json_response (mesmo parser robusto usado para respostas da IA);
      3) array "pelado" entre cercas markdown.
    Retorna um dict {"segments": [...]} com a lista preenchida, ou None.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read()
    except OSError as e:
        print(i18n("Error loading JSON: {}.").format(e))
        return None

    if not raw or not raw.strip():
        return None

    # 1) Caminho feliz: JSON já válido
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("segments"), list):
            return data
        if isinstance(data, list):
            return {"segments": data}
    except (ValueError, TypeError):
        pass

    # 2) Parser tolerante (cercas ```json, texto extra, JSON truncado)
    try:
        data = create_viral_segments.clean_json_response(raw)
        if isinstance(data, dict) and data.get("segments"):
            return data
    except Exception:
        pass

    # 3) Array "pelado" possivelmente entre cercas markdown simples
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return {"segments": parsed}
            if isinstance(parsed, dict) and isinstance(parsed.get("segments"), list):
                return parsed
        except (ValueError, TypeError):
            pass

    return None

def main():
    # Configuração de Argumentos via Linha de Comando (CLI)
    parser = argparse.ArgumentParser(description="ViralCutter CLI")
    parser.add_argument("--url", help="YouTube Video URL")
    parser.add_argument("--segments", type=int, help="Number of segments to create")
    parser.add_argument("--viral", action="store_true", help="Enable viral mode")
    parser.add_argument("--themes", help="Comma-separated themes (if not viral mode)")
    parser.add_argument("--burn-only", action="store_true", help="Skip processing and only burn subtitles")
    parser.add_argument("--min-duration", type=int, default=60, help="Minimum segment duration (seconds)")
    parser.add_argument("--max-duration", type=int, default=120, help="Maximum segment duration (seconds)")
    parser.add_argument("--ai-duration", action="store_true", help="A IA decide a duração: sem mínimo; --max-duration vira teto de segurança")
    parser.add_argument("--model", default="large-v3-turbo", help="Whisper model to use")
    parser.add_argument("--language", default="pt", help="Default transcription language code (e.g. 'pt', 'en')")
    
    parser.add_argument("--api-key", help="Gemini API Key")

    parser.add_argument("--chunk-size", help="Override Chunk Size")
    parser.add_argument("--ai-model-name", help="Override AI Model Name")

    parser.add_argument("--project-path", help="Path to existing project folder (overrides URL/Latest)")
    parser.add_argument("--workflow", choices=["1", "2", "3"], default="1", help="Workflow choice: 1=Full, 2=Cut Only, 3=Subtitles Only")
    parser.add_argument("--subtitle-config", help="Path to subtitle configuration JSON file")
    parser.add_argument("--outro-config", help="Path to outro configuration JSON file")
    parser.add_argument("--watermark-config", help="Path to watermark configuration JSON file")
    parser.add_argument("--audio-config", help="Path to audio configuration JSON file")
    parser.add_argument("--skip-prompts", action="store_true", help="Skip interactive prompts and use defaults/existing files")
    parser.add_argument("--video-quality", choices=["best", "1080p", "720p", "480p"], default="best", help="Video download quality")
    parser.add_argument("--skip-youtube-subs", dest="skip_youtube_subs", action="store_true", default=True, help="Skip downloading YouTube subtitles")
    parser.add_argument("--use-youtube-subs", dest="skip_youtube_subs", action="store_false", help="Download and use YouTube subtitles if available")
    parser.add_argument("--manual-webui", action="store_true", help="Pause pipeline after generating prompts for manual UI intervention.")

    args = parser.parse_args()
    
    # Workflow Logic
    workflow_choice = args.workflow
    
    # If Subtitles Only, checking project path
    if workflow_choice == "3" and not args.project_path and not args.url and not args.skip_prompts:
        # Prompt for project path or use latest if not provided?
        pass # Will handle in main flow

    # Modo Apenas Queimar Legenda (Legacy support, mapped to Workflow 3 internally if burn-only is set)
    # Verifica o argumento CLI ou uma variável local hardcoded (para compatibilidade)
    burn_only_mode = args.burn_only

    if burn_only_mode:
        print(i18n("Burn only mode activated. Switching to Workflow 3..."))
        workflow_choice = "3"

    # Obtenção de Inputs (CLI ou Interativo)
    url = args.url
    project_path_arg = args.project_path
    input_video = None

    # Se project_path for fornecido, ignoramos URL
    if project_path_arg:
        if os.path.exists(project_path_arg):
             print(i18n("Using provided project path: {}").format(project_path_arg))
             # Tentar achar o input.mp4 pra manter compatibilidade de variaveis, embora Workflow 3 não precise de download
             possible_input = os.path.join(project_path_arg, "input.mp4")
             if os.path.exists(possible_input):
                 input_video = possible_input
             else:
                 # Se não tiver input.mp4, tudo bem para workflow 3, mas definimos um dummy para não quebrar logica
                 input_video = os.path.join(project_path_arg, "dummy_input.mp4")
             
             # Se for workflow 3, não precisamos de URL
        else:
             print(i18n("Error: Provided project path does not exist."))
             sys.exit(1)

    # Se não temos URL via CLI nem Project Path, pedimos agora
    if not url and not project_path_arg:
        if args.skip_prompts:
             print(i18n("No URL provided and skipping prompts. Trying to load latest project..."))
             # Fallthrough to project loading logic
        else:
            user_input = input(i18n("Enter the YouTube video URL (or press Enter to use latest project): ")).strip()
            if user_input:
                url = user_input
    
    if not url and not input_video:
        # Usuário apertou Enter (Vazio) -> Tentar pegar último projeto
        base_virals = "VIRALS"
        if os.path.exists(base_virals):
            subdirs = [os.path.join(base_virals, d) for d in os.listdir(base_virals) if os.path.isdir(os.path.join(base_virals, d))]
            if subdirs:
                latest_project = max(subdirs, key=os.path.getmtime)
                detected_video = os.path.join(latest_project, "input.mp4")
                if os.path.exists(detected_video):
                    input_video = detected_video
                    print(i18n("Using latest project: {}").format(latest_project))
                else:
                    print(i18n("Latest project found but 'input.mp4' is missing."))
                    sys.exit(1)
            else:
                print(i18n("No existing projects found in VIRALS folder."))
                sys.exit(1)
        else:
             print(i18n("VIRALS folder not found. Cannot load latest project."))
             sys.exit(1)

    # -------------------------------------------------------------------------
    # Checagem Antecipada de Segmentos Virais (Para pular configurações se já existirem)
    # -------------------------------------------------------------------------
    viral_segments = None
    project_folder_anticipated = None

    if input_video:
        # Se já temos o vídeo, podemos deduzir a pasta
        project_folder_anticipated = os.path.dirname(input_video)
        viral_segments_file = os.path.join(project_folder_anticipated, "viral_segments.txt")
        
        if os.path.exists(viral_segments_file):
             print(i18n("\nExisting viral segments found: {}").format(viral_segments_file))
             if args.skip_prompts:
                 use_existing_json = 'yes'
             else:
                 use_existing_json = input(i18n("Use existing viral segments? (yes/no) [default: yes]: ")).strip().lower()
             
             if use_existing_json in ['', 'y', 'yes']:
                viral_segments = _load_viral_segments_file(viral_segments_file)
                if viral_segments and viral_segments.get("segments"):
                    print(i18n("Loaded existing viral segments. Skipping configuration prompts."))
                    print(f"DEBUG: Loaded {len(viral_segments['segments'])} segments from file.")
                else:
                    viral_segments = None
                    print("DEBUG: Não foi possível extrair uma lista 'segments' válida do JSON.")

    # Variaveis de config de IA (só necessárias se não tivermos os segmentos)
    num_segments = None
    viral_mode = False
    themes = ""
    ai_backend = "gemini"  # Only Gemini is supported
    api_key = None

    if not viral_segments:
        num_segments = args.segments
        if not num_segments:
            if args.skip_prompts:
                print(i18n("No segments count provided and skip-prompts is ON. Using default 12."))
                num_segments = 12
            else:
                num_segments = interactive_input_int("Enter the number of viral segments to create: ")

        viral_mode = args.viral
        if not args.viral and not args.themes:
            if args.skip_prompts:
                print(i18n("Viral mode not set, defaulting to True."))
                viral_mode = True
            else:
                response = input(i18n("Do you want viral mode? (yes/no): ")).lower()
                viral_mode = response in ['yes', 'y']
        
        themes = args.themes if args.themes else ""
        if not viral_mode and not themes:
            if not args.skip_prompts:
                 themes = input(i18n("Enter themes (comma-separated, leave blank if viral mode is True): "))

        # Duration Config
        print(i18n("\nCurrent duration settings: {}s - {}s").format(args.min_duration, args.max_duration))
        if not args.skip_prompts:
            change_dur = input(i18n("Change duration? (y/n) [default: n]: ")).strip().lower()
            if change_dur in ['y', 'yes']:
                 try:
                     min_d = input(i18n("Minimum duration [{}]: ").format(args.min_duration)).strip()
                     if min_d: args.min_duration = int(min_d)
                     
                     max_d = input(i18n("Maximum duration [{}]: ").format(args.max_duration)).strip()
                     if max_d: args.max_duration = int(max_d)
                 except ValueError:
                     print(i18n("Invalid number. Using previous values."))

        # Load API Config
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api_config.json')
        api_config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    api_config = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(i18n("Warning: could not read api_config.json: {}").format(e))

        # AI Backend: only Gemini is supported.
        ai_backend = "gemini"

        api_key = args.api_key
        # Check config for API Key if not provided
        if not api_key:
            cfg_key = api_config.get("gemini", {}).get("api_key", "")
            if cfg_key and cfg_key != "SUA_KEY_AQUI":
                api_key = cfg_key

        if not api_key:
             if args.skip_prompts:
                 print(i18n("Gemini API key missing, but skip-prompts is ON. Might fail."))
             else:
                 print(i18n("Gemini API Key not found in api_config.json or arguments."))
                 api_key = input(i18n("Enter your Gemini API Key: ")).strip()

    # Workflow (preserve overrides from burn_only_mode)
    if workflow_choice != "3":  # Don't overwrite if already set by burn_only_mode
        workflow_choice = args.workflow


    # Pipeline Execution
    try:
        # 1. Download & Project Setup
        print(f"DEBUG: Checking input_video state. input_video={input_video}")
        
        if not input_video:
            if not url:
                print(i18n("Error: No URL provided and no existing video selected."))
                sys.exit(1)
                
            print(i18n("Starting download..."))
            download_subs = not args.skip_youtube_subs
            download_result = download_video.download(url, download_subs=download_subs, quality=args.video_quality)
            
            if isinstance(download_result, tuple):
                input_video, project_folder = download_result
            else:
                input_video = download_result
                project_folder = os.path.dirname(input_video)
                
            print(f"DEBUG: Download finished. input_video={input_video}, project_folder={project_folder}")
            
        else:
            # Reuso de video existente
            print("DEBUG: Using existing video logic.")
            project_folder = os.path.dirname(input_video)
            
        print(f"Project Folder: {project_folder}")
        
        # 2. Transcribe
        if workflow_choice == "3":
            print(i18n("Workflow 3: Skipping Transcribe."))
            # We assume transcription exists (SRT/JSON) or we won't need it for 'adjust_subtitles' if it uses 'subs/*.json' which are created by 'cut_segments'
            # Actually 'adjust_subtitles' reads from 'project_folder/subs'.
            # viral_segments = True # Removed to avoid overwritting dict loaded earlier
        else:
            print(i18n("Transcribing with model {}...").format(args.model))
            # Se skip config, args.model é default
            srt_file, tsv_file = transcribe_video.transcribe(input_video, args.model, project_folder=project_folder, language=args.language)

        # 3. Create Viral Segments
        if workflow_choice != "3":
            # Se não carregamos 'viral_segments' lá em cima (ou se era download novo), checamos agora ou criamos
            if not viral_segments:
                # Checagem tardia para downloads novos que por acaso ja tenham json (Ex: URL repetida)
                viral_segments_file_late = os.path.join(project_folder, "viral_segments.txt")
                if os.path.exists(viral_segments_file_late):
                    print(i18n("Found existing viral segments file at {}").format(viral_segments_file_late))
                    if args.skip_prompts:
                        print(i18n("Skipping prompts enabled. Loading existing segments."))
                    else:
                        print(i18n("Loading existing viral segments found at {}").format(viral_segments_file_late))
                    viral_segments = _load_viral_segments_file(viral_segments_file_late)
                    if viral_segments and viral_segments.get("segments"):
                        print(f"DEBUG: Loaded {len(viral_segments['segments'])} segments from file.")
                    else:
                        viral_segments = None
                        print(i18n("Error loading existing JSON: {}. Proceeding to create new segments.").format("formato inválido / sem 'segments'"))
                    
                if not viral_segments:
                    print(i18n("Creating viral segments using {}...").format("MANUAL_WEBUI" if args.manual_webui else ai_backend.upper()))
                    
                    actual_ai_mode = "manual_webui" if args.manual_webui else ai_backend
                    
                    viral_segments = create_viral_segments.create(
                        num_segments, 
                        viral_mode, 
                        themes, 
                        args.min_duration, 
                        args.max_duration,
                        ai_mode=actual_ai_mode,
                        api_key=api_key,
                        project_folder=project_folder,
                        chunk_size_arg=args.chunk_size,
                        model_name_arg=args.ai_model_name,
                        ai_duration=args.ai_duration
                    )

                if viral_segments and viral_segments.get("paused_for_manual"):
                    print(i18n("\n[INFO] Pipeline paused. Waiting for manual AI input via WebUI."))
                    sys.exit(0)
                
                if not viral_segments or not viral_segments.get("segments"):
                    print(i18n("Error: No viral segments were generated."))
                    print(i18n("Possible reasons: API error, Model not found, or empty response."))
                    print(i18n("Stopping execution."))
                    sys.exit(1)
                
                save_json.save_viral_segments(viral_segments, project_folder=project_folder) 

        # 3.5. Fix Raw Segments (missing timestamps)
        if workflow_choice != "3" and viral_segments and "segments" in viral_segments:
            segs = viral_segments.get("segments", [])
            if segs and len(segs) > 0:
                 # Check first segment for duration 0 but having start_time_ref or just check duration
                 first = segs[0]
                 # If duration is effectively 0 and we have a ref tag (or even if we dont, we cant cut 0s video)
                 # We assume if duration is 0, it is raw.
                 if first.get("duration", 0) == 0:
                      print(i18n("Detected raw AI segments without timestamps (Duration 0). Running alignment..."))
                      try:
                          # Load transcript
                          transcript = create_viral_segments.load_transcript(project_folder)
                          # Process (Align)
                          # Use None for output_count to keep all found segments
                          viral_segments = create_viral_segments.process_segments(
                              segs,
                              transcript,
                              (0 if args.ai_duration else args.min_duration),
                              args.max_duration,
                              output_count=None
                          )
                          save_json.save_viral_segments(viral_segments, project_folder=project_folder)
                          print(i18n("Segments aligned and saved."))
                      except Exception as e:
                          print(i18n("Failed to align raw segments: {}").format(e))
                          # If alignment fails, it might crash later, but we tried. 

        # 4. Cut Segments
        # Se workflow for 3, pulamos corte
        if workflow_choice == "3":
            print(i18n("Workflow 3 (Subtitles Only): Skipping Cut and Edit."))
            # Deduzir cuts folder apenas para log
            cuts_folder = os.path.join(project_folder, "cuts")
        else:
            cuts_folder = os.path.join(project_folder, "cuts")
            skip_cutting = False
            
            if os.path.exists(cuts_folder) and os.listdir(cuts_folder):
                print(i18n("\nExisting cuts found in: {}").format(cuts_folder))
                if args.skip_prompts:
                    cut_again_resp = 'no'
                else:
                    cut_again_resp = input(i18n("Cuts already exist. Cut again? (yes/no) [default: no]: ")).strip().lower()
                
                # Default is no (skip) if they just press enter or say no
                if cut_again_resp not in ['y', 'yes']:
                    skip_cutting = True
            
            if skip_cutting:
                print(i18n("Skipping Video Rendering (using existing cuts), but updating Subtitle JSONs..."))
            else:
                print(i18n("Cutting segments..."))

            cut_segments.cut(viral_segments, project_folder=project_folder, skip_video=skip_cutting)
        
        # 5. Workflow Check
        if workflow_choice == "2":
            print(i18n("Cut Only selected. Skipping Face Crop and Subtitles."))
            print(i18n("Process completed! Check your results in: {}").format(project_folder))
            sys.exit(0)

        # 5. Edit Video (Center 9:16 Crop)
        if workflow_choice != "3":
            print(i18n("Cropping videos to vertical 9:16 (centered)..."))
            edit_video.edit(
                project_folder=project_folder,
                segments_data=viral_segments.get("segments", []) if viral_segments else None,
                no_face_mode="zoom"
            )


        else:
            print(i18n("Workflow 3: Skipping Face Crop."))
            # Rename existing files if viral_segments available (since edit_video didn't run)
            if viral_segments and "segments" in viral_segments:
                 segments_data = viral_segments.get("segments", [])
                 final_folder = os.path.join(project_folder, "final")
                 subs_folder = os.path.join(project_folder, "subs")
                 
                 print(i18n("Renaming existing files with titles..."))
                 for idx, segment in enumerate(segments_data):
                     title = segment.get("title", f"Segment_{idx}")
                     safe_title = "".join([c for c in title if c.isalnum() or c in " _-"]).strip()
                     safe_title = safe_title.replace(" ", "_")[:60]
                     
                     new_base_name = f"{idx:03d}_{safe_title}"
                     
                     # 1. MP4
                     old_mp4_name = f"final-output{idx:03d}_processed.mp4"
                     old_mp4_path = os.path.join(final_folder, old_mp4_name)
                     new_mp4_path = os.path.join(final_folder, f"{new_base_name}.mp4")
                     if os.path.exists(old_mp4_path) and not os.path.exists(new_mp4_path):
                         os.rename(old_mp4_path, new_mp4_path)
                         print(f"Renamed (Workflow 3): {old_mp4_name} -> {new_base_name}.mp4")

                     # 2. JSON Sub
                     old_json_name = f"final-output{idx:03d}_processed.json"
                     old_json_path = os.path.join(subs_folder, old_json_name)
                     new_json_path = os.path.join(subs_folder, f"{new_base_name}_processed.json")
                     if os.path.exists(old_json_path) and not os.path.exists(new_json_path):
                         os.rename(old_json_path, new_json_path)
                         print(f"Renamed (Workflow 3): {old_json_name} -> {new_base_name}_processed.json")

        # 6. Subtitles
        burn_subtitles_option = True 
        if burn_subtitles_option:
            print(i18n("Processing subtitles..."))
            # transcribe_cuts removido: JSON de legenda já é gerado no corte
            # transcribe_cuts.transcribe(project_folder=project_folder)

            sub_config = get_subtitle_config(args.subtitle_config)
            

            
            # Passa o dicionário desempacotado como argumentos, mais o project_folder
            try:
                adjust_subtitles.adjust(project_folder=project_folder, **sub_config)
                burn_subtitles.burn(project_folder=project_folder)
            except FileNotFoundError as fnf_error:
                print(i18n("\n[ERROR] Subtitle processing failed: {}").format(str(fnf_error)))
                print(i18n("Tip: If you are using Workflow 3 (Subtitles Only), ensure the 'subs' folder exists and contains valid JSON files."))
                sys.exit(1)
            except Exception as e:
                print(i18n("\n[ERROR] Unexpected error during subtitle processing: {}").format(str(e)))
                raise e
        else:
            print(i18n("Subtitle burning skipped."))

        # Flags do que foi efetivamente embutido nos cortes (base dos botões "Aplicar X").
        applied_watermark = False
        applied_outro = False
        applied_audio_bgm = False
        applied_outro_music = False
        applied_source_volume = False

        # 6.5 Apply Watermark
        if args.watermark_config and os.path.exists(args.watermark_config):
            try:
                with open(args.watermark_config, "r", encoding="utf-8") as f:
                    watermark_cfg = json.load(f)
                if watermark_cfg.get("enabled", False):
                    from scripts import apply_watermark
                    if burn_subtitles_option and os.path.exists(os.path.join(project_folder, "burned_sub")):
                        wm_src_folder = os.path.join(project_folder, "burned_sub")
                    else:
                        wm_src_folder = os.path.join(project_folder, "final")
                    apply_watermark.process_all_videos(
                        source_folder=wm_src_folder,
                        watermark_config=watermark_cfg,
                        output_folder=wm_src_folder
                    )
                    applied_watermark = True
            except Exception as e:
                print(f"Error applying watermark: {e}")

        # 6.6 Append Outro
        if args.outro_config and os.path.exists(args.outro_config):
            try:
                with open(args.outro_config, "r", encoding="utf-8") as f:
                    outro_cfg = json.load(f)
                if outro_cfg.get("enabled", False):
                    from scripts import append_outro
                    # Use burned_sub if subtitles burned, else final
                    if burn_subtitles_option and os.path.exists(os.path.join(project_folder, "burned_sub")):
                        outro_src_folder = os.path.join(project_folder, "burned_sub")
                    else:
                        outro_src_folder = os.path.join(project_folder, "final")
                    
                    append_outro.process_all_videos(
                        source_folder=outro_src_folder,
                        outro_config=outro_cfg,
                        output_folder=outro_src_folder
                    )
                    applied_outro = True
            except Exception as e:
                print(f"Error applying outro: {e}")

        # 7. Apply Audio Overlay
        if args.audio_config and os.path.exists(args.audio_config):
            try:
                with open(args.audio_config, "r", encoding="utf-8") as f:
                    audio_cfg = json.load(f)
                try:
                    source_video_volume = float(audio_cfg.get("source_video_volume", 200.0))
                except (TypeError, ValueError):
                    source_video_volume = 200.0

                outro_music_enabled = bool(audio_cfg.get("outro_music", {}).get("enabled", False))
                should_apply_audio = audio_cfg.get("enabled", False) or abs(source_video_volume - 100.0) > 0.001 or outro_music_enabled
                if should_apply_audio:
                    from scripts import apply_audio
                    if burn_subtitles_option and os.path.exists(os.path.join(project_folder, "burned_sub")):
                        audio_src_folder = os.path.join(project_folder, "burned_sub")
                    else:
                        audio_src_folder = os.path.join(project_folder, "final")
                    apply_audio.process_all_videos(
                        source_folder=audio_src_folder,
                        audio_config=audio_cfg,
                        output_folder=audio_src_folder
                    )
                    applied_audio_bgm = bool(audio_cfg.get("enabled", False))
                    applied_outro_music = outro_music_enabled and applied_outro
                    applied_source_volume = abs(source_video_volume - 100.0) > 0.001
            except Exception as e:
                print(f"Error applying audio overlay: {e}")

        # --- Registrar efeitos embutidos por corte (base dos botões "Aplicar X" da Biblioteca) ---
        try:
            sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui"))
            import render_state
            seg_count = len(viral_segments.get("segments", [])) if (viral_segments and "segments" in viral_segments) else 0
            if seg_count > 0:
                render_state.set_all_segments(
                    project_folder,
                    range(seg_count),
                    {
                        "subtitles": burn_subtitles_option,
                        "watermark": applied_watermark,
                        "outro": applied_outro,
                        "audio_bgm": applied_audio_bgm,
                        "outro_music": applied_outro_music,
                        "source_volume": applied_source_volume,
                    },
                )
        except Exception as st_err:
            print(f"[render_state] não foi possível registrar estado do pipeline: {st_err}")

        # Organização Final (Opcional, pois agora já está tudo em project_folder)
        # organize_output.organize(project_folder=project_folder)
        
        # --- Save Processing Configuration ---
        try:
            # Determine AI Model used
            used_ai_model = args.ai_model_name
            if not used_ai_model:
                used_ai_model = api_config.get("gemini", {}).get("model", "default")

            # Ensure sub_config exists
            current_sub_config = sub_config if 'sub_config' in locals() else get_subtitle_config(args.subtitle_config)

            final_config = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "workflow": workflow_choice,
                "ai_config": {
                    "backend": "gemini",
                    "model_name": used_ai_model,
                    "viral_mode": viral_mode,
                    "themes": themes,
                    "num_segments": num_segments,
                    "chunk_size": args.chunk_size
                },
                "face_config": {
                    "model": "static_center"
                },
                "video_config": {
                    "min_duration": args.min_duration,
                    "max_duration": args.max_duration,
                    "ai_duration": args.ai_duration,
                    "whisper_model": args.model
                },
                "subtitle_config": current_sub_config
            }

            config_save_path = os.path.join(project_folder, "process_config.json")
            with open(config_save_path, "w", encoding="utf-8") as f:
                json.dump(final_config, f, indent=4, ensure_ascii=False)
            print(i18n("Configuration saved to: {}").format(config_save_path))
            
        except Exception as e:
            print(i18n("Error saving configuration JSON: {}").format(e))
        # -------------------------------------

        # -------------------------------------
        # Exportação para Desktop (Cortes IPB)
        try:
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            cortes_ipb_dir = os.path.join(desktop_path, "Cortes IPB")
            os.makedirs(cortes_ipb_dir, exist_ok=True)
            
            export_source = os.path.join(project_folder, "burned_sub")
            if workflow_choice == "2" or not burn_subtitles_option:
                export_source = os.path.join(project_folder, "final")
                if not os.path.exists(export_source):
                    export_source = os.path.join(project_folder, "cuts")
            
            if os.path.exists(export_source):
                exported_count = 0
                for f in os.listdir(export_source):
                    if f.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                        shutil.copy2(os.path.join(export_source, f), os.path.join(cortes_ipb_dir, f))
                        exported_count += 1
                if exported_count > 0:
                    print(i18n("\n[SUCESSO] {} vídeos exportados para a Área de Trabalho em 'Cortes IPB'.").format(exported_count))
        except Exception as e:
            print(f"[AVISO] Não foi possível copiar para a Área de Trabalho: {e}")
        # -------------------------------------

        print(i18n("Process completed! Check your results in: {}").format(project_folder))

    except Exception as e:
        print(i18n("\nAn error occurred: {}").format(str(e)))
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
