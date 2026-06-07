"""
Rastreia quais efeitos já estão embutidos em cada corte renderizado.

Cada projeto guarda um VIRALS/<projeto>/render_state.json no formato:
    { "segments": { "0": {"subtitles": true, "watermark": false, ...}, ... } }

`true` = o efeito está embutido no vídeo atual em burned_sub/. É a base para os
botões "Aplicar X" da Biblioteca decidirem entre ativo (ainda não aplicado neste
corte) e cinza (já aplicado).

Não tem dependências além de json/os de propósito — é importado pelo pipeline
(main_improved.py), pelo render por-corte (subtitle_editor.py) e pela Biblioteca.
"""
import json
import os

STATE_FILE = "render_state.json"

# Recursos rastreados. `subtitles` é sempre embutido (sempre queimado no pipeline).
FEATURE_KEYS = ("subtitles", "watermark", "outro", "audio_bgm", "outro_music", "source_volume")


def _state_path(project_folder):
    return os.path.join(project_folder, STATE_FILE)


def load_state(project_folder):
    path = _state_path(project_folder)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("segments"), dict):
                return data
        except Exception as e:
            print(f"[render_state] Falha ao ler {path}: {e}")
    return {"segments": {}}


def save_state(project_folder, data):
    path = _state_path(project_folder)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[render_state] Falha ao salvar {path}: {e}")
        return False


def _default_features():
    feats = {k: False for k in FEATURE_KEYS}
    feats["subtitles"] = True
    return feats


def get_segment_features(project_folder, index):
    """Flags de um segmento. Sem registro → tudo False (exceto subtitles=True)."""
    feats = _default_features()
    stored = load_state(project_folder).get("segments", {}).get(str(index))
    if isinstance(stored, dict):
        for k in FEATURE_KEYS:
            if k in stored:
                feats[k] = bool(stored[k])
    return feats


def set_segment_features(project_folder, index, features):
    """Mescla as flags informadas para um segmento e salva."""
    data = load_state(project_folder)
    segs = data.setdefault("segments", {})
    cur = segs.get(str(index)) if isinstance(segs.get(str(index)), dict) else {}
    cur.update({k: bool(v) for k, v in features.items() if k in FEATURE_KEYS})
    segs[str(index)] = cur
    save_state(project_folder, data)


def set_all_segments(project_folder, indices, features):
    """Aplica as mesmas flags a vários segmentos (usado no render inicial do pipeline)."""
    data = load_state(project_folder)
    segs = data.setdefault("segments", {})
    clean = {k: bool(v) for k, v in features.items() if k in FEATURE_KEYS}
    for i in indices:
        cur = segs.get(str(i)) if isinstance(segs.get(str(i)), dict) else {}
        cur.update(clean)
        segs[str(i)] = cur
    save_state(project_folder, data)


# ----------------------------------------------------------------------------
# Leitura dos configs da raiz para decidir o que um render do zero embutiria.
# ----------------------------------------------------------------------------
def _read_json(root_dir, name):
    p = os.path.join(root_dir, name)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _path_exists(root_dir, path):
    if not path:
        return False
    # Normaliza separadores: um config salvo no Windows ("WEBUI_ASSETS\\x.png") precisa
    # resolver no Colab/Linux e vice-versa.
    norm = path.replace("\\", "/")
    is_windows_abs = len(norm) > 1 and norm[1] == ":"
    if os.path.isabs(norm) or is_windows_abs:
        return os.path.exists(path)
    return os.path.exists(os.path.join(root_dir, *[p for p in norm.split("/") if p]))


def _source_volume(audio_cfg):
    try:
        return float(audio_cfg.get("source_video_volume", 200.0))
    except (TypeError, ValueError):
        return 200.0


def compute_enabled_features(root_dir):
    """
    Espelha as condições de aplicação de render_specific_video / main_improved:
    o conjunto de efeitos que um render do zero embutiria AGORA, com base apenas
    nas flags `enabled` (a música de encerramento exige o vídeo de outro ativo).
    """
    wm = _read_json(root_dir, "watermark_config.json")
    outro = _read_json(root_dir, "outro_config.json")
    audio = _read_json(root_dir, "audio_config.json")
    om = audio.get("outro_music", {}) if isinstance(audio.get("outro_music"), dict) else {}

    outro_on = bool(outro.get("enabled", False))
    return {
        "subtitles": True,
        "watermark": bool(wm.get("enabled", False)),
        "outro": outro_on,
        "audio_bgm": bool(audio.get("enabled", False)),
        "outro_music": bool(om.get("enabled", False)) and outro_on,
        "source_volume": abs(_source_volume(audio) - 100.0) > 0.001,
    }


def feature_enabled_and_configured(root_dir, feature):
    """
    Validação dos botões 'Aplicar X': o recurso está ativado E com arquivo pronto?
    Devolve (ok: bool, motivo: str).
    """
    wm = _read_json(root_dir, "watermark_config.json")
    outro = _read_json(root_dir, "outro_config.json")
    audio = _read_json(root_dir, "audio_config.json")
    om = audio.get("outro_music", {}) if isinstance(audio.get("outro_music"), dict) else {}
    outro_ok = bool(outro.get("enabled", False)) and _path_exists(root_dir, outro.get("outro_video_path"))

    if feature == "watermark":
        if bool(wm.get("enabled", False)) and _path_exists(root_dir, wm.get("watermark_image_path")):
            return True, ""
        return False, "Ative e configure a Marca d'Água na aba primeiro."
    if feature == "outro":
        if outro_ok:
            return True, ""
        return False, "Ative e configure o Outro/Encerramento na aba primeiro."
    if feature == "audio_bgm":
        if bool(audio.get("enabled", False)) and _path_exists(root_dir, audio.get("audio_file_path")):
            return True, ""
        return False, "Ative e configure o Áudio BGM na aba primeiro."
    if feature == "outro_music":
        if bool(om.get("enabled", False)) and _path_exists(root_dir, om.get("audio_file_path")) and outro_ok:
            return True, ""
        return False, "Ative a Música de Encerramento e o vídeo de Outro na aba primeiro."
    return False, f"Recurso desconhecido: {feature}"
