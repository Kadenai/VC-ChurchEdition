import os
import json

try:
    from media_utils import (
        build_file_url,
        build_file_url_candidates,
        extract_file_path,
        persist_uploaded_file,
        resolve_existing_path,
    )
except ImportError:
    from webui.media_utils import (
        build_file_url,
        build_file_url_candidates,
        extract_file_path,
        persist_uploaded_file,
        resolve_existing_path,
    )

CONFIG_FILE = "audio_config.json"

DEFAULT_OUTRO_MUSIC_CONFIG = {
    "enabled": True,
    "audio_file_path": "WEBUI_ASSETS/audio/Sacred_Reflections_1777226629_309f30c2_1777229952_464350b7_1777230878_e0cdcc3d_1777233772_9f2e0a90_1777242995_db6a232f_1777825066_69923054_1779040978_dd64358e.mp3",
    "volume": 50,
    "start_from": "end",
    "fade_in_duration": 1,
    "fade_out_enabled": True,
    "fade_out_duration": 1,
}

DEFAULT_AUDIO_CONFIG = {
    "enabled": False,
    "audio_file_path": "WEBUI_ASSETS/audio/Glass_on_the_Keys_1779040978_9d23bb01.mp3",
    "base_volume": 12,
    "source_video_volume": 200.0,
    "loop_to_end": True,
    "fade_in_duration": 0.5,
    "fade_out_duration": 0.5,
    "crossfade_duration": 3.0,
    "use_ending_volume": True,
    "stop_before_outro": True,
    "sync_with_outro": True,
    "ending_volume": 20,
    "ending_start_time": 10,
    "outro_music": dict(DEFAULT_OUTRO_MUSIC_CONFIG),
}

def _clamp_source_video_volume(value):
    try:
        volume = float(value)
    except (TypeError, ValueError):
        volume = 200.0
    return max(0.0, min(200.0, volume))

# audio_config.json handler
def load_audio_config():
    config = dict(DEFAULT_AUDIO_CONFIG)
    config["outro_music"] = dict(DEFAULT_OUTRO_MUSIC_CONFIG)  # ensure fresh copy

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    # Merge top-level keys
                    for k, v in loaded.items():
                        if k != "outro_music":
                            config[k] = v
                    # Merge outro_music sub-dict with defaults (safe)
                    if "outro_music" in loaded and isinstance(loaded["outro_music"], dict):
                        merged_outro = dict(DEFAULT_OUTRO_MUSIC_CONFIG)
                        merged_outro.update(loaded["outro_music"])
                        config["outro_music"] = merged_outro
        except Exception as e:
            print(f"Error loading audio config: {e}")

    # Resolve file paths
    config["audio_file_path"] = resolve_existing_path(config.get("audio_file_path"))
    config["source_video_volume"] = _clamp_source_video_volume(config.get("source_video_volume", 200.0))

    # Resolve outro_music file path
    outro = config.get("outro_music", {})
    outro["audio_file_path"] = resolve_existing_path(outro.get("audio_file_path"))
    config["outro_music"] = outro

    return config

def save_audio_config(
    enabled, audio_file_path, base_volume, loop_to_end,
    fade_in_duration, fade_out_duration, crossfade_duration,
    use_ending_volume, stop_before_outro, sync_with_outro,
    ending_volume, ending_start_time,
    source_video_volume=None,
    # outro_music fields
    outro_music_enabled=True,
    outro_music_file=None,
    outro_music_volume=50,
    outro_music_start_from="end",
    outro_music_fade_in=1,
    outro_music_fade_out_enabled=True,
    outro_music_fade_out=1,
):
    existing_cfg = load_audio_config()
    persisted_audio_path = persist_uploaded_file(audio_file_path, "audio")
    if not persisted_audio_path:
        persisted_audio_path = resolve_existing_path(extract_file_path(audio_file_path))
    if not persisted_audio_path:
        persisted_audio_path = existing_cfg.get("audio_file_path")

    if source_video_volume is None:
        source_video_volume = existing_cfg.get("source_video_volume", 200.0)

    # Persist outro music file
    persisted_outro_music_path = persist_uploaded_file(outro_music_file, "audio")
    if not persisted_outro_music_path:
        persisted_outro_music_path = resolve_existing_path(extract_file_path(outro_music_file))
    if not persisted_outro_music_path:
        existing_outro = existing_cfg.get("outro_music", {})
        persisted_outro_music_path = existing_outro.get("audio_file_path")

    config = {
        "enabled": enabled,
        "audio_file_path": persisted_audio_path,
        "base_volume": base_volume,
        "source_video_volume": _clamp_source_video_volume(source_video_volume),
        "loop_to_end": loop_to_end,
        "fade_in_duration": fade_in_duration,
        "fade_out_duration": fade_out_duration,
        "crossfade_duration": crossfade_duration,
        "use_ending_volume": use_ending_volume,
        "stop_before_outro": stop_before_outro,
        "sync_with_outro": sync_with_outro,
        "ending_volume": ending_volume,
        "ending_start_time": ending_start_time,
        "outro_music": {
            "enabled": outro_music_enabled,
            "audio_file_path": persisted_outro_music_path,
            "volume": outro_music_volume,
            "start_from": outro_music_start_from if outro_music_start_from in ("start", "end") else "end",
            "fade_in_duration": outro_music_fade_in,
            "fade_out_enabled": outro_music_fade_out_enabled,
            "fade_out_duration": outro_music_fade_out,
        },
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return "Configurações de Áudio salvas com sucesso!"
    except Exception as e:
        return f"Erro ao salvar configurações: {e}"


def save_source_video_volume(source_video_volume):
    config = load_audio_config()
    config["source_video_volume"] = _clamp_source_video_volume(source_video_volume)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return "Volume do vídeo original salvo com sucesso!"
    except Exception as e:
        return f"Erro ao salvar volume do vídeo original: {e}"

def generate_audio_preview(video_file, audio_file, base_volume, loop_bgm=True):
    if not video_file or not audio_file:
        return '<div style="padding: 20px; text-align: center; color: #888;">Faça o upload de um Vídeo Teste e do arquivo de Áudio BGM BGM para testar o volume em tempo real.</div>'

    vid_path = resolve_existing_path(extract_file_path(video_file))
    aud_path = resolve_existing_path(extract_file_path(audio_file))
    
    if not vid_path or not aud_path:
        return '<div style="padding: 20px; text-align: center; color: #888;">Arquivos não encontrados no disco.</div>'

    vid_url = build_file_url(vid_path)
    aud_url = build_file_url(aud_path)
    vid_candidates = json.dumps(build_file_url_candidates(vid_path))
    aud_candidates = json.dumps(build_file_url_candidates(aud_path))
    loop_js = "true" if loop_bgm else "false"
    loop_attr = "loop" if loop_bgm else ""
    
    html = f"""
    <div style="width: 100%; max-width: 480px; margin: 0 auto; background: #111; border-radius: 8px; overflow: hidden; border: 1px solid #333;">
        <video id="audio_preview_vid" controls playsinline preload="metadata" data-candidates='{vid_candidates}' style="width: 100%; display: block; max-height: 480px; background: #000;">
            <source src="{vid_url}" type="video/mp4">
        </video>
        <audio id="audio_preview_aud" src="{aud_url}" data-candidates='{aud_candidates}' {loop_attr}></audio>
        <div style="padding: 10px; text-align: center; color: #888; font-size: 13px;">
            Dê <b>play no vídeo</b> e o áudio iniciará sincronizado com ele.<br>
            Você pode testar a barra de busca e alterar o volume em tempo real.
        </div>
        <img src="dummy" onerror="(function() {{
            const v = document.getElementById('audio_preview_vid');
            const a = document.getElementById('audio_preview_aud');
            if(!v || !a) {{
                return;
            }}

            const loopEnabled = {loop_js};
            a.loop = loopEnabled;

            const parseCandidates = (el) => {{
                try {{
                    return JSON.parse(el.dataset.candidates || '[]');
                }} catch (err) {{
                    return [];
                }}
            }};

            const applyFallback = (el, candidates, isVideo) => {{
                let idx = 0;
                const applyNext = () => {{
                    if (idx >= candidates.length) {{
                        return false;
                    }}
                    const nextSrc = candidates[idx++];
                    if (isVideo) {{
                        const srcEl = el.querySelector('source');
                        if (srcEl) {{
                            srcEl.src = nextSrc;
                        }} else {{
                            el.src = nextSrc;
                        }}
                    }} else {{
                        el.src = nextSrc;
                    }}
                    if (typeof el.load === 'function') {{
                        el.load();
                    }}
                    return true;
                }};

                el.addEventListener('error', () => {{
                    applyNext();
                }});
                applyNext();
            }};

            applyFallback(v, parseCandidates(v), true);
            applyFallback(a, parseCandidates(a), false);

            const waitCanPlay = (mediaEl) => new Promise((resolve) => {{
                if (mediaEl.readyState >= 2) {{
                    resolve();
                    return;
                }}
                const done = () => resolve();
                mediaEl.addEventListener('canplay', done, {{ once: true }});
                setTimeout(done, 3000);
            }});

            Promise.all([waitCanPlay(v), waitCanPlay(a)]).then(() => {{
                a.volume = {base_volume} / 100.0;

                v.onplay = () => a.play().catch((err) => console.warn('Audio preview play failed:', err));
                v.onpause = () => a.pause();
                v.onseeked = () => {{
                    if (!isNaN(a.duration) && a.duration > 0) {{
                        a.currentTime = loopEnabled ? (v.currentTime % a.duration) : Math.min(v.currentTime, a.duration);
                    }} else {{
                        a.currentTime = v.currentTime;
                    }}
                }};
            }});
        }})(); this.remove();" style="display:none;" />
    </div>
    """
    return html
