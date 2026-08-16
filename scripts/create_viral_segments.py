import json
import os
import re
import sys
import time
import ast
import io
import math
from difflib import SequenceMatcher

# Configura stdout para evitar erros de encoding no Windows (substitui caracteres inválidos por ?)
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    try:
        # Mantém encoding original mas ignora erros (substitui por ?)
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding=sys.stdout.encoding or 'utf-8', errors='replace', line_buffering=True)
    except:
        pass

def clean_json_response(response_text):
    """
    Limpa a resposta focando em encontrar o objeto JSON que contém a chave "segments".
    Estratégia: 
    1. Busca a palavra "segments", encontra o '{' anterior e usa raw_decode.
    2. Fallback: Parsear lista de segmentos item a item (recuperação de JSON truncado).
    """
    if not isinstance(response_text, str):
        response_text = str(response_text)
    
    if not response_text:
        return {"segments": []}

    # 1. Limpeza preliminar
    # Remove tags de pensamento (DeepSeek R1)
    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)
    
    # Normaliza escapes excessivos (\n virando \\n) e aspas se parecer necessário
    try:
        if "\\n" in response_text or "\\\"" in response_text:
             # Tenta um decode básico de escapes
             response_text = response_text.replace("\\n", "\n").replace("\\\"", "\"").replace("\\'", "'")
    except:
        pass

    # 2. Busca pela palavra-chave "segments"
    # Procura índices de todas as ocorrências de 'segments'
    matches = [m.start() for m in re.finditer(r'segments', response_text)]
    
    if not matches:
        # Se não achou segments, retorna vazio
        return {"segments": []}

    # Tenta extrair JSON válido a partir de cada ocorrência
    for match_idx in matches:
        # Procura o '{' mais próximo ANTES de "segments"
        # Limita busca a 5000 chars para trás para performance
        start_search = max(0, match_idx - 5000)
        snippet_before = response_text[start_search:match_idx]
        
        # Encontra o ÚLTIMO '{' no snippet
        last_open_rel = snippet_before.rfind('{')
        
        if last_open_rel != -1:
            real_start = start_search + last_open_rel
            candidate_text = response_text[real_start:]
            
            # Tentativa A: json.raw_decode
            try:
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(candidate_text)
                if 'segments' in obj and isinstance(obj['segments'], list):
                    return obj
            except:
                pass
            
            # Tentativa B: ast.literal_eval
            try:
                balance = 0
                in_string = False
                string_char = None
                escape = False
                found_end = -1
                
                for i, char in enumerate(candidate_text):
                    if escape:
                        escape = False
                        continue
                    if char == '\\':
                        if in_string:
                            escape = True
                        continue
                    if in_string:
                        if char == string_char:
                            in_string = False
                            string_char = None
                        continue
                    if char == '"' or char == "'":
                        in_string = True
                        string_char = char
                        continue
                        
                    if not in_string:
                        if char == '{':
                            balance += 1
                        elif char == '}':
                            balance -= 1
                            if balance == 0:
                                found_end = i
                                break
                
                if found_end != -1:
                    clean_cand = candidate_text[:found_end+1]
                    obj = ast.literal_eval(clean_cand)
                    if 'segments' in obj and isinstance(obj['segments'], list):
                        return obj
            except:
                pass

    # 3. Fallback: Extração bruta de markdown
    try:
        match = re.search(r"```json(.*?)```", response_text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except:
        pass
        
    # 4. LAST RESORT: Fragment Parser (Para JSON truncado/incompleto)
    # Procura por "segments": [ e tenta parsear item por item
    try:
        match_list = re.search(r'"segments"\s*:\s*\[', response_text)
        if match_list:
            start_pos = match_list.end()
            current_pos = start_pos
            found_segments = []
            decoder = json.JSONDecoder()
            
            while True:
                while current_pos < len(response_text) and response_text[current_pos] in ' \t\n\r,':
                    current_pos += 1
                
                if current_pos >= len(response_text):
                    break
                    
                if response_text[current_pos] == ']':
                    break
                
                try:
                    obj, end_pos = decoder.raw_decode(response_text[current_pos:])
                    if isinstance(obj, dict):
                        found_segments.append(obj)
                    current_pos += end_pos
                except json.JSONDecodeError:
                    break
                    
            if found_segments:
                print(f"[INFO] Recuperado {len(found_segments)} segmentos de JSON truncado.")
                return {"segments": found_segments}
    except:
        pass

    return {"segments": []}


def preprocess_transcript_for_ai(segments):
    """
    Concatenates transcript segments into a single string with embedded time tags.
    """
    if not segments:
        return ""

    full_text = ""
    last_tag_time = -100  # Force first tag
    
    # Try to start with (0s) based on first segment
    first_start = segments[0].get('start', 0)
    full_text += f"({int(first_start)}s) "
    last_tag_time = first_start

    for seg in segments:
        text = seg.get('text', '').strip()
        end_time = seg.get('end', 0)
        
        full_text += text + " "
        
        if end_time - last_tag_time >= 4:
            full_text += f"({int(end_time)}s) "
            last_tag_time = end_time

    return full_text.strip()

def call_gemini(prompt, api_key, model_name='gemini-3.7-flash'):
    import requests
    import time
    import re
    
    # Define fallback sequence
    models_to_try = []
    if model_name:
        models_to_try.append(model_name)
        
    fallback_sequence = ["gemini-3.7-flash", "gemini-3-flash-preview"]
    for m in fallback_sequence:
        if m not in models_to_try:
            models_to_try.append(m)
            
    for current_model in models_to_try:
        if "gemini" not in current_model:
            continue
            
        print(f"\n[Gemini] Trying chunk with model: {current_model}...")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {}
        }
        
        # Configure Thinking per user request
        if "gemini-3" in current_model:
            data["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "high"}
        elif "gemini-2.5" in current_model:
            data["generationConfig"]["thinkingConfig"] = {"thinkingBudget": -1}
             
        if not data["generationConfig"]:
             del data["generationConfig"]
        
        max_retries = 3
        base_wait = 15
        model_success = False
        final_text = "{}"
        
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=data)
                
                if response.status_code == 429:
                    wait_time = base_wait * (attempt + 1)
                    print(f"  -> [429] Quota Exceeded. Waiting {wait_time:.2f}s before retry...", flush=True)
                    time.sleep(wait_time)
                    continue
                    
                if response.status_code == 400 and "thinkingConfig" in str(response.text):
                     # If the model explicitly rejects thinking mode, try removing it and resent once
                     if "generationConfig" in data:
                         del data["generationConfig"]
                         response = requests.post(url, headers=headers, json=data)
                         response.raise_for_status()
                
                response.raise_for_status()
                res_json = response.json()
                final_text = res_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                model_success = True
                break
                
            except requests.exceptions.HTTPError as he:
                if response.status_code == 400:
                    print(f"  -> Error 400 (Bad Request) for {current_model}. {response.text}")
                    break # Move to next model
                else:
                    print(f"  -> HTTP Error: {he}.")
                    
                if response.status_code >= 500:
                     time.sleep(base_wait * (attempt + 1))
                     continue
                break # Any other error, jump to next model
            except Exception as e:
                print(f"  -> Unexpected API Error ({current_model}): {e}")
                time.sleep(base_wait)
        
        if model_success and final_text != "{}":
            return final_text
            
        print(f"[Gemini] Failed or quota exceeded for {current_model}. Triggering Fallback...")
        
    print("[Gemini] Total failure across all fallback models.")
    return "{}"

def load_transcript(project_folder):
    """Parses input.tsv or input.srt from the project folder."""
    input_tsv = os.path.join(project_folder, 'input.tsv')
    input_srt = os.path.join(project_folder, 'input.srt')

    transcript_segments = []
    
    # Try to load TSV first (more reliable time)
    if os.path.exists(input_tsv):
        try:
            with open(input_tsv, 'r', encoding='utf-8') as f:
                # Skip header
                lines = f.readlines()[1:] 
                for line in lines:
                    parts = line.strip().split('\t')
                    if len(parts) >= 3:
                        start_ms = float(parts[0])
                        end_ms = float(parts[1])
                        text = parts[2]
                        transcript_segments.append({
                            'start': start_ms / 1000.0, 
                            'end': end_ms / 1000.0, 
                            'text': text
                        })
        except Exception as e:
            print(f"Error parsing TSV: {e}")

    # Fallback to SRT parser if TSV empty/failed
    if not transcript_segments and os.path.exists(input_srt):
         with open(input_srt, 'r', encoding='utf-8') as f:
             srt_content = f.read()
         pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:(?!\n\n).)*)', re.DOTALL)
         matches = pattern.findall(srt_content)
         
         def srt_time_to_seconds(t_str):
             h, m, s = t_str.replace(',', '.').split(':')
             return int(h) * 3600 + int(m) * 60 + float(s)

         for m in matches:
             start_sec = srt_time_to_seconds(m[1])
             end_sec = srt_time_to_seconds(m[2])
             text = m[3].replace('\n', ' ')
             transcript_segments.append({'start': start_sec, 'end': end_sec, 'text': text})

    if not transcript_segments:
        raise ValueError("Could not parse transcript from TSV or SRT.")
    
    return transcript_segments

def _coerce_seconds(value):
    """Converte start_time/end_time/duration para float em segundos.
    Aceita float/int, string numérica, "HH:MM:SS" ou "MM:SS". Retorna None se inválido."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # Heurística: se >= 1000 e veio como número grande, provavelmente é ms
        return v / 1000.0 if v >= 100000 else v
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        pass
    parts = s.split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except (TypeError, ValueError):
        return None
    return None


def dedupe_non_overlapping(segments, epsilon=2.0, min_separation=None):
    """Remove cortes cujas janelas de tempo se sobrepõem OU cujo centro está perto demais.

    Duas regras combinadas:
      1) Sobreposição estrita: se um corte cai dentro da janela [s, e] de outro já aceito
         (tolerando `epsilon` segundos de encostar borda), descarta.
      2) Centro próximo: se o centro de um corte está a menos de `min_separation` segundos
         do centro de outro já aceito, descarta — evita "cortes vizinhos" cobrindo a mesma cena.
         Default: `min_separation = max(epsilon * 2, 5)` se não for informado.

    Mantém o de maior `score`; em empate, o de maior duração; depois, o que começa antes.
    Retorna nova lista (não muta a entrada). Loga descartes no stdout.
    """
    if min_separation is None:
        min_separation = max(epsilon * 2, 5.0)

    normalized = []
    for seg in segments or []:
        s = _coerce_seconds(seg.get('start_time'))
        e = _coerce_seconds(seg.get('end_time'))
        if e is None:
            dur = _coerce_seconds(seg.get('duration'))
            if s is not None and dur is not None:
                e = s + dur
        if s is None or e is None or e <= s:
            print(f"[DEDUP] Ignorando segmento sem janela válida: title={seg.get('title')!r} start={seg.get('start_time')!r} end={seg.get('end_time')!r}")
            continue
        try:
            score = int(seg.get('score', 0) or 0)
        except (TypeError, ValueError):
            score = 0
        normalized.append((score, e - s, s, e, seg))

    # Maior score primeiro; em empate, maior duração; depois start mais cedo
    normalized.sort(key=lambda t: (-t[0], -(t[1]), t[2]))

    kept = []
    for score, dur, s, e, seg in normalized:
        center = (s + e) / 2.0
        conflict = None
        conflict_reason = ""
        for ks, ke, kseg in kept:
            # 1) Sobreposição estrita
            if s < ke - epsilon and e > ks + epsilon:
                conflict = (ks, ke, kseg)
                conflict_reason = "sobreposição"
                break
            # 2) Centro próximo (cortes "vizinhos" cobrindo a mesma cena)
            kcenter = (ks + ke) / 2.0
            if abs(center - kcenter) < min_separation:
                conflict = (ks, ke, kseg)
                conflict_reason = f"centro a {abs(center - kcenter):.1f}s (<{min_separation:.1f}s)"
                break
        if conflict is not None:
            ks, ke, kseg = conflict
            print(f"[DEDUP] Descartando '{seg.get('title','?')}' ({s:.1f}-{e:.1f}s) — {conflict_reason} com '{kseg.get('title','?')}' ({ks:.1f}-{ke:.1f}s)")
            continue
        # Garante que o segmento devolvido tenha start_time/end_time/duration consistentes em float
        seg = dict(seg)
        seg['start_time'] = s
        seg['end_time'] = e
        seg['duration'] = e - s
        kept.append((s, e, seg))

    # Devolve em ordem cronológica (mais natural para usuário e ffmpeg)
    kept.sort(key=lambda t: t[0])
    return [k[2] for k in kept]


def dedupe_raw_candidates(segments, ref_tolerance=15.0, title_similarity=0.75):
    """Remove candidatos brutos da IA que provavelmente são o MESMO segmento detectado
    em chunks diferentes (devido ao overlap entre chunks).

    Compara `start_time_ref` (em segundos) e similaridade de `title`/`start_text`.
    Dois candidatos são considerados duplicatas se:
      - Seus `start_time_ref` estão a <= `ref_tolerance` segundos OU
      - Seus títulos têm similaridade >= `title_similarity`.

    Mantém o de maior `score`. Retorna nova lista. Loga descartes.
    """
    if not segments:
        return []

    def parse_ref(seg):
        """Extrai segundos do campo start_time_ref ('(123s)' ou '123' ou número)."""
        ref = seg.get('start_time_ref', None)
        if ref is None:
            return None
        if isinstance(ref, (int, float)):
            return float(ref)
        try:
            m = re.search(r'\d+(?:\.\d+)?', str(ref))
            return float(m.group()) if m else None
        except (AttributeError, ValueError):
            return None

    def norm_text(t):
        if not t:
            return ""
        t = str(t).lower().strip()
        t = re.sub(r'[^\w\s]', '', t)
        t = re.sub(r'\s+', ' ', t)
        return t

    enriched = []
    for seg in segments:
        try:
            score = int(seg.get('score', 0) or 0)
        except (TypeError, ValueError):
            score = 0
        enriched.append({
            "seg": seg,
            "score": score,
            "ref": parse_ref(seg),
            "title_norm": norm_text(seg.get('title', '')),
            "start_text_norm": norm_text(seg.get('start_text', '')),
        })

    # Maior score primeiro (em empate, ordem original)
    enriched.sort(key=lambda x: -x["score"])

    kept = []
    discarded = 0
    for cand in enriched:
        is_dup = False
        for k in kept:
            # 1) Mesmo timestamp de referência
            if cand["ref"] is not None and k["ref"] is not None:
                if abs(cand["ref"] - k["ref"]) <= ref_tolerance:
                    is_dup = True
                    reason = f"start_time_ref próximo ({cand['ref']:.0f}s vs {k['ref']:.0f}s)"
                    break
            # 2) Título muito similar
            if cand["title_norm"] and k["title_norm"]:
                sim = SequenceMatcher(None, cand["title_norm"], k["title_norm"]).ratio()
                if sim >= title_similarity:
                    is_dup = True
                    reason = f"título similar (~{sim:.0%})"
                    break
            # 3) start_text muito similar (fallback se títulos diferem)
            if cand["start_text_norm"] and k["start_text_norm"]:
                sim = SequenceMatcher(None, cand["start_text_norm"], k["start_text_norm"]).ratio()
                if sim >= title_similarity:
                    is_dup = True
                    reason = f"start_text similar (~{sim:.0%})"
                    break
        if is_dup:
            discarded += 1
            print(f"[DEDUP-RAW] Descartando candidato '{cand['seg'].get('title','?')}' (score={cand['score']}) — {reason}")
            continue
        kept.append(cand)

    if discarded:
        print(f"[DEDUP-RAW] {discarded} candidato(s) brutos descartado(s) antes do alinhamento.")

    return [k["seg"] for k in kept]


def process_segments(raw_segments, transcript_segments, min_duration, max_duration, output_count=None):
    """
    Aligns raw AI segments (with reference tags) to actual transcript timestamps.
    Applies constraints, validation, and deduplication.
    """
    
    all_segments = raw_segments
    tempo_minimo = min_duration
    tempo_maximo = max_duration
    
    # Sort segments by score (descending)
    try:
        all_segments.sort(key=lambda x: int(x.get('score', 0)), reverse=True)
    except:
        pass

    # --- POST-PROCESSING: Match Text to Timestamps ---
    processed_segments = []
    
    print(f"[DEBUG] Matching {len(all_segments)} raw segments to timestamps...")
    
    for seg in all_segments:
        try:
            # 1. Parse Reference Time
            ref_time_str = seg.get('start_time_ref', '(0s)')
            ref_time_val = 0
            try:
                if isinstance(ref_time_str, str):
                    match = re.search(r'\d+', ref_time_str)
                    if match:
                         ref_time_val = int(match.group())
                else:
                    ref_time_val = int(ref_time_str)
            except:
                ref_time_val = 0
                
            # Find segment index closest to ref_time
            start_idx = 0
            min_diff = 999999
            for i, s in enumerate(transcript_segments):
                diff = abs(s['start'] - ref_time_val)
                if diff < min_diff:
                    min_diff = diff
                    start_idx = i
                if s['start'] > ref_time_val + 10: 
                    break
            
            # Backtrack
            start_idx = max(0, start_idx - 5)
            
            # 2. Find Exact Start Text
            start_text_target = seg.get('start_text', '').lower().strip()
            # Normalize
            start_text_target = re.sub(r'[^\w\s]', '', start_text_target)
            
            final_start_time = -1
            match_start_idx = -1
            
            # Search window
            search_limit = min(len(transcript_segments), start_idx + 50)
            
            for i in range(start_idx, search_limit):
                s_text = transcript_segments[i]['text'].lower()
                s_text = re.sub(r'[^\w\s]', '', s_text)
                
                # Check for partial match
                if start_text_target and (start_text_target in s_text or s_text in start_text_target):
                    final_start_time = transcript_segments[i]['start']
                    match_start_idx = i
                    break
            
            # Fallback
            if final_start_time == -1:
                final_start_time = transcript_segments[start_idx]['start'] if start_idx < len(transcript_segments) else ref_time_val
                match_start_idx = start_idx

            # 3. Find End Text
            end_text_target = seg.get('end_text', '').lower().strip()
            end_text_target = re.sub(r'[^\w\s]', '', end_text_target)
            
            final_end_time = -1
            
            if match_start_idx != -1:
                search_end_limit = min(len(transcript_segments), match_start_idx + 200)
                
                for i in range(match_start_idx, search_end_limit):
                    s_text = transcript_segments[i]['text'].lower()
                    s_text = re.sub(r'[^\w\s]', '', s_text)
                    
                    if end_text_target and (end_text_target in s_text or s_text in end_text_target):
                         final_end_time = transcript_segments[i]['end']
                         break
            
            # Sem end_text válido → descartar para evitar fallback que cria
            # durações idênticas (start + min_duration) e mascara duplicatas
            # vindas de chunks com overlap.
            if final_end_time == -1:
                print(f"[WARN] Descartando '{seg.get('title','?')}' — end_text não encontrado na transcrição.")
                continue

            # Calculate Duration
            duration = final_end_time - final_start_time
            
            # Validate Duration (Min)
            if duration < tempo_minimo: 
                print(f"[WARN] Segmento menor que duration min ({duration:.2f}s < {tempo_minimo}s). Estendendo para {tempo_minimo}s.")
                duration = tempo_minimo
                final_end_time = final_start_time + duration
            
            # Validate Duration (Max)
            if duration > tempo_maximo:
                print(f"[WARN] Segmento excede max duration ({duration:.2f}s > {tempo_maximo}s). Cortando para {tempo_maximo}s.")
                final_end_time = final_start_time + tempo_maximo
                duration = tempo_maximo

            # --- Margem de segurança (buffer) ---
            # Exportamos o corte LIMPO detectado pela IA. A margem de segurança
            # (até 5s por lado) NÃO é aplicada de primeira — fica disponível como
            # "saldo" e o usuário pode adicioná-la por corte na Biblioteca (botão
            # Reprocessar), que recalcula a partir de original_start/original_end
            # usando o input.mp4 completo. Assim nenhum vídeo sai com buffer embutido.
            original_start = final_start_time
            original_end = final_end_time

            # Construct Final Segment (corte limpo; margem fica como saldo)
            processed_segments.append({
                "title": seg.get('title', 'Viral Segment'),
                "start_time": original_start,
                "end_time": original_end,
                "original_start_time": original_start,
                "original_end_time": original_end,
                "buffer_start_used": 0,
                "buffer_end_used": 0,
                "hook": seg.get('title', ''),
                "reasoning": seg.get('reasoning', ''),
                "score": seg.get('score', 0),
                "duration": original_end - original_start
            })

        except Exception as e:
            print(f"[WARN] Error processing segment {seg}: {e}")
            continue

    # Deduplication estrita: zero sobreposição entre janelas de tempo
    # E centros separados por pelo menos metade do `min_duration` (com teto
    # de 30s), para evitar cortes vizinhos cobrindo a mesma cena.
    try:
        sep = max(5.0, min(float(tempo_minimo) / 2.0, 30.0)) if tempo_minimo else 5.0
    except (TypeError, ValueError):
        sep = 5.0
    all_segments = dedupe_non_overlapping(processed_segments, min_separation=sep)
    print(f"[DEBUG] Finished processing. {len(all_segments)} segments valid.")

    if output_count and len(all_segments) > output_count:
        print(f"Filtrando os top {output_count} segmentos de {len(all_segments)} candidatos encontrados nos chunks.")
        all_segments = all_segments[:output_count]

    final_result = {"segments": all_segments}
    
    # Validação básica de que temos start_time
    validated_segments = []
    for seg in final_result['segments']:
        if 'start_time' in seg:
             validated_segments.append(seg)
    
    final_result['segments'] = validated_segments
    
    return final_result


def create(num_segments, viral_mode, themes, tempo_minimo, tempo_maximo, ai_mode="manual", api_key=None, project_folder="tmp", chunk_size_arg=None, model_name_arg=None, ai_duration=False, hook_mode=False):
    quantidade_de_virals = num_segments

    # 1. Load Transcript
    transcript_segments = load_transcript(project_folder)

    # 2. Pre-process Content
    formatted_content = preprocess_transcript_for_ai(transcript_segments)
    content = formatted_content

    # Load Config and Prompt
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'api_config.json')
    # Modo gancho: usa o prompt alternativo focado no primeiro segundo do corte.
    prompt_path = os.path.join(base_dir, 'prompt_hook.txt' if hook_mode else 'prompt.txt')
    if hook_mode:
        if os.path.exists(prompt_path):
            print("[INFO] Modo Gancho ativado: usando prompt_hook.txt.")
        else:
            print("Aviso: prompt_hook.txt não encontrado. Usando prompt.txt padrão.")
            prompt_path = os.path.join(base_dir, 'prompt.txt')

    config = {
        "selected_api": "gemini",
        "gemini": {
            "api_key": "",
            "model": "gemini-3.7-flash",
            "chunk_size": 70000
        }
    }

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                if "gemini" in loaded_config: config["gemini"].update(loaded_config["gemini"])
                if "selected_api" in loaded_config: config["selected_api"] = loaded_config["selected_api"]
        except Exception as e:
            print(f"Erro ao ler api_config.json: {e}")

    # Config Vars
    current_chunk_size = 70000
    model_name = ""

    if ai_mode == "gemini":
        cfg_chunk = config["gemini"].get("chunk_size", 70000)
        current_chunk_size = chunk_size_arg if chunk_size_arg and int(chunk_size_arg) > 0 else cfg_chunk
        cfg_model = config["gemini"].get("model", "gemini-3.7-flash")
        model_name = model_name_arg if model_name_arg else cfg_model
        if not api_key: api_key = config["gemini"].get("api_key", "")

    system_prompt_template = ""
    if os.path.exists(prompt_path):
        with open(prompt_path, 'r', encoding='utf-8') as f:
            system_prompt_template = f.read()
    else:
        print("Aviso: prompt.txt não encontrado. Usando prompt interno.")
        system_prompt_template = """You are a World-Class Viral Video Editor.
{context_instruction}
Analyze the transcript below with time tags (XXs). Find {amount} viral segments.
Constraints: Each segment MUST be between {min_duration} seconds and {max_duration} seconds.
IMPORTANT: Output "Title", "Hook", and "Reasoning" in the SAME LANGUAGE as the transcript (e.g., if transcript is Portuguese, output Portuguese).
TRANSCRIPT:
{transcript_chunk}
OUTPUT JSON ONLY:
{json_template}"""


    json_template = '''
            { "segments" :
                [
                    {
                        "start_text": "Exact first 5-10 words of the segment",
                        "end_text": "Exact last 5-10 words of the segment",
                        "start_time_ref": "Value of closest (XXs) tag",
                        "title": "Viral Hook Title (Same Language as Transcript)",
                        "reasoning": "Why this is viral? Hook? Value? (Same Language as Transcript)",
                        "score": 95
                    }
                ]
            }
        '''

    # Chunking
    chunk_size = int(current_chunk_size)
    overlap_size = max(1000, int(chunk_size * 0.1))
    
    chunks = []
    start = 0
    content_len = len(content)

    print(f"[DEBUG] Chunking content (Size: {content_len}) with Chunk Size: {chunk_size} and Overlap: {overlap_size}")

    while start < content_len:
        end = min(start + chunk_size, content_len)
        if end < content_len:
            last_space = content.rfind(' ', start, end)
            if last_space != -1 and last_space > start:
                end = last_space
        chunk_text = content[start:end]
        if chunk_text.strip():
            chunks.append(chunk_text)
        if end >= content_len:
            break
        next_start = max(start + 1, end - overlap_size)
        safe_space = content.rfind(' ', start, next_start)
        if safe_space != -1:
            start = safe_space + 1
        else:
            start = next_start

    # Distribuir a cota de segmentos pelos chunks com folga. A IA costuma
    # gerar candidatos sobrepostos (mesma cena descrita de ângulos diferentes),
    # e o dedupe posterior os descarta — então pedimos ~1.4x mais para que
    # após a deduplicação reste perto do alvo `quantidade_de_virals`. Para
    # múltiplos chunks, a folga é distribuída entre eles.
    num_chunks = max(1, len(chunks))
    target_with_slack = max(quantidade_de_virals + 2, math.ceil(quantidade_de_virals * 1.4))
    if num_chunks > 1:
        per_chunk_amount = max(2, math.ceil(target_with_slack / num_chunks))
    else:
        per_chunk_amount = target_with_slack
    print(f"[DEBUG] Pedindo até {per_chunk_amount} candidato(s) por chunk ({num_chunks} chunks). Alvo final após dedup: {quantidade_de_virals}.")

    if viral_mode:
        virality_instruction = (
            "Selecione APENAS os momentos de PICO do sermão — os que fariam alguém parar de rolar o feed.\n"
            "Priorize, nesta ordem:\n"
            "1. Frases de impacto: declarações ousadas, contraintuitivas ou que geram tensão (\"uau\").\n"
            "2. Verdades espirituais profundas ditas de forma memorável e CITÁVEL.\n"
            "3. Histórias/ilustrações vívidas com início, clímax e desfecho.\n"
            "4. Momentos de convicção/confronto OU de forte encorajamento e esperança.\n"
            "5. Chamados claros à decisão ou à ação.\n"
            "Seja EXIGENTE: prefira devolver POUCOS cortes excelentes a muitos medianos. "
            "Dê notas (score) honestas — reserve 90+ apenas para momentos realmente fortes."
        )
    else:
        virality_instruction = (
            "Selecione os melhores momentos do sermão focados ESTRITAMENTE nos seguintes temas/assuntos: "
            f"{themes}.\n"
            "Dentro desses temas, priorize frases de impacto, verdades memoráveis e citáveis, "
            "histórias vívidas e chamados à ação. Seja exigente com a qualidade."
        )

    # Instrução de duração: com teto de segurança (IA decide) ou faixa fixa mín–máx.
    if ai_duration:
        duration_instruction = (
            "DURAÇÃO: NÃO há tempo mínimo — priorize entregar a ideia completa, do gancho à conclusão. "
            f"O trecho pode ir de poucos segundos até no MÁXIMO {tempo_maximo}s. "
            "Se a ideia não couber nesse teto, escolha um recorte menor e completo em vez de cortar no meio. "
            "Nunca termine no meio de uma frase ou de um versículo."
        )
    else:
        duration_instruction = (
            f"DURAÇÃO: cada trecho DEVE ter entre {tempo_minimo}s e {tempo_maximo}s. "
            "Use as marcas (XXs) para estimar a duração."
        )

    output_texts = []
    for i, chunk in enumerate(chunks):
        context_instruction = ""
        if len(chunks) > 1:
            context_instruction = f"Part {i+1} of {len(chunks)}. "

        try:
            prompt = system_prompt_template.format(
                context_instruction=context_instruction,
                virality_instruction=virality_instruction,
                duration_instruction=duration_instruction,
                min_duration=tempo_minimo,
                max_duration=tempo_maximo,
                transcript_chunk=chunk,
                json_template=json_template,
                amount=per_chunk_amount
            )
        except KeyError as e:
            prompt = system_prompt_template
            prompt = prompt.replace("{context_instruction}", context_instruction)
            prompt = prompt.replace("{virality_instruction}", virality_instruction)
            prompt = prompt.replace("{duration_instruction}", duration_instruction)
            prompt = prompt.replace("{min_duration}", str(tempo_minimo))
            prompt = prompt.replace("{max_duration}", str(tempo_maximo))
            prompt = prompt.replace("{transcript_chunk}", chunk)
            prompt = prompt.replace("{json_template}", json_template)
            prompt = prompt.replace("{amount}", str(per_chunk_amount))

        output_texts.append(prompt)

    try:
        full_prompt_path = os.path.join(project_folder, "prompt_full.txt")
        full_prompt = system_prompt_template
        full_prompt = full_prompt.replace("{context_instruction}", "Full Video Transcript Analysis")
        full_prompt = full_prompt.replace("{virality_instruction}", virality_instruction)
        full_prompt = full_prompt.replace("{duration_instruction}", duration_instruction)
        full_prompt = full_prompt.replace("{min_duration}", str(tempo_minimo))
        full_prompt = full_prompt.replace("{max_duration}", str(tempo_maximo))
        full_prompt = full_prompt.replace("{transcript_chunk}", content)
        full_prompt = full_prompt.replace("{json_template}", json_template)
        full_prompt = full_prompt.replace("{amount}", str(quantidade_de_virals))
        
        with open(full_prompt_path, "w", encoding="utf-8") as f:
            f.write(full_prompt)
    except Exception as e:
        print(f"[WARN] Could not save prompt_full.txt: {e}")

    all_raw_segments = []

    print(f"Processando {len(output_texts)} chunks usando modo: {ai_mode.upper()}")

    for i, prompt in enumerate(output_texts):
        response_text = ""
        manual_prompt_path = os.path.join(project_folder, f"prompt_part_{i+1}.txt")
        try:
            with open(manual_prompt_path, "w", encoding="utf-8") as f:
                f.write(prompt)
        except Exception as e:
            print(f"[ERRO] Falha ao salvar prompt.txt: {e}")
        
        if ai_mode == "manual_webui":
            print(f"\n[INFO] O prompt completo foi salvo em: prompt_full.txt na pasta do projeto.")
            print("\n[PAUSE_FOR_MANUAL_WEBUI]")
            return {"segments": [], "paused_for_manual": True}

        elif ai_mode == "gemini":
            print(f"Enviando chunk {i+1} para o Gemini (Model: {model_name})...")
            response_text = call_gemini(prompt, api_key, model_name=model_name)

        # --- Save RAW Response for Debugging ---
        try:
            raw_response_path = os.path.join(project_folder, f"response_raw_part_{i+1}.txt")
            with open(raw_response_path, "w", encoding="utf-8") as f:
                f.write(response_text)
            print(f"[DEBUG] Raw response saved to: {raw_response_path}")
        except Exception as e:
            print(f"[WARN] Failed to save raw response: {e}")

        # Processar resposta
        try:
            data = clean_json_response(response_text)
            chunk_segments = data.get("segments", [])
            print(f"Encontrados {len(chunk_segments)} segmentos neste chunk.")
            all_raw_segments.extend(chunk_segments)
        except json.JSONDecodeError:
            print(f"Erro: Resposta inválida.")
        except Exception as e:
            print(f"Erro desconhecido ao processar chunk: {e}")

    # Dedupe inter-chunk: remove candidatos brutos que são o mesmo segmento
    # detectado em chunks vizinhos (overlap), ANTES do alinhamento — evita que
    # o fallback de duração mascare a duplicata.
    print(f"[DEBUG] Total de candidatos brutos antes do dedupe inter-chunk: {len(all_raw_segments)}")
    all_raw_segments = dedupe_raw_candidates(all_raw_segments)
    print(f"[DEBUG] Total de candidatos após dedupe inter-chunk: {len(all_raw_segments)}")

    # Call the alignment / processing logic.
    # Com "IA decide a duração", não há mínimo: passamos 0 para desativar a trava
    # que estenderia cortes curtos. O máximo (tempo_maximo) segue como teto de segurança.
    proc_min = 0 if ai_duration else tempo_minimo
    return process_segments(
        all_raw_segments,
        transcript_segments,
        proc_min,
        tempo_maximo,
        output_count=quantidade_de_virals
    )
