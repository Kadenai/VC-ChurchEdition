import os
import json
import mimetypes

try:
    from media_utils import build_file_url, build_file_url_candidates, resolve_existing_path
except ImportError:
    from webui.media_utils import build_file_url, build_file_url_candidates, resolve_existing_path


def _extract_file_path(file_obj):
    if not file_obj:
        return None
    if isinstance(file_obj, str):
        return file_obj
    if hasattr(file_obj, "name"):
        return file_obj.name
    if isinstance(file_obj, list) and len(file_obj) > 0:
        first_item = file_obj[0]
        if hasattr(first_item, "name"):
            return first_item.name
        return str(first_item)
    return str(file_obj)


def _clamp_volume_percent(value):
    try:
        vol = float(value)
    except (TypeError, ValueError):
        vol = 200.0
    return max(0.0, min(200.0, vol))


def _guess_video_mime(video_path):
    mime, _ = mimetypes.guess_type(video_path)
    return mime or "video/mp4"


def generate_original_volume_preview(video_file, source_video_volume=200):
    if not video_file:
        return '<div style="padding: 20px; text-align: center; color: #888;">Carregue um video teste para ajustar o volume original em tempo real.</div>'

    video_path = resolve_existing_path(_extract_file_path(video_file))
    if not video_path:
        return '<div style="padding: 20px; text-align: center; color: #888;">Arquivo de video nao encontrado no disco.</div>'

    initial_volume_percent = _clamp_volume_percent(source_video_volume)
    video_url = build_file_url(video_path)
    video_candidates = json.dumps(build_file_url_candidates(video_path))
    video_mime = _guess_video_mime(video_path)

    html = f"""
    <div style="width: 100%; max-width: 760px; margin: 0 auto; background: #111; border-radius: 10px; overflow: hidden; border: 1px solid #333;">
        <video id="original_volume_preview_vid" controls playsinline preload="metadata" data-candidates='{video_candidates}' style="width: 100%; display: block; max-height: 540px; background: #000;">
            <source src="{video_url}" type="{video_mime}">
        </video>
        <div style="padding: 12px; border-top: 1px solid #222;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px; color:#ddd; font-size: 13px;">
                <span>Volume aplicado na previa</span>
                <span id="original_volume_preview_value">{int(round(initial_volume_percent))}%</span>
            </div>
            <canvas id="original_volume_preview_meter" width="736" height="64" style="width:100%; height:64px; background:#0b0b0b; border:1px solid #222; border-radius:6px;"></canvas>
            <div style="padding-top:8px; text-align:center; color:#888; font-size:12px;">
                Clique em play e ajuste o slider para ouvir o resultado em tempo real.
            </div>
        </div>
        <img src="dummy" onerror="(function() {{
            const video = document.getElementById('original_volume_preview_vid');
            const valueLabel = document.getElementById('original_volume_preview_value');
            if (!video) {{
                return;
            }}

            try {{
                const candidates = JSON.parse(video.dataset.candidates || '[]');
                let idx = 0;
                const sourceEl = video.querySelector('source');
                const applyNext = () => {{
                    if (idx >= candidates.length) {{
                        return false;
                    }}
                    const nextSrc = candidates[idx++];
                    if (sourceEl) {{
                        sourceEl.src = nextSrc;
                    }} else {{
                        video.src = nextSrc;
                    }}
                    video.load();
                    return true;
                }};
                video.addEventListener('error', () => {{
                    applyNext();
                }});
                applyNext();
            }} catch (err) {{
                console.warn('Video preview fallback setup failed', err);
            }}

            const sliderLabel = document.getElementById('original_volume_slider_value');
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            const supportsWebAudio = !!AudioCtx;

            let ctx = null;
            let sourceNode = null;
            let gainNode = null;
            let analyserNode = null;
            let usingWebAudio = false;

            function initWebAudioIfNeeded() {{
                if (usingWebAudio || !supportsWebAudio) {{
                    return usingWebAudio;
                }}

                try {{
                    ctx = new AudioCtx();
                    sourceNode = ctx.createMediaElementSource(video);
                    gainNode = ctx.createGain();
                    analyserNode = ctx.createAnalyser();
                    analyserNode.fftSize = 128;

                    sourceNode.connect(gainNode);
                    gainNode.connect(analyserNode);
                    analyserNode.connect(ctx.destination);

                    const resumeCtx = function() {{
                        if (ctx && ctx.state === 'suspended') {{
                            ctx.resume().catch(() => {{}});
                        }}
                    }};

                    video.addEventListener('play', resumeCtx);
                    video.addEventListener('click', resumeCtx);

                    usingWebAudio = true;
                }} catch (err) {{
                    usingWebAudio = false;
                    ctx = null;
                    sourceNode = null;
                    gainNode = null;
                    analyserNode = null;
                }}

                return usingWebAudio;
            }}

            function applyPreviewVolume(volPercent) {{
                const safe = Math.max(0, Math.min(200, Number(volPercent) || 0));
                const normalized = safe / 100.0;

                // Always try to initialize WebAudio so it's ready for > 100% boost
                initWebAudioIfNeeded();

                if (usingWebAudio && gainNode && ctx) {{
                    if (ctx.state === 'suspended') {{
                        ctx.resume().catch(() => {{}});
                    }}
                    gainNode.gain.setTargetAtTime(normalized, ctx.currentTime, 0.02);
                    // When using WebAudio, native volume must be 1.0 — gain node handles all amplification
                    video.volume = 1.0;
                    video.muted = false;
                }} else {{
                    // Fallback: native HTML5 volume (capped at 1.0 / 100%)
                    video.volume = Math.max(0, Math.min(1, normalized));
                    video.muted = false;
                }}

                if (valueLabel) {{
                    valueLabel.textContent = Math.round(safe) + '%';
                }}
                if (sliderLabel) {{
                    sliderLabel.textContent = Math.round(safe) + '%';
                }}
            }}

            window.vcUpdateOriginalVolume = applyPreviewVolume;

            applyPreviewVolume({initial_volume_percent});

            const drawMeter = function() {{
                const canvas = document.getElementById('original_volume_preview_meter');
                if (!canvas) {{
                    if (document.body.contains(video)) {{
                        window.requestAnimationFrame(drawMeter);
                    }}
                    return;
                }}

                const c = canvas.getContext('2d');
                if (!c) {{
                    if (document.body.contains(video)) {{
                        window.requestAnimationFrame(drawMeter);
                    }}
                    return;
                }}

                c.clearRect(0, 0, canvas.width, canvas.height);
                c.fillStyle = '#0b0b0b';
                c.fillRect(0, 0, canvas.width, canvas.height);

                if (usingWebAudio && analyserNode) {{
                    const data = new Uint8Array(analyserNode.frequencyBinCount);
                    analyserNode.getByteFrequencyData(data);

                    const bars = 28;
                    const step = Math.max(1, Math.floor(data.length / bars));
                    const barW = canvas.width / bars;

                    for (let i = 0; i < bars; i++) {{
                        const raw = data[i * step] || 0;
                        const barH = (raw / 255) * canvas.height;
                        const y = canvas.height - barH;
                        c.fillStyle = raw > 175 ? '#f97316' : '#22c55e';
                        c.fillRect((i * barW) + 1, y, Math.max(1, barW - 2), barH);
                    }}
                }} else {{
                    const fillWidth = Math.max(0, Math.min(canvas.width, canvas.width * (video.volume || 0)));
                    c.fillStyle = '#22c55e';
                    c.fillRect(0, 0, fillWidth, canvas.height);
                }}

                if (document.body.contains(video)) {{
                    window.requestAnimationFrame(drawMeter);
                }}
            }};

            drawMeter();
        }})(); this.remove();" style="display:none;" />
    </div>
    """

    return html
