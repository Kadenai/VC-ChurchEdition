from scripts import cut_json
import os
import subprocess
import json

def cut(segments, project_folder="tmp", skip_video=False):

    def check_nvenc_support():
        # ... (unchanged)
        try:
            result = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True)
            return "h264_nvenc" in result.stdout
        except subprocess.CalledProcessError:
            return False

    def generate_segments(response, project_folder, skip_video):
        def parse_seconds(value, treat_large_numbers_as_ms=False):
            if isinstance(value, (int, float)):
                seconds = float(value)
                # Heurística antiga interpretava >= 1000 como ms, mas isso quebra
                # cortes legítimos em vídeos > ~16 min (1000s). Só consideramos ms
                # quando o número é grande o suficiente para não ser plausível em
                # segundos (>= 100000s = ~27h). Alinha com _coerce_seconds em
                # create_viral_segments.py.
                if treat_large_numbers_as_ms and seconds >= 100000:
                    seconds = seconds / 1000.0
                return seconds

            text_value = str(value).strip()
            try:
                return float(text_value)
            except (TypeError, ValueError):
                pass

            parts = text_value.split(':')
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds

            raise ValueError(f"Invalid time format: {value}")

        if not check_nvenc_support():
            print("NVENC is not supported on this system. Falling back to libx264.")
            video_codec = "libx264"
        else:
            video_codec = "h264_nvenc"

        # Procurar input_video.mp4 no project_folder ou tmp
        input_file = os.path.join(project_folder, "input.mp4")
        if not os.path.exists(input_file):
            # Tenta fallback legado
            input_file_legacy = os.path.join(project_folder, "input_video.mp4")
            if os.path.exists(input_file_legacy):
                input_file = input_file_legacy
            else:
                print(f"Input file not found in {project_folder}")
                return

        # Pasta de saida para os cortes
        cuts_folder = os.path.join(project_folder, "cuts")
        os.makedirs(cuts_folder, exist_ok=True)
        
        # Pasta de saida para legendas json cortadas
        subs_folder = os.path.join(project_folder, "subs")
        os.makedirs(subs_folder, exist_ok=True)

        # Input JSON (Transkription original)
        input_json_path = os.path.join(project_folder, "input.json")

        outro_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outro_config.json")
        pad_duration = 0.0
        if os.path.exists(outro_config_path):
            try:
                with open(outro_config_path, "r", encoding="utf-8") as f:
                    outro_config = json.load(f)
                if outro_config.get("enabled", False):
                    pad_duration = float(outro_config.get("fade_duration", 0.0))
            except Exception as e:
                print(f"Warning: failed to read outro_config.json: {e}")

        segments = response.get("segments", [])
        for i, segment in enumerate(segments):
            start_time = segment.get("start_time", "00:00:00")
            duration = segment.get("duration", 0)

            # Heurística para duration:
            try:
                duration_seconds = parse_seconds(duration, treat_large_numbers_as_ms=True)
            except Exception as e:
                print(f"Warning: invalid duration for segment {i}: {duration} ({e}). Skipping.")
                continue

            if duration_seconds <= 0:
                print(f"Warning: duration <= 0 for segment {i} ({duration_seconds}). Skipping.")
                continue

            duration_str = f"{duration_seconds:.3f}"
            
            # Heurística para start_time:
            try:
                start_time_seconds = parse_seconds(start_time, treat_large_numbers_as_ms=True)
            except Exception as e:
                print(f"Warning: invalid start_time for segment {i}: {start_time} ({e}). Skipping.")
                continue

            start_time_str = f"{start_time_seconds:.3f}"

            # Título para nome de arquivo
            title = segment.get("title", f"Segment_{i}")
            safe_title = "".join([c for c in title if c.isalnum() or c in " _-"]).strip()
            safe_title = safe_title.replace(" ", "_")[:60]
            base_name = f"{i:03d}_{safe_title}"

            output_filename = f"{base_name}_original_scale.mp4"
            output_path = os.path.join(cuts_folder, output_filename)

            print(f"Processing segment {i+1}/{len(segments)}")
            print(f"Start time: {start_time}, Duration: {duration}")
            # print(f"Executing command: {' '.join(command)}")

            # VIDEO GENERATION
            if not skip_video:
                video_duration = max(0.05, duration_seconds + pad_duration)
                video_duration_str = f"{video_duration:.3f}"
                # Comando ffmpeg
                command = [
                    "ffmpeg",
                    "-y",
                    "-loglevel", "error", "-hide_banner",
                    "-ss", start_time_str,
                    "-i", input_file,
                    "-t", video_duration_str,
                    "-c:v", video_codec
                ]

                if video_codec == "h264_nvenc":
                    command.extend([
                        "-preset", "p1",
                        "-b:v", "5M",
                    ])
                else:
                    command.extend([
                        "-preset", "ultrafast",
                        "-crf", "23"
                    ])

                command.extend([
                    "-c:a", "aac",
                    "-b:a", "128k",
                    output_path
                ])

                result = subprocess.run(command, check=False, capture_output=True, text=True)
                if result.returncode == 0:
                    if os.path.exists(output_path):
                        file_size = os.path.getsize(output_path)
                        print(f"Generated segment: {output_filename}, Size: {file_size} bytes")
                else:
                    print(f"Error executing ffmpeg for {output_filename}: {result.stderr or result.stdout}")
                    continue
            else:
                print(f"Skipping video generation for {output_filename} (using existing). check json...")
            
            # --- JSON CUTTING (ALWAYS RUN) ---
            end_time_seconds = start_time_seconds + float(duration_seconds)
            
            # Nome do json correspondente ao vídeo FINAL com titulo
            json_output_filename = f"{base_name}_processed.json"
            json_output_path = os.path.join(subs_folder, json_output_filename)
            
            cut_json.cut_json_transcript(input_json_path, json_output_path, start_time_seconds, end_time_seconds)
            # --------------------

            print("\n" + "="*50 + "\n")

    # Reading the JSON file if segments not provided (legacy behavior)
    json_path = os.path.join(project_folder, 'viral_segments.txt')
    if segments is None:
        with open(json_path, 'r', encoding='utf-8') as file:
            response = json.load(file)
    else:
        response = segments

    # Deduplicação estrita no gargalo: protege ambos os caminhos de geração
    # (IA automática via process_segments + JSON manual colado direto em viral_segments.txt).
    # Garante que duas janelas de tempo nunca se sobreponham.
    try:
        from scripts.create_viral_segments import dedupe_non_overlapping
        raw_segments = response.get("segments", []) if isinstance(response, dict) else []
        before = len(raw_segments)
        deduped = dedupe_non_overlapping(raw_segments)
        if before != len(deduped):
            print(f"[DEDUP] {before - len(deduped)} corte(s) sobrepostos descartados (de {before} -> {len(deduped)}).")
        response["segments"] = deduped
        # Persiste a lista limpa para que a Library/UI reflita exatamente o que será cortado
        try:
            with open(json_path, 'w', encoding='utf-8') as file:
                json.dump(response, file, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DEDUP] Aviso: falha ao reescrever viral_segments.txt: {e}")
    except Exception as e:
        print(f"[DEDUP] Aviso: deduplicação pulada por erro: {e}")

    generate_segments(response, project_folder, skip_video)
