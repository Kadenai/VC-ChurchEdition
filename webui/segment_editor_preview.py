import copy
import json
import os
import re
import subprocess
import time

import cv2
import numpy as np

try:
    import outro_handler
    import segment_editor_state
    from media_utils import extract_file_path, resolve_existing_path
except ImportError:
    from webui import outro_handler, segment_editor_state
    from webui.media_utils import extract_file_path, resolve_existing_path


PREVIEW_SUBDIR = "segment_editor_preview"


def _preview_dir(project_folder):
    path = os.path.join(project_folder, "preview", PREVIEW_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def _preview_path(project_folder, segment, kind, ext="jpg"):
    safe_kind = re.sub(r"[^A-Za-z0-9_-]", "_", str(kind or "preview"))
    return os.path.join(_preview_dir(project_folder), f"{int(segment):03d}_{safe_kind}.{ext}")


def _write_image(path, frame_bgr, quality=90):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cv2.imwrite(path, frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    return path


def _placeholder(project_folder, segment, kind, message):
    out_path = _preview_path(project_folder, segment, kind)
    frame = np.full((1920, 1080, 3), 28, dtype=np.uint8)
    cv2.putText(frame, "PREVIEW", (330, 860), cv2.FONT_HERSHEY_SIMPLEX, 2, (130, 130, 130), 5)
    words = re.sub(r"[^A-Za-z0-9 .,;:/_-]", "", str(message or "Preview indisponivel")).split()
    lines = []
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if len(candidate) > 28:
            if line:
                lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    for idx, line in enumerate(lines[:5]):
        cv2.putText(frame, line, (110, 970 + idx * 54), cv2.FONT_HERSHEY_SIMPLEX, 1.15, (205, 205, 205), 3)
    return _write_image(out_path, frame)


def _video_duration(video_path):
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return None
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        total = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps > 0 and total > 0:
            return total / fps
    finally:
        cap.release()
    return None


def extract_frame(project_folder, segment, video_path, kind="base", timestamp=None):
    out_path = _preview_path(project_folder, segment, f"{kind}_frame")
    if not video_path or not os.path.exists(video_path):
        return None
    try:
        if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(video_path):
            return out_path
    except OSError:
        pass

    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return None
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if timestamp is not None and fps > 0:
            frame_index = max(0, int(float(timestamp) * fps))
            if total > 0:
                frame_index = min(frame_index, max(0, total - 1))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        elif total > 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total // 2))

        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            return None
        return _write_image(out_path, frame)
    finally:
        cap.release()


def _overlay_image(frame, image_path, x, y, scale, opacity=100, rounded_corners=0):
    resolved_image_path = resolve_existing_path(extract_file_path(image_path))
    if not resolved_image_path or not os.path.exists(resolved_image_path):
        return frame

    img = cv2.imread(resolved_image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return frame

    try:
        scale_value = float(scale) / 100.0
    except (TypeError, ValueError):
        scale_value = 1.0
    target_width = int(img.shape[1] * scale_value)
    target_height = int(img.shape[0] * scale_value)
    if target_width <= 0 or target_height <= 0:
        return frame

    img_resized = cv2.resize(img, (target_width, target_height), interpolation=cv2.INTER_AREA)
    if img_resized.shape[2] == 3:
        img_resized = cv2.cvtColor(img_resized, cv2.COLOR_BGR2BGRA)

    if rounded_corners:
        radius = min(
            int(float(rounded_corners) * min(target_width, target_height) / 100.0),
            min(target_width, target_height) // 2,
        )
        if radius > 0:
            mask = np.zeros((target_height, target_width), dtype=np.uint8)
            cv2.rectangle(mask, (radius, 0), (target_width - radius, target_height), 255, -1)
            cv2.rectangle(mask, (0, radius), (target_width, target_height - radius), 255, -1)
            cv2.circle(mask, (radius, radius), radius, 255, -1)
            cv2.circle(mask, (target_width - radius, radius), radius, 255, -1)
            cv2.circle(mask, (radius, target_height - radius), radius, 255, -1)
            cv2.circle(mask, (target_width - radius, target_height - radius), radius, 255, -1)
            img_resized[:, :, 3] = cv2.bitwise_and(img_resized[:, :, 3], mask)

    alpha = img_resized[:, :, 3] / 255.0
    try:
        alpha = alpha * (float(opacity) / 100.0)
    except (TypeError, ValueError):
        pass
    colors = img_resized[:, :, :3]

    h, w = frame.shape[:2]
    y1, x1 = int(float(y)), int(float(x))
    y2, x2 = y1 + target_height, x1 + target_width
    if y1 >= h or x1 >= w or y2 <= 0 or x2 <= 0:
        return frame

    src_y1 = max(0, -y1)
    src_x1 = max(0, -x1)
    src_y2 = min(target_height, h - y1)
    src_x2 = min(target_width, w - x1)
    dst_y1 = max(0, y1)
    dst_x1 = max(0, x1)
    dst_y2 = min(h, y2)
    dst_x2 = min(w, x2)

    alpha_slice = alpha[src_y1:src_y2, src_x1:src_x2]
    alpha_expanded = np.expand_dims(alpha_slice, axis=2)
    roi = frame[dst_y1:dst_y2, dst_x1:dst_x2]
    frame[dst_y1:dst_y2, dst_x1:dst_x2] = (
        alpha_expanded * colors[src_y1:src_y2, src_x1:src_x2] + (1 - alpha_expanded) * roi
    ).astype(np.uint8)
    return frame


def _choose_subtitle_time(json_path):
    if not json_path or not os.path.exists(json_path):
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    segments = data.get("segments", []) if isinstance(data, dict) else []
    timed = []
    for seg in segments:
        try:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start))
        except (TypeError, ValueError):
            continue
        if end > start:
            timed.append((start, end))
    if not timed:
        return None
    max_end = max(end for _, end in timed)
    target = max_end / 2.0
    chosen_start, chosen_end = min(timed, key=lambda item: 0 if item[0] <= target <= item[1] else min(abs(item[0] - target), abs(item[1] - target)))
    return max(chosen_start, min((chosen_start + chosen_end) / 2.0, chosen_end - 0.02))


def _safe_ass_filter_path(path):
    return os.path.abspath(path).replace("\\", "/").replace(":", "\\:")


def render_subtitle_preview(project_folder, segment, video_path, json_path, configs):
    if not json_path or not os.path.exists(json_path):
        return _placeholder(project_folder, segment, "subtitle", "JSON de legenda nao encontrado")
    if not video_path or not os.path.exists(video_path):
        return _placeholder(project_folder, segment, "subtitle", "Video base nao encontrado")

    preview_time = _choose_subtitle_time(json_path)
    if preview_time is None:
        duration = _video_duration(video_path) or 2.0
        preview_time = max(0.0, duration / 2.0)

    frame_path = extract_frame(project_folder, segment, video_path, "subtitle", preview_time)
    if not frame_path:
        return _placeholder(project_folder, segment, "subtitle", "Falha ao extrair frame")

    from scripts import adjust_subtitles as adjust

    out_path = _preview_path(project_folder, segment, "subtitle")
    ass_path = _preview_path(project_folder, segment, "subtitle", "ass")
    cfg = copy.deepcopy((configs or {}).get("subtitle") or {})
    cfg = segment_editor_state.normalize_configs(project_folder, {"subtitle": cfg}).get("subtitle", {})

    face_modes = {}
    modes_file = os.path.join(project_folder, "face_modes.json")
    if os.path.exists(modes_file):
        try:
            with open(modes_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                face_modes = loaded
        except Exception:
            face_modes = {}

    adjust.generate_ass_from_file(json_path, ass_path, project_folder, **cfg, face_modes=face_modes)
    safe_ass = _safe_ass_filter_path(ass_path)
    vf = f"setpts=PTS+{preview_time:.3f}/TB,ass='{safe_ass}'"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", frame_path,
        "-vf", vf,
        "-frames:v", "1",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(out_path):
        msg = (result.stderr or result.stdout or "Falha no ffmpeg").strip()[:500]
        print(f"[segment_editor_preview] subtitle preview failed: {msg}")
        return _placeholder(project_folder, segment, "subtitle", "Falha ao gerar preview da legenda")
    return out_path


def render_watermark_preview(project_folder, segment, video_path, configs):
    if not video_path or not os.path.exists(video_path):
        return _placeholder(project_folder, segment, "watermark", "Video base nao encontrado")
    frame_path = extract_frame(project_folder, segment, video_path, "watermark")
    if not frame_path:
        return _placeholder(project_folder, segment, "watermark", "Falha ao extrair frame")
    frame = cv2.imread(frame_path, cv2.IMREAD_COLOR)
    if frame is None:
        return _placeholder(project_folder, segment, "watermark", "Falha ao abrir frame")

    cfg = segment_editor_state.normalize_configs(project_folder, configs).get("watermark", {})
    if cfg.get("enabled", False):
        frame = _overlay_image(
            frame,
            cfg.get("watermark_image_path"),
            cfg.get("position_x", 480),
            cfg.get("position_y", 0),
            cfg.get("scale", 15),
            cfg.get("opacity", 30),
        )
    return _write_image(_preview_path(project_folder, segment, "watermark"), frame)


def render_outro_preview(project_folder, segment, configs):
    cfg = segment_editor_state.normalize_configs(project_folder, configs).get("outro", {})
    try:
        frame_rgb = outro_handler.generate_outro_preview(
            cfg.get("outro_video_path"),
            cfg.get("overlay_image_path"),
            cfg.get("position_x", 179),
            cfg.get("position_y", 886),
            cfg.get("scale", 42),
            cfg.get("rounded_corners", 0),
        )
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        return _write_image(_preview_path(project_folder, segment, "outro"), frame_bgr)
    except Exception as e:
        print(f"[segment_editor_preview] outro preview failed: {e}")
        return _placeholder(project_folder, segment, "outro", "Falha ao gerar preview do outro")


def render_preview(project_folder, segment, kind, configs, video_path=None, json_path=None):
    kind = kind if kind in {"subtitle", "watermark", "outro"} else "subtitle"
    normalized = segment_editor_state.normalize_configs(project_folder, configs)
    if kind == "subtitle":
        return render_subtitle_preview(project_folder, segment, video_path, json_path, normalized)
    if kind == "watermark":
        return render_watermark_preview(project_folder, segment, video_path, normalized)
    return render_outro_preview(project_folder, segment, normalized)
