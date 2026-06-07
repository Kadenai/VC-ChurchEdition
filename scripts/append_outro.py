import os
import subprocess
import json
import tempfile
import shutil
import cv2
import numpy as np

try:
    from scripts.edit_video import get_best_encoder
except ImportError:
    # Fallback if cannot import
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

def get_video_duration(video_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except Exception as e:
        print(f"Error getting duration for {video_path}: {e}")
        return 0.0


def has_audio_stream(video_path):
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=index", "-of", "csv=p=0", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


HW_ENCODERS = ("h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox")


def _cmd_uses_hw_encoder(cmd):
    for i, tok in enumerate(cmd):
        if tok == "-c:v" and i + 1 < len(cmd) and cmd[i + 1] in HW_ENCODERS:
            return True
    return False


def _swap_to_cpu_encoder(cmd):
    """Return a copy of cmd with any hardware H.264 encoder replaced by libx264/ultrafast."""
    new_cmd = list(cmd)
    for i, tok in enumerate(new_cmd):
        if tok == "-c:v" and i + 1 < len(new_cmd) and new_cmd[i + 1] in HW_ENCODERS:
            new_cmd[i + 1] = "libx264"
            if i + 2 < len(new_cmd) and new_cmd[i + 2] == "-preset" and i + 3 < len(new_cmd):
                new_cmd[i + 3] = "ultrafast"
    return new_cmd


def run_ffmpeg_command(cmd, context):
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        # Hardware encoders (NVENC/AMF/QSV) fail intermittently when the GPU is
        # busy or the session limit is hit. Retry once on CPU before giving up so
        # the outro is not silently skipped for some videos but not others.
        if _cmd_uses_hw_encoder(cmd):
            print(f"{context}: hardware encoder failed, retrying with CPU (libx264)...")
            cpu_result = subprocess.run(_swap_to_cpu_encoder(cmd), check=False, capture_output=True, text=True)
            if cpu_result.returncode == 0:
                return True
            result = cpu_result
        error_text = (result.stderr or result.stdout or "Unknown ffmpeg error").strip()
        print(f"{context}: {error_text}")
        return False
    return True

def compose_outro_with_image(outro_video, image_path, x, y, scale, output_path, rounded_corners=0, outro_volume=100):
    """
    Composes the image over the outro video and normalizes its format.

    `outro_volume` is a percentage (100 = original level) applied to the outro's
    own audio track when it has one. It is ignored when the outro is silent.
    """
    encoder, preset = get_best_encoder()
    
    temp_img_path = None
    if image_path and os.path.exists(image_path) and rounded_corners > 0:
        try:
            img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
            if img is not None:
                if len(img.shape) == 3 and img.shape[2] == 3:
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                h, w = img.shape[:2]
                mask = np.zeros((h, w), dtype=np.uint8)
                radius = min(int(rounded_corners * min(w, h) / 100), min(w, h) // 2)
                if radius > 0:
                    cv2.rectangle(mask, (radius, 0), (w - radius, h), 255, -1)
                    cv2.rectangle(mask, (0, radius), (w, h - radius), 255, -1)
                    cv2.circle(mask, (radius, radius), radius, 255, -1)
                    cv2.circle(mask, (w - radius, radius), radius, 255, -1)
                    cv2.circle(mask, (radius, h - radius), radius, 255, -1)
                    cv2.circle(mask, (w - radius, h - radius), radius, 255, -1)
                    if len(img.shape) == 3 and img.shape[2] == 4:
                        img[:, :, 3] = cv2.bitwise_and(img[:, :, 3], mask)
                    
                temp_img_fd, temp_img_path = tempfile.mkstemp(suffix=".png")
                os.close(temp_img_fd)
                cv2.imwrite(temp_img_path, img)
                image_path = temp_img_path
        except Exception as e:
            print(f"Error applying rounded corners: {e}")
    
    outro_has_audio = has_audio_stream(outro_video)
    try:
        volume_percent = float(outro_volume)
    except (TypeError, ValueError):
        volume_percent = 100.0
    volume_percent = max(0.0, min(200.0, volume_percent))
    volume_factor = volume_percent / 100.0

    has_image = bool(image_path and os.path.exists(image_path))

    # We normalize to 1080x1920, 30fps, yuv420p to ensure xfade compatibility later
    base_v = "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p"
    filter_parts = []
    if has_image:
        filter_parts.append(f"{base_v}[base]")
        filter_parts.append(f"[1:v]scale=iw*({scale}/100):ih*({scale}/100)[img]")
        filter_parts.append(f"[base][img]overlay={x}:{y}[v]")
    else:
        filter_parts.append(f"{base_v}[v]")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", outro_video]
    if has_image:
        cmd.extend(["-i", image_path])

    if outro_has_audio:
        # Apply the configured outro volume to its own audio track
        filter_parts.append(f"[0:a]volume={volume_factor}[aout]")
        audio_map = "[aout]"
        use_shortest = False
    else:
        # No audio in outro: add a silent track so later acrossfade/concat works
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
        silent_idx = 2 if has_image else 1
        audio_map = f"{silent_idx}:a"
        use_shortest = True  # stop at shortest to not let anullsrc go forever

    filter_complex = "; ".join(filter_parts)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", audio_map,
        "-c:v", encoder, "-preset", preset, "-b:v", "5M",
        "-c:a", "aac", "-b:a", "192k",
    ])
    if use_shortest:
        cmd.append("-shortest")
    cmd.append(output_path)

    success = run_ffmpeg_command(cmd, "Error composing outro")
        
    if temp_img_path and os.path.exists(temp_img_path):
        try:
            os.remove(temp_img_path)
        except:
            pass
            
    return success

def append_outro_to_video(main_video, composed_outro, fade_duration, output_path):
    duration = get_video_duration(main_video)
    if duration <= 0:
        print(f"Error: Invalid duration for main video: {main_video}")
        return False

    if duration <= fade_duration:
        print(f"Warning: Main video ({duration}s) too short for fade ({fade_duration}s). Fallback to standard concat.")
        fade_duration = 0
    
    offset = max(0.0, duration - fade_duration)
    encoder, preset = get_best_encoder()
    
    # We must ensure both videos are strictly 30 fps and same SAR for xfade
    filter_complex = (
        f"[0:v]fps=30,scale=1080:1920,format=yuv420p,setsar=1[v0]; "
        f"[1:v]fps=30,scale=1080:1920,format=yuv420p,setsar=1[v1]; "
    )

    main_has_audio = has_audio_stream(main_video)
    outro_has_audio = has_audio_stream(composed_outro)
    outro_duration = max(0.1, get_video_duration(composed_outro))

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", main_video,
        "-i", composed_outro,
    ]

    next_input_idx = 2
    main_audio_label = "[0:a]"
    outro_audio_label = "[1:a]"

    if not main_has_audio:
        cmd.extend([
            "-f", "lavfi",
            "-t", f"{max(0.1, duration):.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"
        ])
        main_audio_label = f"[{next_input_idx}:a]"
        next_input_idx += 1

    if not outro_has_audio:
        cmd.extend([
            "-f", "lavfi",
            "-t", f"{outro_duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"
        ])
        outro_audio_label = f"[{next_input_idx}:a]"
        next_input_idx += 1
    
    if fade_duration > 0:
        filter_complex += f"[v0][v1]xfade=transition=fade:duration={fade_duration}:offset={offset}[v]; "
        filter_complex += f"{main_audio_label}{outro_audio_label}acrossfade=d={fade_duration}[a]"
    else:
        filter_complex += f"[v0]{main_audio_label}[v1]{outro_audio_label}concat=n=2:v=1:a=1[v][a]"

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", encoder, "-preset", preset, "-b:v", "5M",
        "-c:a", "aac", "-b:a", "192k",
        output_path
    ])

    return run_ffmpeg_command(cmd, f"Error applying outro to {main_video}")

def process_all_videos(source_folder, outro_config, output_folder):
    """
    Applies the configured outro to all mp4 videos in the source_folder.
    """
    outro_video = outro_config.get("outro_video_path")
    if not outro_video or not os.path.exists(outro_video):
        print("Outro video path not configured or not found. Skipping outro.")
        return
    
    print(f"Applying Outro/Ending to all videos in {source_folder}...")
    
    image_path = outro_config.get("overlay_image_path")
    x = outro_config.get("position_x", 179)
    y = outro_config.get("position_y", 886)
    scale = outro_config.get("scale", 42)
    fade_duration = outro_config.get("fade_duration", 1)
    rounded_corners = outro_config.get("rounded_corners", 10)
    outro_volume = outro_config.get("outro_volume", 100)

    os.makedirs(output_folder, exist_ok=True)

    # 1. Compose the Outro once
    temp_dir = tempfile.mkdtemp()
    composed_outro = os.path.join(temp_dir, "composed_outro.mp4")

    print("Preparing Outro overlay cache...")
    success = compose_outro_with_image(outro_video, image_path, x, y, scale, composed_outro, rounded_corners, outro_volume)
    if not success:
        print("Failed to compose outro overlay. Aborting outro step.")
        shutil.rmtree(temp_dir)
        return

    # 2. Iterate through videos
    processed_count = 0
    files = [f for f in os.listdir(source_folder) if f.lower().endswith(('.mp4', '.mkv', '.avi')) and not f.startswith("temp_")]
    
    for filename in files:
        
        main_video_path = os.path.join(source_folder, filename)
        temp_output_path = os.path.join(temp_dir, f"temp_out_{filename}")
        
        print(f"Adding Outro to {filename}...")
        if append_outro_to_video(main_video_path, composed_outro, fade_duration, temp_output_path):
            # Replace the original file with the new one
            final_output_path = os.path.join(output_folder, filename)
            try:
                if os.path.exists(final_output_path):
                    os.remove(final_output_path)
                shutil.move(temp_output_path, final_output_path)
                processed_count += 1
            except Exception as e:
                print(f"Could not replace original file {filename}: {e}")
    
    # Cleanup
    try:
        shutil.rmtree(temp_dir)
    except:
        pass
    
    print(f"Outro/Ending process completed. Applied to {processed_count} videos.")
