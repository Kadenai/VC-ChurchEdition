import os
import subprocess
import shutil
import tempfile

try:
    from scripts.edit_video import get_best_encoder
except ImportError:
    def get_best_encoder():
        try:
            result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True)
            output = result.stdout
            if "h264_nvenc" in output: return ("h264_nvenc", "fast")
            if "h264_amf" in output: return ("h264_amf", "speed")
            if "h264_qsv" in output: return ("h264_qsv", "veryfast")
            if "h264_videotoolbox" in output: return ("h264_videotoolbox", "default")
        except:
            pass
        return ("libx264", "ultrafast")

def apply_watermark_to_video(input_video, image_path, x, y, scale, opacity, output_video):
    encoder, preset = get_best_encoder()
    
    # We apply the overlay and keep audio intact.
    filter_complex = f"[1:v]scale=iw*({scale}/100):ih*({scale}/100),format=rgba,colorchannelmixer=aa={opacity}/100.0[wm];[0:v][wm]overlay={x}:{y}[v]"
    
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", input_video,
        "-i", image_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", encoder, "-preset", preset, "-b:v", "5M",
        "-c:a", "copy",
        output_video
    ]
    
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "Unknown ffmpeg error").strip()
        print(f"Error applying watermark to {input_video}: {error_text}")
        return False
    return True

def process_all_videos(source_folder, watermark_config, output_folder):
    """
    Applies the configured watermark to all mp4 videos in the source_folder.
    """
    image_path = watermark_config.get("watermark_image_path")
    if not image_path or not os.path.exists(image_path):
        print("Watermark image path not configured or not found. Skipping watermark.")
        return
        
    print(f"Applying Watermark to all videos in {source_folder}...")
    
    x = watermark_config.get("position_x", 480)
    y = watermark_config.get("position_y", 0)
    scale = watermark_config.get("scale", 15)
    opacity = watermark_config.get("opacity", 30)
    
    os.makedirs(output_folder, exist_ok=True)
    temp_dir = tempfile.mkdtemp()
    
    processed_count = 0
    files = [f for f in os.listdir(source_folder) if f.lower().endswith(('.mp4', '.mkv', '.avi')) and not f.startswith("temp_")]
    
    for filename in files:
        main_video_path = os.path.join(source_folder, filename)
        temp_output_path = os.path.join(temp_dir, f"temp_wm_{filename}")
        
        print(f"Adding Watermark to {filename}...")
        if apply_watermark_to_video(main_video_path, image_path, x, y, scale, opacity, temp_output_path):
            final_output_path = os.path.join(output_folder, filename)
            try:
                if os.path.exists(final_output_path):
                    os.remove(final_output_path)
                shutil.move(temp_output_path, final_output_path)
                processed_count += 1
            except Exception as e:
                print(f"Could not replace original file {filename}: {e}")
                
    try:
        shutil.rmtree(temp_dir)
    except:
        pass
        
    print(f"Watermark process completed. Applied to {processed_count} videos.")
