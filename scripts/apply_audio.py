import os
import subprocess
import shutil
import tempfile
import json

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

def get_video_duration(video_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def get_audio_file_duration(audio_path):
    """Returns the duration of an audio file in seconds."""
    return get_video_duration(audio_path)


def has_audio_stream(video_path):
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=index", "-of", "csv=p=0", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def get_source_volume_factor(config):
    try:
        source_video_volume = float(config.get("source_video_volume", 200.0))
    except (TypeError, ValueError):
        source_video_volume = 200.0
    source_video_volume = max(0.0, min(200.0, source_video_volume))
    return source_video_volume / 100.0, source_video_volume

def build_volume_expression(video_dur, base_volume, ending_active, ending_vol, ending_start, crossfade_duration):
    """
    Builds an FFmpeg expression for varying volume over time.
    """
    if not ending_active:
        return f"{base_volume / 100.0}"
        
    start_fade = video_dur - ending_start
    if start_fade < 0:
        start_fade = 0
        
    end_fade = start_fade + crossfade_duration
    if end_fade > video_dur:
        end_fade = video_dur
        
    dur = end_fade - start_fade
    if dur <= 0:
        dur = 0.001
        
    b_vol = base_volume / 100.0
    e_vol = ending_vol / 100.0
    
    # Linear interpolation: y = y1 + (y2 - y1) * (t - x1) / (x2 - x1)
    transition_expr = f"{b_vol}+({e_vol}-{b_vol})*(t-{start_fade})/{dur}"
    
    # if t < start_fade -> base_volume
    # if t >= start_fade and t <= end_fade -> transition
    # if t > end_fade -> ending_vol
    expr = f"if(lt(t,{start_fade}),{b_vol},if(lt(t,{end_fade}),{transition_expr},{e_vol}))"
    return expr


def apply_source_volume_only(input_video, source_volume_factor, output_video):
    if abs(source_volume_factor - 1.0) <= 0.0001:
        try:
            shutil.copy2(input_video, output_video)
            return True
        except Exception as e:
            print(f"Error copying {input_video} to {output_video}: {e}")
            return False

    if not has_audio_stream(input_video):
        print(f"No original audio stream found in {input_video}. Copying file without volume adjustment.")
        try:
            shutil.copy2(input_video, output_video)
            return True
        except Exception as e:
            print(f"Error copying {input_video} to {output_video}: {e}")
            return False

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", input_video,
        "-map", "0:v",
        "-map", "0:a",
        "-c:v", "copy",
        "-af", f"volume={source_volume_factor}",
        "-c:a", "aac", "-b:a", "192k",
        output_video
    ]

    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error applying source volume to {input_video}: {result.stderr or result.stdout}")
        return False
    return True

def apply_audio_to_video(input_video, audio_path, config, output_video):
    video_dur = get_video_duration(input_video)
    if video_dur <= 0:
        print(f"Failed to get duration for {input_video}, skipping audio overlay.")
        return False

    source_volume_factor, _ = get_source_volume_factor(config)
    has_original_audio = has_audio_stream(input_video)
    bgm_enabled = bool(config.get("enabled", False))
    has_bgm_audio = bgm_enabled and bool(audio_path and os.path.exists(audio_path))

    # --- Outro Music config ---
    outro_music_cfg = config.get("outro_music", {})
    outro_music_enabled = bool(outro_music_cfg.get("enabled", False))
    outro_music_path = outro_music_cfg.get("audio_file_path", "")
    has_outro_music = outro_music_enabled and bool(outro_music_path and os.path.exists(outro_music_path))

    if not has_bgm_audio and not has_outro_music:
        return apply_source_volume_only(input_video, source_volume_factor, output_video)

    encoder, preset = get_best_encoder()

    # --- BGM (Música A) config ---
    base_volume = config.get("base_volume", 12)
    loop_audio = config.get("loop_to_end", True)
    fade_in = config.get("fade_in_duration", 0.5)
    fade_out = config.get("fade_out_duration", 0.5)
    crossfade = config.get("crossfade_duration", 3.0)
    use_ending_volume = config.get("use_ending_volume", True)
    stop_before_outro = config.get("stop_before_outro", True)
    sync_with_outro = config.get("sync_with_outro", True)
    ending_volume = config.get("ending_volume", 20)
    ending_start_time = config.get("ending_start_time", 10)

    actual_audio_dur = video_dur

    # --- Read Outro video config for sync ---
    outro_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outro_config.json")
    outro_video_dur = 0.0
    outro_fade_dur = 1.0
    outro_enabled = False

    if os.path.exists(outro_config_path):
        try:
            with open(outro_config_path, "r", encoding="utf-8") as f:
                outro_config = json.load(f)
            if outro_config.get("enabled", False):
                outro_enabled = True
                outro_video = outro_config.get("outro_video_path")
                if outro_video and os.path.exists(outro_video):
                    outro_video_dur = get_video_duration(outro_video)
                outro_fade_dur = float(outro_config.get("fade_duration", 1.0))
        except Exception as e:
            print(f"Error reading outro config for audio sync: {e}")

    # Calculate the transition point where Outro begins
    # total = main + outro - fade  →  transition_point = total - outro_dur
    transition_point = 0.0
    if outro_enabled and outro_video_dur > 0:
        transition_point = max(0.0, video_dur - outro_video_dur)

    # -----------------------------------------------------------------------
    # If outro_music is active, it overrides BGM's fade-out / ending logic.
    # The BGM will instead fade out exactly at the transition point.
    # -----------------------------------------------------------------------
    if has_outro_music and outro_enabled and outro_video_dur > 0:
        # BGM trims and fades out at transition
        bgm_end = min(video_dur, transition_point + outro_fade_dur)
        bgm_fade_out_start = transition_point
        bgm_fade_out_dur = outro_fade_dur
        bgm_vol_expr = f"{base_volume / 100.0}"
        use_bgm_ending_volume_override = False
    elif has_bgm_audio:
        # Original BGM logic (no outro_music)
        if os.path.exists(outro_config_path):
            try:
                with open(outro_config_path, "r", encoding="utf-8") as f:
                    outro_config_r = json.load(f)
                if outro_config_r.get("enabled", False):
                    o_video = outro_config_r.get("outro_video_path")
                    if o_video and os.path.exists(o_video):
                        o_dur = get_video_duration(o_video)
                        o_fade = float(outro_config_r.get("fade_duration", 1.0))
                        if o_dur > 0:
                            if stop_before_outro:
                                actual_audio_dur = max(0.1, video_dur - o_dur)
                                use_ending_volume = False
                            elif use_ending_volume and sync_with_outro:
                                ending_start_time = o_dur
                                crossfade = o_fade
            except Exception as e:
                print(f"Error reading outro config for audio sync: {e}")
        bgm_end = actual_audio_dur
        bgm_fade_out_start = max(0, video_dur - fade_out)
        bgm_fade_out_dur = fade_out
        bgm_vol_expr = build_volume_expression(actual_audio_dur, base_volume, use_ending_volume, ending_volume, ending_start_time, crossfade)
        use_bgm_ending_volume_override = True
    else:
        bgm_end = video_dur
        bgm_fade_out_start = 0
        bgm_fade_out_dur = 0
        bgm_vol_expr = f"{base_volume / 100.0}"
        use_bgm_ending_volume_override = False

    # -----------------------------------------------------------------------
    # Calculate outro_music trim based on start_from
    # -----------------------------------------------------------------------
    outro_music_trim_start = 0.0
    outro_music_trim_end = 0.0
    outro_portion_dur = 0.0

    if has_outro_music:
        if outro_enabled and outro_video_dur > 0:
            outro_portion_dur = max(0.1, video_dur - transition_point)
        else:
            # No outro video — warn and skip outro music
            print("[Audio] outro_music is enabled but no Outro video is active. Skipping outro_music.")
            has_outro_music = False

    if has_outro_music:
        outro_music_file_dur = get_audio_file_duration(outro_music_path)
        start_from = outro_music_cfg.get("start_from", "end")

        if outro_music_file_dur <= 0:
            print(f"[Audio] Could not read duration of outro_music file: {outro_music_path}. Skipping.")
            has_outro_music = False
        else:
            if outro_music_file_dur <= outro_portion_dur:
                # Music shorter than outro portion — use entire file
                outro_music_trim_start = 0.0
                outro_music_trim_end = outro_music_file_dur
            elif start_from == "end":
                outro_music_trim_start = max(0.0, outro_music_file_dur - outro_portion_dur)
                outro_music_trim_end = outro_music_file_dur
            else:  # "start" (default)
                outro_music_trim_start = 0.0
                outro_music_trim_end = outro_portion_dur

    # -----------------------------------------------------------------------
    # Build FFmpeg command
    # -----------------------------------------------------------------------
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", input_video]

    input_idx = 1  # next input index after the video

    if has_bgm_audio:
        if loop_audio:
            cmd.extend(["-stream_loop", "-1", "-i", audio_path])
        else:
            cmd.extend(["-i", audio_path])
        bgm_input_idx = input_idx
        input_idx += 1

    if has_outro_music:
        cmd.extend(["-i", outro_music_path])
        outro_music_input_idx = input_idx
        input_idx += 1

    # --- Build filter_complex ---
    filter_parts = []
    mix_labels = []

    # 1. Original audio (source video)
    if has_original_audio:
        if abs(source_volume_factor - 1.0) > 0.0001:
            filter_parts.append(f"[0:a]volume={source_volume_factor}[orig]")
            mix_labels.append("[orig]")
        else:
            mix_labels.append("[0:a]")
    # (if no original audio, skip entirely)

    # 2. BGM (Música A)
    if has_bgm_audio:
        bgm_filters = []
        bgm_filters.append(f"atrim=0:{bgm_end}")
        bgm_filters.append("asetpts=PTS-STARTPTS")

        if use_bgm_ending_volume_override and 'if(' in bgm_vol_expr:
            bgm_filters.append(f"volume='{bgm_vol_expr}':eval=frame")
        else:
            bgm_filters.append(f"volume={bgm_vol_expr}")

        if fade_in > 0:
            bgm_filters.append(f"afade=t=in:d={fade_in}")

        if has_outro_music:
            # Fade out BGM at the outro transition, duration = outro_fade_dur
            if outro_fade_dur > 0:
                bgm_filters.append(f"afade=t=out:st={bgm_fade_out_start}:d={bgm_fade_out_dur}")
        else:
            # Original fade-out
            if bgm_fade_out_dur > 0:
                bgm_filters.append(f"afade=t=out:st={bgm_fade_out_start}:d={bgm_fade_out_dur}")

        bgm_filters.append("aresample=44100")
        filter_parts.append(f"[{bgm_input_idx}:a]{','.join(bgm_filters)}[bgm]")
        mix_labels.append("[bgm]")

    # 3. Outro Music (Música B)
    if has_outro_music:
        om_volume = outro_music_cfg.get("volume", 50)
        om_fade_in = float(outro_music_cfg.get("fade_in_duration", 1))
        om_fade_out_enabled = bool(outro_music_cfg.get("fade_out_enabled", True))
        om_fade_out = float(outro_music_cfg.get("fade_out_duration", 1))
        om_vol_factor = om_volume / 100.0

        om_filters = []
        om_filters.append(f"atrim={outro_music_trim_start}:{outro_music_trim_end}")
        om_filters.append("asetpts=PTS-STARTPTS")
        om_filters.append(f"volume={om_vol_factor}")

        effective_om_dur = outro_music_trim_end - outro_music_trim_start

        if om_fade_in > 0:
            om_filters.append(f"afade=t=in:d={min(om_fade_in, effective_om_dur)}")

        if om_fade_out_enabled and om_fade_out > 0:
            clamped_fade_out = min(om_fade_out, effective_om_dur)
            fade_out_st = max(0.0, effective_om_dur - clamped_fade_out)
            om_filters.append(f"afade=t=out:st={fade_out_st}:d={clamped_fade_out}")

        # Delay outro music to start at the transition point (ms)
        delay_ms = int(transition_point * 1000)
        om_filters.append(f"adelay={delay_ms}|{delay_ms}")
        om_filters.append("aresample=44100")

        filter_parts.append(f"[{outro_music_input_idx}:a]{','.join(om_filters)}[outro_bgm]")
        mix_labels.append("[outro_bgm]")

    # 4. Mix all labels
    n_inputs = len(mix_labels)
    if n_inputs == 0:
        # No audio at all — just copy video
        cmd.extend(["-map", "0:v", "-c:v", "copy", "-an", output_video])
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        return result.returncode == 0
    elif n_inputs == 1:
        mix_label = mix_labels[0]
        # No need for amix, just rename
        if mix_label.startswith("["):
            filter_parts.append(f"{mix_label}anull[a]")
        else:
            filter_parts.append(f"{mix_label}anull[a]")
        mix_out = "[a]"
    else:
        mix_label_str = "".join(mix_labels)
        filter_parts.append(
            f"{mix_label_str}amix=inputs={n_inputs}:duration=first:dropout_transition=0:normalize=0[a]"
        )
        mix_out = "[a]"

    filter_complex = ";".join(filter_parts)

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend([
        "-map", "0:v",
        "-map", mix_out,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        output_video
    ])

    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error applying audio to {input_video}: {result.stderr or result.stdout}")
        return False
    return True

def process_all_videos(source_folder, audio_config, output_folder):
    """
    Applies the configured audio background to all mp4 videos in the source_folder.
    """
    audio_path = audio_config.get("audio_file_path")
    source_volume_factor, source_volume_percent = get_source_volume_factor(audio_config)
    bgm_enabled = bool(audio_config.get("enabled", False))
    has_bgm_audio = bgm_enabled and bool(audio_path and os.path.exists(audio_path))

    # Check outro_music
    outro_music_cfg = audio_config.get("outro_music", {})
    outro_music_enabled = bool(outro_music_cfg.get("enabled", False))
    outro_music_path = outro_music_cfg.get("audio_file_path", "")
    has_outro_music = outro_music_enabled and bool(outro_music_path and os.path.exists(outro_music_path))

    if not has_bgm_audio and not has_outro_music and abs(source_volume_factor - 1.0) <= 0.0001:
        print("No valid BGM configured, no Outro Music, and source video volume is at 100%. Skipping audio process.")
        return

    if bgm_enabled and not has_bgm_audio and audio_path:
        print(f"Configured BGM file was not found: {audio_path}. Applying only source video volume / outro music.")

    if has_bgm_audio:
        print(f"Applying Audio Overlay to all videos in {source_folder}...")
    elif has_outro_music:
        print(f"Applying Outro Music to all videos in {source_folder}...")
    else:
        print(f"Applying source video volume ({source_volume_percent:.0f}%) to all videos in {source_folder}...")

    
    os.makedirs(output_folder, exist_ok=True)
    temp_dir = tempfile.mkdtemp()
    
    processed_count = 0
    files = [f for f in os.listdir(source_folder) if f.lower().endswith(('.mp4', '.mkv', '.avi')) and not f.startswith("temp_")]
    
    for filename in files:
        main_video_path = os.path.join(source_folder, filename)
        temp_output_path = os.path.join(temp_dir, f"temp_aud_{filename}")
        
        print(f"Processing audio for {filename}...")
        if apply_audio_to_video(main_video_path, audio_path if has_bgm_audio else None, audio_config, temp_output_path):
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
        
    print(f"Audio Overlay process completed. Applied to {processed_count} videos.")
