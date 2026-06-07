import json
import os
import re
import time


def call_gemini_simple(prompt, api_key, model_name="gemini-3.5-flash"):
    """
    Simple Gemini call without thinkingConfig (not needed for text correction).
    Falls back through model sequence if needed.
    """
    import requests

    # Mesma cadeia de call_gemini() em create_viral_segments.py — qualquer
    # chamada à API do Gemini deve seguir a mesma ordem de preferência.
    fallback_sequence = [model_name, "gemini-3.5-flash", "gemini-3-flash-preview"]
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
    """Build the correction prompt for a chunk of segment texts.

    Tuned for Brazilian-Portuguese sermon/preaching transcripts: it fixes
    speech-recognition mistakes (including biblical names and references) while
    preserving the exact word count per line, which lets the caller keep the
    word-level subtitle timestamps aligned.
    """
    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(segment_texts))
    return (
        "Você é um revisor profissional de legendas de SERMÕES e PREGAÇÕES cristãs "
        "em português brasileiro.\n"
        "Abaixo está uma lista numerada de legendas transcritas automaticamente por IA, "
        "que pode conter erros de reconhecimento de fala.\n\n"
        "Corrija SOMENTE erros óbvios, com mão leve:\n"
        "- Palavras que a IA transcreveu errado (que não fazem sentido no contexto da fala)\n"
        "- Nomes próprios bíblicos e termos teológicos (ex.: Jesus, Paulo, Coríntios, "
        "Espírito Santo, Habacuque, aleluia)\n"
        "- Referências bíblicas no formato correto (ex.: \"joão 3 16\" -> \"João 3:16\")\n"
        "- Pontuação e uso de maiúsculas/minúsculas quando necessário\n\n"
        "Regras OBRIGATÓRIAS (não quebre nenhuma):\n"
        "- NÃO altere a ordem das palavras\n"
        "- NÃO adicione nem remova palavras — mantenha EXATAMENTE a mesma quantidade de "
        "palavras em cada linha (isso é essencial para a sincronia da legenda)\n"
        "- NÃO reformule, NÃO traduza e NÃO parafraseie as frases\n"
        "- NÃO junte nem divida linhas — devolva o EXATO mesmo número de linhas recebido\n"
        "- Se uma linha já estiver correta, devolva-a idêntica\n"
        "- Na dúvida, NÃO mude\n"
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
