
import json
import os
import re
import sys

# Helper to format seconds to HH:MM:SS,mmm
def format_timestamp(seconds):
    millis = int((seconds % 1) * 1000)
    seconds = int(seconds)
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"

# Helper to parse HH:MM:SS,mmm back to seconds
def parse_timestamp(ts_str):
    try:
        # Handle different formats just in case
        ts_str = ts_str.replace(',', '.')
        parts = ts_str.split(':')
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return 0.0
    except:
        return 0.0

def load_transcription_for_editor(json_path):
    """
    Loads `final-outputXXX_processed.json` and flattens it for the Dataframe editor.
    Returns a list of lists: [[Start, End, Text], ...]
    """
    if not os.path.exists(json_path):
        return []

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        segments = data.get('segments', [])
        editor_data = [] # List of [Start, End, Text]

        # We display segments. Each segment has 'words'. 
        # But users want to edit at segment level (the full sentence).
        for seg in segments:
            start_fmt = format_timestamp(seg.get('start', 0))
            end_fmt = format_timestamp(seg.get('end', 0))
            text = seg.get('text', '').strip()
            editor_data.append([start_fmt, end_fmt, text])
            
        return editor_data
    except Exception as e:
        print(f"Error loading JSON for editor: {e}")
        return []

def save_editor_changes(json_path, new_data):
    """
    Reconstructs the complex JSON from the simplified Dataframe edits.
    Smartly redistributes word timestamps if text content changed.
    """
    if not os.path.exists(json_path):
        return "Error: Original file not found."

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            original_json = json.load(f)
        
        original_segments = original_json.get('segments', [])
        
        # new_data is list of [Start, End, Text] from Dataframe
        
        updated_segments = []
        
        for i, row in enumerate(new_data):
            start_str, end_str, new_text = row
            start_sec = parse_timestamp(start_str)
            end_sec = parse_timestamp(end_str)
            
            # Get original segment using timestamp matching to be resilient against added/deleted rows
            orig_seg = {}
            orig_words = []
            best_match = None
            best_score = -1
            
            for o_seg in original_segments:
                score = 0
                o_start = o_seg.get('start', -100)
                if abs(o_start - start_sec) < 0.5:
                    score += 10
                if o_seg.get('text', '').strip() == new_text.strip():
                    score += 10
                if score > best_score and score > 0:
                    best_score = score
                    best_match = o_seg
            
            if best_match:
                orig_seg = best_match
                orig_words = orig_seg.get('words', [])
            elif i < len(original_segments):
                orig_seg = original_segments[i]
                orig_words = orig_seg.get('words', [])
            
            # 1. Update Segment Level
            new_segment = {
                "start": start_sec,
                "end": end_sec,
                "text": new_text
            }
            
            # 2. Reconstruct Words
            # Split new text into words
            new_word_list = new_text.split()
            reconstructed_words = []
            
            if not new_word_list:
                updated_segments.append({**new_segment, "words": []})
                continue

            # Strategy:
            # - If word count matches exactly, assign original timings 1:1.
            # - If mismatch, distribute time proportionally.
            
            if len(new_word_list) == len(orig_words):
                 # Easy mode: Just replace the "word" text, keep timing
                 for j, w_text in enumerate(new_word_list):
                     orig_w = orig_words[j]
                     reconstructed_words.append({
                         "word": w_text,
                         "start": orig_w.get("start", start_sec),
                         "end": orig_w.get("end", end_sec),
                         "score": orig_w.get("score", 0.99)
                     })
            else:
                # Hard mode: Length-proportional Interpolation
                duration = end_sec - start_sec
                if duration <= 0: duration = 0.1
                
                total_chars = max(sum(len(w) for w in new_word_list), 1)
                
                current_time = start_sec
                for w_text in new_word_list:
                    word_duration = (len(w_text) / total_chars) * duration
                    w_end = current_time + word_duration
                    reconstructed_words.append({
                        "word": w_text,
                        "start": round(current_time, 3),
                        "end": round(w_end, 3),
                        "score": 0.99
                    })
                    current_time = w_end
            
            new_segment["words"] = reconstructed_words
            updated_segments.append(new_segment)
            
        # Update final JSON structure
        original_json["segments"] = updated_segments
        
        # Save Text back to file
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(original_json, f, indent=4, ensure_ascii=False)
            
        return "Success: Subtitles updated."
        
    except Exception as e:
        return f"Error saving changes: {e}"

def list_editable_files(project_dir):
    """
    Scans VIRALS/{project_name}/subs/ for json files.
    """
    if not os.path.exists(project_dir):
        return []
    
    subs_dir = os.path.join(project_dir, 'subs')
    if not os.path.exists(subs_dir):
        return []
        
    # Look for files matching 'final-output...processed.json'
    files = [f for f in os.listdir(subs_dir) if f.endswith('_processed.json')]
    return sorted(files)

def render_specific_video(json_full_path):
    """
    1. Regenerate ASS for this specific JSON file.
    2. Burn ASS into the corresponding Video file.
    """
    if not json_full_path or not os.path.exists(json_full_path):
        return "Error: JSON file not found."

    project_folder = os.path.dirname(os.path.dirname(json_full_path)) # ../../ from subs/file.json
    
    # Identify key paths
    filename = os.path.basename(json_full_path)
    base_name = os.path.splitext(filename)[0] # final-output000_processed
    
    # Assuming standard structure
    ass_path = os.path.join(project_folder, "subs_ass", f"{base_name}.ass")
    os.makedirs(os.path.dirname(ass_path), exist_ok=True)
    
    # Video Path?
    # burn_subtitles iterates 'final' folder and matches name.
    # The JSON is "final-output000_processed.json".
    # The video in 'final' usually is "fina-output000.mp4" or similar?
    # Wait, edit_video generates "final-output000_processed.mp4"?
    # Let's assume the name matches exactly the JSON name.
    
    # Output path
    burned_folder = os.path.join(project_folder, "burned_sub")
    os.makedirs(burned_folder, exist_ok=True)
    output_video_path = os.path.join(burned_folder, f"{base_name}_subtitled.mp4")

    # Try finding the video file
    video_folder = os.path.join(project_folder, "final")
    if not os.path.exists(video_folder):
        video_folder = os.path.join(project_folder, "cuts") # Fallback for Cut Only mode
        
    video_candidate = os.path.join(video_folder, f"{base_name}.mp4")
    
    if not os.path.exists(video_candidate):
        # Try stripping "_processed" (common suffix for subtitle files)
        if base_name.endswith("_processed"):
             clean_name = base_name.replace("_processed", "")
             candidate_2 = os.path.join(video_folder, f"{clean_name}.mp4")
             if os.path.exists(candidate_2):
                 video_candidate = candidate_2
        
        # If still not found, try regex strategies
        if not os.path.exists(video_candidate) and os.path.exists(video_folder):
            # Strategy A: 'output123' pattern
            match = re.search(r"output(\d+)", base_name)
            
            # Strategy B: '000_Name' pattern (digits at start)
            if not match:
                match = re.search(r"^(\d+)_", base_name)
            
            if match:
                vid_id = match.group(1)
                # Look for file containing this ID
                files = os.listdir(video_folder)
                found = None
                for f in files:
                    if (f"output{vid_id}" in f or f.startswith(f"{vid_id}_")) and f.endswith(".mp4") and "subtitled" not in f:
                         found = os.path.join(video_folder, f)
                         break
                if found:
                    video_candidate = found
                else:
                    return f"Error: Could not find video file for ID {vid_id} (from {base_name}) in {video_folder}"
            else:
                 return f"Error: Could not determine video ID from {base_name}"
    
    # Output path
    burned_folder = os.path.join(project_folder, "burned_sub")
    os.makedirs(burned_folder, exist_ok=True)
    output_video_path = os.path.join(burned_folder, f"{base_name}_subtitled.mp4")

    # Load the heavier processing modules only when a render is requested.
    # This keeps the WebUI startup and tab switching light in Colab.
    from main_improved import get_subtitle_config
    from scripts import adjust_subtitles as adjust
    from scripts import burn_subtitles as burn

    # Load Config
    try:
        # Try to load temp config from root, else default
        temp_config = os.path.join(os.path.dirname(os.path.dirname(project_folder)), "temp_subtitle_config.json")
        # .. from VIRALS/proj -> VIRALS -> root? No.
        # project_folder is VIRALS/proj.
        # root is ../../
        root_dir = os.path.dirname(os.path.dirname(project_folder))
        # actually project_folder is c:\...\VIRALS\proj.
        # root is c:\...\
        
        # Safer: use main_improved working dir if imported from there or app
        config_path = os.path.join(root_dir, "temp_subtitle_config.json")
        if not os.path.exists(config_path):
             config_path = None
        
        config = get_subtitle_config(config_path)
        # print(f"DEBUG: Loaded subt config: H={config.get('highlight_color')} B={config.get('base_color')}")
        # Ensure 'uppercase' exists as it's not in default config of main_improved
        config['uppercase'] = config.get('uppercase', False)
        
        # Load Face Modes
        face_modes = {}
        modes_file = os.path.join(project_folder, "face_modes.json")
        if os.path.exists(modes_file):
            with open(modes_file, "r") as f:
                face_modes = json.load(f)
        
        # 1. Generate ASS
        adjust.generate_ass_from_file(json_full_path, ass_path, project_folder, **config, face_modes=face_modes)
        
        # 2. Burn Video
        success, msg = burn.burn_video_file(video_candidate, ass_path, output_video_path)
        
        if success:
             # Post-processing (Watermark, Outro, Audio config)
             try:
                 import tempfile
                 import shutil
                 
                 # Create a temp dir to isolate this single video for process_all_videos scripts
                 temp_proc_dir = tempfile.mkdtemp()
                 temp_vid_path = os.path.join(temp_proc_dir, os.path.basename(output_video_path))
                 shutil.copy2(output_video_path, temp_vid_path)
                 
                 # Watermark
                 watermark_cfg_path = os.path.join(root_dir, "watermark_config.json")
                 if os.path.exists(watermark_cfg_path):
                     with open(watermark_cfg_path, "r", encoding="utf-8") as f:
                         wm_cfg = json.load(f)
                     if wm_cfg.get("enabled", False):
                         from scripts import apply_watermark
                         apply_watermark.process_all_videos(temp_proc_dir, wm_cfg, temp_proc_dir)
                 
                 # Outro
                 outro_cfg_path = os.path.join(root_dir, "outro_config.json")
                 if os.path.exists(outro_cfg_path):
                     with open(outro_cfg_path, "r", encoding="utf-8") as f:
                         outro_cfg = json.load(f)
                     if outro_cfg.get("enabled", False):
                         from scripts import append_outro
                         append_outro.process_all_videos(temp_proc_dir, outro_cfg, temp_proc_dir)
                         
                 # Audio Overlay
                 audio_cfg_path = os.path.join(root_dir, "audio_config.json")
                 if os.path.exists(audio_cfg_path):
                     with open(audio_cfg_path, "r", encoding="utf-8") as f:
                         audio_cfg = json.load(f)
                     if audio_cfg.get("enabled", False):
                         from scripts import apply_audio
                         apply_audio.process_all_videos(temp_proc_dir, audio_cfg, temp_proc_dir)
                 
                 # Copy back to burned_sub folder
                 if os.path.exists(temp_vid_path):
                     shutil.copy2(temp_vid_path, output_video_path)
                 
                 # Cleanup temp dir
                 shutil.rmtree(temp_proc_dir)
                 
             except Exception as pp_err:
                 print(f"Error in post-processing during subtitle manual render: {pp_err}")

             # Exportation to Desktop (Cortes IPB)
             desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
             cortes_ipb_dir = os.path.join(desktop_path, "Cortes IPB")
             os.makedirs(cortes_ipb_dir, exist_ok=True)
             
             export_path = os.path.join(cortes_ipb_dir, os.path.basename(output_video_path))
             try:
                 import shutil
                 shutil.copy2(output_video_path, export_path)
                 export_msg = f" (Also saved to Cortes IPB: {os.path.basename(export_path)})"
             except Exception as cp_err:
                 export_msg = f" (Failed to copy to Cortes IPB: {cp_err})"
             
             return f"Success! Rendered: {os.path.basename(output_video_path)}{export_msg}"
        else:
             return f"Render Failed: {msg}"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Critical Error: {e}"
