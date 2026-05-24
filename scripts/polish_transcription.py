import json
import os
import re
import time

CHUNK_SIZE = 100  # Segments per API call


def call_gemini_simple(prompt, api_key, model_name="gemini-3.5-flash"):
    """
    Simple Gemini call without thinkingConfig (not needed for text correction).
    Falls back through model sequence if needed.
    """
    import requests

    # Mesma cadeia de call_gemini() em create_viral_segments.py — qualquer
    # chamada à API do Gemini deve seguir a mesma ordem de preferência.
    fallback_sequence = [model_name, "gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite-preview"]
    # Deduplicate while preserving order
    seen = set()
    models_to_try = []
    for m in fallback_sequence:
        if m and m not in seen:
            seen.add(m)
            models_to_try.append(m)

    for current_model in models_to_try:
        if "gemini" not in current_model:
            continue

        print(f"[PolishSubs] Trying model: {current_model}...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
        }

        max_retries = 3
        base_wait = 15
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=data, timeout=120)

                if response.status_code == 429:
                    wait_time = base_wait * (attempt + 1)
                    print(f"  -> [429] Rate limit. Waiting {wait_time}s...", flush=True)
                    time.sleep(wait_time)
                    continue

                if response.status_code == 400:
                    print(f"  -> [400] Bad request for {current_model}. Trying next model.")
                    break  # Try next model

                response.raise_for_status()
                res_json = response.json()
                text = (
                    res_json.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if text:
                    return text

            except requests.exceptions.Timeout:
                print(f"  -> Timeout on attempt {attempt + 1}. Retrying...")
                time.sleep(base_wait)
            except requests.exceptions.HTTPError as e:
                print(f"  -> HTTP error: {e}")
                break
            except Exception as e:
                print(f"  -> Unexpected error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(base_wait)

    return None


def build_prompt(segment_texts):
    """Build the correction prompt for a chunk of segment texts."""
    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(segment_texts))
    return (
        "Você é um corretor profissional de legendas em português brasileiro.\n"
        "Abaixo está uma lista numerada de legendas transcritas automaticamente por IA.\n\n"
        "Regras OBRIGATÓRIAS:\n"
        "- Corrija APENAS erros de transcrição (palavras erradas, nomes próprios mal escritos)\n"
        "- Corrija pontuação e capitalização onde necessário\n"
        "- NÃO altere a ordem das palavras\n"
        "- NÃO adicione nem remova palavras — apenas corrija as existentes\n"
        "- NÃO reformule ou parafraseie as frases\n"
        "- Mantenha o EXATO mesmo número de linhas que você recebeu\n"
        "- Retorne APENAS a lista numerada corrigida, sem explicações, sem markdown\n\n"
        f"Legendas:\n{numbered}"
    )


def parse_corrections(response_text, expected_count):
    """
    Parse the numbered list returned by the AI.
    Returns a list of corrected texts, or None if parsing fails.
    """
    lines = response_text.strip().splitlines()
    corrections = []

    for line in lines:
        # Match lines like "1. text" or "1) text"
        match = re.match(r"^\d+[.)]\s*(.*)", line.strip())
        if match:
            corrections.append(match.group(1).strip())

    if len(corrections) != expected_count:
        print(
            f"  -> [Warning] Expected {expected_count} corrections, got {len(corrections)}. Skipping chunk."
        )
        return None

    return corrections


def apply_corrections_to_data(data, all_corrections):
    """
    Apply text corrections back to the JSON data.
    Tries word-level mapping first; falls back to segment-level only.
    """
    segments = data.get("segments", [])
    applied = 0

    for i, segment in enumerate(segments):
        if i >= len(all_corrections):
            break

        corrected_text = all_corrections[i]
        original_text = segment.get("text", "").strip()

        if not corrected_text:
            continue

        # Always update segment-level text
        segment["text"] = " " + corrected_text if original_text.startswith(" ") else corrected_text

        # Attempt word-level mapping
        words_list = segment.get("words", [])
        if words_list:
            original_words = original_text.split()
            corrected_words = corrected_text.split()

            if len(original_words) == len(corrected_words) == len(words_list):
                for j, word_entry in enumerate(words_list):
                    word_entry["word"] = corrected_words[j]
            # If counts differ, timestamps are preserved as-is (segment text still corrected)

        applied += 1

    return applied


def polish(project_folder, api_key, model_name, ai_mode="gemini"):
    """
    Polishes transcription text in input.json using AI.

    Args:
        project_folder: Path to project folder containing input.json
        api_key: API key for the AI backend
        model_name: Model name (e.g. "gemini-3.5-flash")
        ai_mode: Currently only "gemini" is supported

    Returns:
        bool: True if polishing was successful (at least partially)
    """
    input_json_path = os.path.join(project_folder, "input.json")
    backup_path = os.path.join(project_folder, "input_original.json")

    if not os.path.exists(input_json_path):
        print(f"[PolishSubs] input.json not found at {input_json_path}. Skipping.")
        return False

    if ai_mode != "gemini" or not api_key:
        print(f"[PolishSubs] AI mode '{ai_mode}' not supported or no API key. Skipping.")
        return False

    print(f"[PolishSubs] Loading transcription from {input_json_path}...")
    try:
        with open(input_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[PolishSubs] Failed to load input.json: {e}")
        return False

    segments = data.get("segments", [])
    if not segments:
        print("[PolishSubs] No segments found. Skipping.")
        return False

    print(f"[PolishSubs] Found {len(segments)} segments. Processing in chunks of {CHUNK_SIZE}...")

    # Backup original
    try:
        if not os.path.exists(backup_path):
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"[PolishSubs] Backup saved to {backup_path}")
    except Exception as e:
        print(f"[PolishSubs] Warning: could not create backup: {e}")

    # Process in chunks
    all_corrections = [""] * len(segments)
    total_chunks = (len(segments) + CHUNK_SIZE - 1) // CHUNK_SIZE
    success_chunks = 0

    for chunk_idx in range(total_chunks):
        start = chunk_idx * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, len(segments))
        chunk_segments = segments[start:end]

        chunk_texts = [seg.get("text", "").strip() for seg in chunk_segments]

        print(f"[PolishSubs] Chunk {chunk_idx + 1}/{total_chunks} (segs {start + 1}-{end})...", flush=True)

        prompt = build_prompt(chunk_texts)

        response_text = None
        if ai_mode == "gemini":
            response_text = call_gemini_simple(prompt, api_key, model_name=model_name)

        if not response_text:
            print(f"  -> [Warning] No response for chunk {chunk_idx + 1}. Keeping originals.")
            # Keep originals for this chunk
            for i, text in enumerate(chunk_texts):
                all_corrections[start + i] = text
            continue

        corrections = parse_corrections(response_text, len(chunk_texts))
        if corrections is None:
            # Keep originals
            for i, text in enumerate(chunk_texts):
                all_corrections[start + i] = text
        else:
            for i, corrected in enumerate(corrections):
                all_corrections[start + i] = corrected
            success_chunks += 1

        # Delay between chunks to respect rate limits
        if chunk_idx < total_chunks - 1:
            time.sleep(2)

    # Apply all corrections
    applied = apply_corrections_to_data(data, all_corrections)
    print(f"[PolishSubs] Applied corrections to {applied}/{len(segments)} segments.")

    # Save corrected JSON
    try:
        with open(input_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"[PolishSubs] Corrected transcription saved to {input_json_path}")
    except Exception as e:
        print(f"[PolishSubs] Failed to save corrected JSON: {e}")
        return False

    print(f"[PolishSubs] Done. {success_chunks}/{total_chunks} chunks processed successfully.")
    return success_chunks > 0
