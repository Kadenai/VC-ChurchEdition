import copy
import json
import os
import time

try:
    import render_state
except ImportError:
    from webui import render_state

try:
    import audio_handler
    import outro_handler
    import watermark_handler
    from media_utils import PROJECT_ROOT, resolve_existing_path, to_project_relative
except ImportError:
    from webui import audio_handler, outro_handler, watermark_handler
    from webui.media_utils import PROJECT_ROOT, resolve_existing_path, to_project_relative


STATE_FILE = "segment_edit_state.json"
FEATURE_KEYS = ("subtitles", "watermark", "outro", "audio_bgm", "outro_music", "source_volume")


def _state_path(project_folder):
    return os.path.join(project_folder, STATE_FILE)


def _read_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return copy.deepcopy(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else copy.deepcopy(default)
    except Exception as e:
        print(f"[segment_editor_state] Falha ao ler {path}: {e}")
        return copy.deepcopy(default)


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_state(project_folder):
    data = _read_json(_state_path(project_folder), {"version": 1, "segments": {}})
    if not isinstance(data.get("segments"), dict):
        data["segments"] = {}
    data.setdefault("version", 1)
    return data


def save_state(project_folder, data):
    data.setdefault("version", 1)
    if not isinstance(data.get("segments"), dict):
        data["segments"] = {}
    _atomic_write_json(_state_path(project_folder), data)
    return True


def _storage_path(path_value):
    if not path_value:
        return None
    resolved = resolve_existing_path(path_value)
    if resolved:
        return to_project_relative(resolved)
    text = str(path_value).replace("\\", "/")
    return text or None


def _normalize_watermark_config(config):
    cfg = copy.deepcopy(config or {})
    cfg["enabled"] = bool(cfg.get("enabled", False))
    cfg["watermark_image_path"] = _storage_path(cfg.get("watermark_image_path"))
    cfg["position_x"] = int(float(cfg.get("position_x", 480) or 0))
    cfg["position_y"] = int(float(cfg.get("position_y", 0) or 0))
    cfg["scale"] = int(float(cfg.get("scale", 15) or 15))
    cfg["opacity"] = int(float(cfg.get("opacity", 30) or 30))
    return cfg


def _clamp_float(value, default, low=None, high=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if low is not None:
        parsed = max(float(low), parsed)
    if high is not None:
        parsed = min(float(high), parsed)
    return parsed


def _normalize_audio_config(config):
    base = copy.deepcopy(audio_handler.DEFAULT_AUDIO_CONFIG)
    loaded = copy.deepcopy(config or {})
    outro_music = copy.deepcopy(audio_handler.DEFAULT_OUTRO_MUSIC_CONFIG)
    if isinstance(loaded.get("outro_music"), dict):
        outro_music.update(loaded.get("outro_music") or {})
    for key, value in loaded.items():
        if key != "outro_music":
            base[key] = value
    base["enabled"] = bool(base.get("enabled", False))
    base["audio_file_path"] = _storage_path(base.get("audio_file_path"))
    base["base_volume"] = _clamp_float(base.get("base_volume"), 12, 0, 100)
    base["source_video_volume"] = _clamp_float(base.get("source_video_volume"), 200, 0, 200)
    base["loop_to_end"] = bool(base.get("loop_to_end", True))
    base["fade_in_duration"] = _clamp_float(base.get("fade_in_duration"), 0.5, 0, 60)
    base["fade_out_duration"] = _clamp_float(base.get("fade_out_duration"), 0.5, 0, 60)
    base["crossfade_duration"] = _clamp_float(base.get("crossfade_duration"), 3, 0, 60)
    base["use_ending_volume"] = bool(base.get("use_ending_volume", True))
    base["stop_before_outro"] = bool(base.get("stop_before_outro", True))
    base["sync_with_outro"] = bool(base.get("sync_with_outro", True))
    base["ending_volume"] = _clamp_float(base.get("ending_volume"), 20, 0, 100)
    base["ending_start_time"] = _clamp_float(base.get("ending_start_time"), 10, 0, 600)

    outro_music["enabled"] = bool(outro_music.get("enabled", False))
    outro_music["audio_file_path"] = _storage_path(outro_music.get("audio_file_path"))
    outro_music["volume"] = _clamp_float(outro_music.get("volume"), 50, 0, 100)
    outro_music["start_from"] = outro_music.get("start_from") if outro_music.get("start_from") in ("start", "end") else "end"
    outro_music["fade_in_duration"] = _clamp_float(outro_music.get("fade_in_duration"), 1, 0, 60)
    outro_music["fade_out_enabled"] = bool(outro_music.get("fade_out_enabled", True))
    outro_music["fade_out_duration"] = _clamp_float(outro_music.get("fade_out_duration"), 1, 0, 60)
    base["outro_music"] = outro_music
    return base


def _normalize_outro_config(config):
    cfg = copy.deepcopy(config or {})
    cfg["enabled"] = bool(cfg.get("enabled", False))
    cfg["outro_video_path"] = _storage_path(cfg.get("outro_video_path"))
    cfg["overlay_image_path"] = _storage_path(cfg.get("overlay_image_path"))
    cfg["position_x"] = int(float(cfg.get("position_x", 179) or 0))
    cfg["position_y"] = int(float(cfg.get("position_y", 886) or 0))
    cfg["scale"] = int(float(cfg.get("scale", 42) or 42))
    cfg["fade_duration"] = _clamp_float(cfg.get("fade_duration"), 1, 0, 30)
    cfg["rounded_corners"] = int(float(cfg.get("rounded_corners", 10) or 0))
    cfg["outro_volume"] = _clamp_float(cfg.get("outro_volume"), 100, 0, 200)
    return cfg


def _default_subtitle_config(project_folder):
    # Prefer the config used when the project was originally created, then fall
    # back to the current global subtitle config/defaults.
    process_config = _read_json(os.path.join(project_folder, "process_config.json"))
    if isinstance(process_config.get("subtitle_config"), dict):
        return copy.deepcopy(process_config["subtitle_config"])

    try:
        from main_improved import get_subtitle_config
        config_path = os.path.join(PROJECT_ROOT, "temp_subtitle_config.json")
        return get_subtitle_config(config_path if os.path.exists(config_path) else None)
    except Exception:
        return {
            "font": "Montserrat",
            "base_size": 30,
            "base_color": "&H00FFFFFF&",
            "highlight_color": "&H00FFFFFF&",
            "outline_color": "&H00000000&",
            "outline_thickness": 1,
            "shadow_color": "&H00000000&",
            "shadow_size": 1,
            "vertical_position": 140,
            "margin_h": 35,
            "alignment": 2,
            "bold": 1,
            "italic": 0,
            "underline": 0,
            "strikeout": 0,
            "border_style": 1,
            "words_per_block": 4,
            "gap_limit": 0.6,
            "mode": "no_highlight",
            "highlight_size": 30,
            "uppercase": 0,
            "remove_punctuation": False,
        }


def _normalize_subtitle_config(config):
    cfg = copy.deepcopy(config or {})
    cfg["font"] = str(cfg.get("font") or "Montserrat")
    cfg["base_size"] = int(float(cfg.get("base_size", 30) or 30))
    cfg["highlight_size"] = int(float(cfg.get("highlight_size", cfg["base_size"]) or cfg["base_size"]))
    for key, default in (
        ("base_color", "&H00FFFFFF&"),
        ("highlight_color", "&H00FFFFFF&"),
        ("outline_color", "&H00000000&"),
        ("shadow_color", "&H00000000&"),
    ):
        cfg[key] = str(cfg.get(key) or default)
    cfg["outline_thickness"] = _clamp_float(cfg.get("outline_thickness"), 1, 0, 20)
    cfg["shadow_size"] = _clamp_float(cfg.get("shadow_size"), 1, 0, 20)
    cfg["vertical_position"] = int(float(cfg.get("vertical_position", 140) or 0))
    cfg["margin_h"] = int(float(cfg.get("margin_h", 35) or 0))
    cfg["alignment"] = int(float(cfg.get("alignment", 2) or 2))
    cfg["bold"] = 1 if bool(cfg.get("bold", 0)) else 0
    cfg["italic"] = 1 if bool(cfg.get("italic", 0)) else 0
    cfg["underline"] = 1 if bool(cfg.get("underline", 0)) else 0
    cfg["strikeout"] = 1 if bool(cfg.get("strikeout", 0)) else 0
    cfg["uppercase"] = 1 if bool(cfg.get("uppercase", 0)) else 0
    cfg["border_style"] = int(float(cfg.get("border_style", 1) or 1))
    cfg["words_per_block"] = int(float(cfg.get("words_per_block", 4) or 4))
    cfg["gap_limit"] = _clamp_float(cfg.get("gap_limit"), 0.6, 0, 20)
    cfg["mode"] = cfg.get("mode") if cfg.get("mode") in ("highlight", "word_by_word", "no_highlight") else "no_highlight"
    cfg["remove_punctuation"] = bool(cfg.get("remove_punctuation", False))
    return cfg


def normalize_configs(project_folder, configs):
    configs = configs if isinstance(configs, dict) else {}
    return {
        "watermark": _normalize_watermark_config(configs.get("watermark")),
        "audio": _normalize_audio_config(configs.get("audio")),
        "outro": _normalize_outro_config(configs.get("outro")),
        "subtitle": _normalize_subtitle_config(configs.get("subtitle")),
    }


def default_segment_state(project_folder, index):
    features = render_state.get_segment_features(project_folder, index)
    watermark_cfg = _normalize_watermark_config(watermark_handler.load_watermark_config())
    audio_cfg = _normalize_audio_config(audio_handler.load_audio_config())
    outro_cfg = _normalize_outro_config(outro_handler.load_outro_config())
    subtitle_cfg = _normalize_subtitle_config(_default_subtitle_config(project_folder))

    watermark_cfg["enabled"] = bool(features.get("watermark", watermark_cfg.get("enabled", False)))
    outro_cfg["enabled"] = bool(features.get("outro", outro_cfg.get("enabled", False)))
    audio_cfg["enabled"] = bool(features.get("audio_bgm", audio_cfg.get("enabled", False)))
    if isinstance(audio_cfg.get("outro_music"), dict):
        audio_cfg["outro_music"]["enabled"] = bool(features.get("outro_music", audio_cfg["outro_music"].get("enabled", False)))
    if not bool(features.get("source_volume", False)):
        audio_cfg["source_video_volume"] = 100.0

    return {
        "features": {k: bool(features.get(k, False)) for k in FEATURE_KEYS},
        "configs": {
            "watermark": watermark_cfg,
            "audio": audio_cfg,
            "outro": outro_cfg,
            "subtitle": subtitle_cfg,
        },
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }


def get_segment_state(project_folder, index, create=True):
    data = load_state(project_folder)
    segments = data.setdefault("segments", {})
    key = str(index)
    if key not in segments and create:
        segments[key] = default_segment_state(project_folder, index)
        save_state(project_folder, data)
    segment_state = segments.get(key) if isinstance(segments.get(key), dict) else None
    if not segment_state:
        return default_segment_state(project_folder, index)
    segment_state.setdefault("features", {})
    segment_state["configs"] = normalize_configs(project_folder, segment_state.get("configs"))
    return segment_state


def update_segment_state(project_folder, index, configs=None, features=None):
    data = load_state(project_folder)
    segments = data.setdefault("segments", {})
    key = str(index)
    current = segments.get(key) if isinstance(segments.get(key), dict) else default_segment_state(project_folder, index)
    if configs is not None:
        current["configs"] = normalize_configs(project_folder, configs)
    if features is not None:
        current["features"] = {k: bool(features.get(k, False)) for k in FEATURE_KEYS}
    current["updated_at"] = int(time.time())
    segments[key] = current
    save_state(project_folder, data)
    return current


def _path_exists(path_value):
    return bool(resolve_existing_path(path_value))


def features_from_configs(configs):
    configs = normalize_configs(PROJECT_ROOT, configs)
    watermark_cfg = configs.get("watermark", {})
    audio_cfg = configs.get("audio", {})
    outro_cfg = configs.get("outro", {})
    outro_music = audio_cfg.get("outro_music", {}) if isinstance(audio_cfg.get("outro_music"), dict) else {}
    outro_on = bool(outro_cfg.get("enabled", False)) and _path_exists(outro_cfg.get("outro_video_path"))
    try:
        source_volume = float(audio_cfg.get("source_video_volume", 100.0))
    except (TypeError, ValueError):
        source_volume = 100.0
    return {
        "subtitles": True,
        "watermark": bool(watermark_cfg.get("enabled", False)) and _path_exists(watermark_cfg.get("watermark_image_path")),
        "outro": outro_on,
        "audio_bgm": bool(audio_cfg.get("enabled", False)) and _path_exists(audio_cfg.get("audio_file_path")),
        "outro_music": bool(outro_music.get("enabled", False)) and _path_exists(outro_music.get("audio_file_path")) and outro_on,
        "source_volume": abs(source_volume - 100.0) > 0.001,
    }
