import cv2
import numpy as np
import os
import json
import glob
import subprocess
from scripts.one_face import resize_with_padding, crop_center_zoom


# Global cache for encoder
CACHED_ENCODER = None

def get_best_encoder():
    global CACHED_ENCODER
    if CACHED_ENCODER: return CACHED_ENCODER

    try:
        # Check available encoders
        result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True)
        output = result.stdout

        # Priority: NVENC (NVIDIA) > AMF (AMD) > QSV (Intel) > CPU
        if "h264_nvenc" in output:
            print("Encoder Detected: NVIDIA (h264_nvenc)")
            CACHED_ENCODER = ("h264_nvenc", "fast") # p1-p7 presets could be used but 'fast' maps well
            return CACHED_ENCODER

        if "h264_amf" in output:
            print("Encoder Detected: AMD (h264_amf)")
            CACHED_ENCODER = ("h264_amf", "speed") # quality, speed, balanced
            return CACHED_ENCODER

        if "h264_qsv" in output:
             print("Encoder Detected: Intel QSV (h264_qsv)")
             CACHED_ENCODER = ("h264_qsv", "veryfast")
             return CACHED_ENCODER

        # Mac OS (VideoToolbox)
        if "h264_videotoolbox" in output:
             print("Encoder Detected: MacOS (h264_videotoolbox)")
             CACHED_ENCODER = ("h264_videotoolbox", "default")
             return CACHED_ENCODER

    except Exception as e:
        print(f"Error checking encoders: {e}")

    print("Encoder Detected: CPU (libx264)")
    CACHED_ENCODER = ("libx264", "ultrafast")
    return CACHED_ENCODER


def generate_short_fallback(input_file, output_file, index, project_folder, final_folder, no_face_mode="zoom"):
    """Crop the video to 9:16: Center Crop (Zoom) by default, or Padding (black bars)."""
    print(f"Processing (Center 9:16): {input_file} | Mode: {no_face_mode}")
    cap = cv2.VideoCapture(input_file)
    if not cap.isOpened():
        print(f"Error opening video: {input_file}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Target dimensions (9:16)

    target_width = 1080
    target_height = 1920

    encoder_name, encoder_preset = get_best_encoder()

    # Use FFmpeg Pipe instead of cv2.VideoWriter to avoid OpenCV backend errors
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-loglevel', 'error', '-hide_banner', '-stats',
        '-threads', '12',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-s', f'{target_width}x{target_height}',
        '-pix_fmt', 'bgr24',
        '-r', str(fps),
        '-i', '-',
        '-c:v', encoder_name,
        '-preset', encoder_preset,
        '-pix_fmt', 'yuv420p',
    ]

    # If using hardware encoder, set bitrate to ensure quality (BEFORE output file)
    if "nvenc" in encoder_name or "amf" in encoder_name:
         ffmpeg_cmd.extend(["-b:v", "5M"])

    ffmpeg_cmd.append(output_file)

    process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if no_face_mode == "padding":
             result = resize_with_padding(frame)
        else:
             result = crop_center_zoom(frame)

        try:
            # Write raw bytes to ffmpeg stdin
            process.stdin.write(result.tobytes())
        except Exception as e:
            print(f"Error writing frame to ffmpeg pipe: {e}")
            pass



    cap.release()
    process.stdin.close()
    return_code = process.wait()
    if return_code != 0:
        print(f"Error: ffmpeg process failed with exit code {return_code} for {input_file}")
        return

    finalize_video(input_file, output_file, index, fps, project_folder, final_folder)

def finalize_video(input_file, output_file, index, fps, project_folder, final_folder):
    """Mux audio and video."""
    audio_file = os.path.join(project_folder, "cuts", f"output-audio-{index}.aac")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-threads", "12", "-i", input_file, "-vn", "-acodec", "copy", audio_file],
                   check=False, capture_output=True)

    # Se o stream original não for AAC, o copy falha e o corte sumiria do
    # pipeline sem o vídeo final — tenta de novo re-encodando.
    if not (os.path.exists(audio_file) and os.path.getsize(audio_file) > 0):
        print(f"Audio copy failed for {input_file}; retrying with AAC re-encode...")
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-threads", "12", "-i", input_file, "-vn", "-c:a", "aac", "-b:a", "192k", audio_file],
                       check=False, capture_output=True)

    if os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
        final_output = os.path.join(final_folder, f"final-output{str(index).zfill(3)}_processed.mp4")
        encoder_name, encoder_preset = get_best_encoder()
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats",
            "-threads", "12",
            "-i", output_file,
            "-i", audio_file,
            "-c:v", encoder_name, "-preset", encoder_preset, "-b:v", "5M",
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(fps),
            final_output
        ]
        try:
            subprocess.run(command, check=True) #, capture_output=True)
            print(f"Final file generated: {final_output}")
            try:
                os.remove(audio_file)
                os.remove(output_file)
            except:
                pass
        except subprocess.CalledProcessError as e:
            print(f"Error muxing: {e}")
    else:
        print(f"Warning: No audio extracted for {input_file}")


def edit(project_folder="tmp", segments_data=None, no_face_mode="zoom", **kwargs):
    """
    Crop each cut to a vertical 9:16 frame using a centered crop (zoom).
    No face detection — the speaker is assumed to be roughly centered.

    Extra keyword arguments are accepted and ignored for backward compatibility
    with older callers.
    """
    index = 0
    cuts_folder = os.path.join(project_folder, "cuts")
    final_folder = os.path.join(project_folder, "final")
    os.makedirs(final_folder, exist_ok=True)

    face_modes_log = {}

    found_files = sorted(glob.glob(os.path.join(cuts_folder, "*_original_scale.mp4")))

    if not found_files:
        print(f"No files found in {cuts_folder}.")
        return

    for input_file in found_files:
        input_filename = os.path.basename(input_file)

        # Extract Index
        index = 0
        try:
             parts = input_filename.split('_')
             if parts[0].isdigit(): index = int(parts[0])
             elif input_filename.startswith("output"): # output000
                 idx_str = input_filename[6:9]
                 if idx_str.isdigit(): index = int(idx_str)
        except: pass

        output_file = os.path.join(final_folder, f"temp_video_no_audio_{index}.mp4")

        # Determine Final Name (Title)
        base_name_final = input_filename.replace("_original_scale.mp4", "")
        # If legacy name, try to improve it
        if input_filename.startswith("output") and segments_data and index < len(segments_data):
             title = segments_data[index].get("title", f"Segment_{index}")
             safe_title = "".join([c for c in title if c.isalnum() or c in " _-"]).strip().replace(" ", "_")[:60]
             base_name_final = f"{index:03d}_{safe_title}"

        if not os.path.exists(input_file):
            continue

        # Center 9:16 crop (the only mode now)
        generate_short_fallback(input_file, output_file, index, project_folder, final_folder, no_face_mode=no_face_mode)

        # Always single-face layout for subtitle positioning
        face_modes_log[f"output{str(index).zfill(3)}"] = "1"

        # Rename output (and matching subtitle JSON) to the segment title
        try:
            new_mp4_name = f"{base_name_final}.mp4"
            new_mp4_path = os.path.join(final_folder, new_mp4_name)

            generated_mp4_name = f"final-output{str(index).zfill(3)}_processed.mp4"
            generated_mp4_path = os.path.join(final_folder, generated_mp4_name)

            if os.path.exists(generated_mp4_path):
                if os.path.exists(new_mp4_path): os.remove(new_mp4_path)
                os.rename(generated_mp4_path, new_mp4_path)
                print(f"Renamed Output to Title: {new_mp4_name}")

                # Rename JSON Subtitle (if exists and hasn't been renamed by cut_segments)
                subs_folder = os.path.join(project_folder, "subs")
                old_json_name = f"final-output{str(index).zfill(3)}_processed.json"
                old_json_path = os.path.join(subs_folder, old_json_name)
                new_json_name = f"{base_name_final}_processed.json"
                new_json_path = os.path.join(subs_folder, new_json_name)

                if os.path.exists(old_json_path):
                    if os.path.exists(new_json_path): os.remove(new_json_path)
                    os.rename(old_json_path, new_json_path)
                    print(f"Renamed Subtitles to Title: {new_json_name}")
        except Exception as e:
            print(f"Warning: Could not rename file with title: {e}")

    # Save Face Modes to JSON for subtitle usage (all single-face)
    modes_file = os.path.join(project_folder, "face_modes.json")
    try:
        with open(modes_file, "w") as f:
            json.dump(face_modes_log, f)
        print(f"Detect Stats saved: {modes_file}")
    except Exception as e:
        print(f"Error saving face modes: {e}")

if __name__ == "__main__":
    edit()
