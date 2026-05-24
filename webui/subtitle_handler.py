
import os
import re
import subprocess
import gradio as gr
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = os.path.dirname(CURRENT_DIR) # ViralCutter root
import sys
sys.path.append(WORKING_DIR)
from i18n.i18n import I18nAuto
i18n = I18nAuto()

# Subtitle Presets
SUBTITLE_PRESETS = {
    "Church Clear": {
        "font_name": "Montserrat",
        "font_size": 30,
        "base_color": "#FFFFFF",
        "highlight_color": "#FFFFFF",
        "outline_color": "#000000",
        "outline_thickness": 1,
        "shadow_color": "#000000",
        "shadow_size": 1,
        "bold": True,
        "italic": False,
        "uppercase": False,
        "highlight_size": 30,
        "words_per_block": 4,
        "gap_limit": 0.6,
        "mode": "no_highlight",
        "underline": False,
        "strikeout": False,
        "border_style": 1,
        "vertical_position": 140,
        "margin_h": 35,
        "alignment": 2,
        "remove_punctuation": False
    }
}

def generate_preview_html(font, size, color, highlight, outline, outline_thick, shadow, shadow_sz, bold, italic, upper, 
                          h_size, w_block, gap, mode, under, strike, border_s, vert_pos, margin_h, align, remove_punc):
    
    # Debug inputs
    #print(f"DEBUG_HTML: Inputs - Color: {color}, Highlight: {highlight}, Outline: {outline}")

    def sanitize_color(c):
        if not c: return "#FFFFFF"
        clean = c.lstrip('#').strip()
        # Handle RGB/RGBA
        if clean.lower().startswith("rgb"):
            try:
                nums = re.findall(r"[\d\.]+", clean)
                if len(nums) >= 3:
                     r = int(float(nums[0]))
                     g = int(float(nums[1]))
                     b = int(float(nums[2]))
                     r = max(0, min(255, r))
                     g = max(0, min(255, g))
                     b = max(0, min(255, b))
                     ret = f"#{r:02X}{g:02X}{b:02X}"
                     # print(f"DEBUG_HTML: Sanitized {c} -> {ret}")
                     return ret
            except Exception as e:
                print(f"DEBUG_HTML: Sanitize Error: {e}")
                pass
        
        # Ensure # prefix for standard hex if missing
        if not c.startswith("#") and not c.startswith("rgb"):
             return f"#{c}"
             
        return c 

    color = sanitize_color(color)
    highlight = sanitize_color(highlight)
    outline = sanitize_color(outline)
    shadow = sanitize_color(shadow)
    
    #print(f"DEBUG_HTML: Final Colors - Color: {color}, Highlight: {highlight}")

    weight = "bold" if bold else "normal"
    style = "italic" if italic else "normal"
    transform = "uppercase" if upper else "none"
    decorations = []
    if under: decorations.append("underline")
    if strike: decorations.append("line-through")
    decoration = " ".join(decorations) if decorations else "none"
    
    # Force larger preview size regardless of input size
    # We maintain ratio between highlight and base
    base_preview_px = 40
    ratio = 1.0
    if size > 0:
        ratio = h_size / size
    highlight_preview_px = base_preview_px * ratio
    
    # Avoid extreme ratios in preview
    if highlight_preview_px > base_preview_px * 2: highlight_preview_px = base_preview_px * 2
    
    # Border Style 3 is Opaque Box usually in ASS, here we can simulate background
    bg_style = "background-color: rgba(0,0,0,0.6); padding: 5px 10px; border-radius: 4px;" if border_s == 3 else ""
    
    # Handle Content based on Mode
    # Handle Content based on Mode
    content_html = ""
    preview_word = i18n("PREVIEW")
    if mode == "word_by_word":
        # Only show the active word
        content_html = f'<span style="font-size: {highlight_preview_px}px; color: {highlight}; -webkit-text-stroke: {outline_thick}px {outline};">{preview_word}</span>'
    elif mode == "no_highlight":
         # No highlight difference
         span_html = f'<span style="font-size: {base_preview_px}px; color: {color}; -webkit-text-stroke: {outline_thick}px {outline};">{preview_word}</span>'
         content_html = i18n("This is a {} of your subtitles").format(span_html)
    else:
        # Default Highlight mode
        span_html = f'<span style="font-size: {highlight_preview_px}px; color: {highlight}; -webkit-text-stroke: {outline_thick}px {outline};">{preview_word}</span>'
        content_html = i18n("This is a {} of your subtitles").format(span_html)

    html = f"""
    <div style="
        background-color: #222; 
        background-image: linear-gradient(45deg, #2a2a2a 25%, transparent 25%, transparent 75%, #2a2a2a 75%, #2a2a2a), 
                          linear-gradient(45deg, #2a2a2a 25%, transparent 25%, transparent 75%, #2a2a2a 75%, #2a2a2a);
        background-size: 20px 20px;
        background-position: 0 0, 10px 10px;
        padding: 40px; 
        border-radius: 8px; 
        text-align: center; 
        font-family: '{font}', sans-serif;
        margin-bottom: 10px;
        border: 1px solid #444;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 120px;
    ">
        <span style="
            font-size: {base_preview_px}px;
            color: {color};
            font-weight: {weight};
            font-style: {style};
            text-transform: {transform};
            text-decoration: {decoration};
            -webkit-text-stroke: {outline_thick}px {outline};
            text-shadow: {shadow_sz}px {shadow_sz}px 0 {shadow};
            {bg_style}
            line-height: 1.2;
        ">
            {content_html}
        </span>
    </div>
    """
    return html

def apply_preset(preset):
    if preset in SUBTITLE_PRESETS:
        p = SUBTITLE_PRESETS[preset]
        return (
            p["font_name"], p["font_size"], p["base_color"], p["highlight_color"], 
            p["outline_color"], p["outline_thickness"], p["shadow_color"], 
            p["shadow_size"], p["bold"], p["italic"], p["uppercase"],
            p["highlight_size"], p["words_per_block"], p["gap_limit"], p["mode"],
            p["underline"], p["strikeout"], p["border_style"],
            p.get("vertical_position", 210), p.get("margin_h", 15), p.get("alignment", 2),
            p.get("remove_punctuation", True)
        )
    return (gr.skip(),) * 22 

import scripts.adjust_subtitles as adjust

def render_preview_video(font, size, color, highlight, outline, outline_thick, shadow, shadow_sz, bold, italic, upper,
                         h_size, w_block, gap, mode, under, strike, border_s, vert_pos, margin_h, align, remove_punc):
    # Helper to convert HEX to ASS color &HBBGGRR&
    def hex_to_ass(h):
        try:
            with open("debug_preview.log", "a") as f:
                f.write(f"PREVIEW INPUT: '{h}'\n")
        except: pass
        
        if not h: return "&H00FFFFFF&"
        
        hex_clean = h.lstrip('#').strip()
        
        # Handle rgb/rgba
        if hex_clean.lower().startswith("rgb"):
            try:
                # regex to capture numbers including floats
                nums = re.findall(r"[\d\.]+", hex_clean)
                if len(nums) >= 3:
                     r = int(float(nums[0]))
                     g = int(float(nums[1]))
                     b = int(float(nums[2]))
                     # Clamp just in case
                     r = max(0, min(255, r))
                     g = max(0, min(255, g))
                     b = max(0, min(255, b))
                     return f"&H00{b:02X}{g:02X}{r:02X}&".upper()
            except: pass
            
        if len(hex_clean) == 3:
            hex_clean = "".join([c*2 for c in hex_clean])
            
        if len(hex_clean) == 6:
            return f"&H00{hex_clean[4:6]}{hex_clean[2:4]}{hex_clean[0:2]}&".upper()
            
        return "&H00FFFFFF&"
    
    base_c = hex_to_ass(color)
    high_c = hex_to_ass(highlight)
    out_c = hex_to_ass(outline)
    shad_c = hex_to_ass(shadow)
    
    # Paths
    preview_dir = os.path.join(CURRENT_DIR, "PREVIEW")
    os.makedirs(preview_dir, exist_ok=True)
    
    json_template = os.path.join(CURRENT_DIR, "preview.json")
    if not os.path.exists(json_template):
        print(f"Error: {json_template} not found.")
        return None
        
    ass_path = os.path.join(preview_dir, "preview.ass")
    out_vid_path = os.path.join(preview_dir, "preview_render.mp4")
    
    # Prepare ASS Bool Values (-1=True, 0=False)
    bold_val = "-1" if bold else "0"
    italic_val = "-1" if italic else "0"
    under_val = "-1" if under else "0"
    strike_val = "-1" if strike else "0"
    
    try:
        # Generate ASS from JSON using the shared script logic
        # this ensures consistency with the actual video generation
        adjust.generate_ass_from_file(
            input_path=json_template,
            output_path=ass_path,
            project_folder=preview_dir, # Dummy folder
            base_color=base_c,
            base_size=size,
            highlight_size=h_size,
            highlight_color=high_c,
            words_per_block=int(w_block),
            gap_limit=gap,
            mode=mode,
            vertical_position=vert_pos,
            margin_h=margin_h,
            alignment=align,
            font=font,
            outline_color=out_c,
            shadow_color=shad_c,
            bold=bold_val,
            italic=italic_val,
            underline=under_val,
            strikeout=strike_val,
            border_style=border_s,
            outline_thickness=outline_thick,
            shadow_size=shadow_sz,
            uppercase=upper,
            face_modes={}, 
            remove_punctuation=remove_punc
        )
        
        # Prepare safe path for ffmpeg filter: escape windows backslashes and colon
        safe_ass_path = ass_path.replace('\\', '/').replace(':', '\\:')
        
        # Render with ffmpeg
        # Background color #333333 to match UI roughly. 
        # Resolution 480x854 (9:16)
        cmd = [
            "ffmpeg", "-y", 
            "-f", "lavfi", "-i", "color=c=0x333333:s=480x854:d=2.4",
            "-vf", f"ass='{safe_ass_path}'",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an",
            out_vid_path
        ]

        result = subprocess.run(cmd, cwd=WORKING_DIR, capture_output=True, text=True)
        if result.returncode != 0:
            err_text = (result.stderr or result.stdout or "Unknown ffmpeg error").strip()
            print(f"Preview ffmpeg failed: {err_text[:800]}")
            return gr.update(value=None, autoplay=False)
        
        if os.path.exists(out_vid_path):
            import shutil
            # Create a timestamped copy to force browser cache refresh
            import time
            timestamp = int(time.time())
            cache_bust_path = os.path.join(preview_dir, f"preview_render_{timestamp}.mp4")
            shutil.copy(out_vid_path, cache_bust_path)
            
            # Clean old files
            try:
                for f in os.listdir(preview_dir):
                    if f.startswith("preview_render_") and f.endswith(".mp4") and f != os.path.basename(cache_bust_path):
                        try:
                            os.remove(os.path.join(preview_dir, f))
                        except: pass
            except: pass
            
            return gr.update(value=cache_bust_path, autoplay=True)
            
    except Exception as e:
        print(f"Preview Gen Error: {e}")
        import traceback
        traceback.print_exc()
        
    return None
