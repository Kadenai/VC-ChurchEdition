import os
import json
import cv2
import numpy as np

try:
    from media_utils import extract_file_path, persist_uploaded_file, resolve_existing_path
except ImportError:
    from webui.media_utils import extract_file_path, persist_uploaded_file, resolve_existing_path

CONFIG_FILE = "outro_config.json"

def load_outro_config():
    defaults = {
        "enabled": True,
        "outro_video_path": "WEBUI_ASSETS/outro/Instagram_Reel_1775408743_8542417d.mov",
        "overlay_image_path": None,
        "position_x": 179,
        "position_y": 886,
        "scale": 42,
        "fade_duration": 1,
        "rounded_corners": 10
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
        except Exception as e:
            print(f"Error loading outro config: {e}")

    defaults["outro_video_path"] = resolve_existing_path(defaults.get("outro_video_path"))
    defaults["overlay_image_path"] = resolve_existing_path(defaults.get("overlay_image_path"))
    return defaults

def save_outro_config(enabled, outro_video_path, overlay_image_path, position_x, position_y, scale, fade_duration, rounded_corners):
    existing_cfg = load_outro_config()

    persisted_outro = persist_uploaded_file(outro_video_path, "outro")
    if not persisted_outro:
        persisted_outro = resolve_existing_path(extract_file_path(outro_video_path))
    if not persisted_outro:
        persisted_outro = existing_cfg.get("outro_video_path")

    persisted_overlay = persist_uploaded_file(overlay_image_path, "outro")
    if not persisted_overlay:
        persisted_overlay = resolve_existing_path(extract_file_path(overlay_image_path))
    if not persisted_overlay:
        persisted_overlay = existing_cfg.get("overlay_image_path")

    config = {
        "enabled": enabled,
        "outro_video_path": persisted_outro,
        "overlay_image_path": persisted_overlay,
        "position_x": position_x,
        "position_y": position_y,
        "scale": scale,
        "fade_duration": fade_duration,
        "rounded_corners": rounded_corners
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return "Configurações de Encerramento salvas com sucesso!"
    except Exception as e:
        return f"Erro ao salvar configurações: {e}"

def generate_outro_preview(outro_video_path, image_path, x, y, scale, rounded_corners=0):
    resolved_outro_path = resolve_existing_path(extract_file_path(outro_video_path))
    resolved_image_path = resolve_existing_path(extract_file_path(image_path))

    if not resolved_outro_path or not os.path.exists(resolved_outro_path):
        # Create a black placeholder frame of 1080x1920
        frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
        cv2.putText(frame, "Nenhum video carregado", (200, 960), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 5)
    else:
        # Extract middle frame
        cap = cv2.VideoCapture(resolved_outro_path)
        if not cap.isOpened():
            frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
        else:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            # Just take a frame slightly into the video
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(30, total_frames // 2))
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
    
    if resolved_image_path and os.path.exists(resolved_image_path):
        # Overlay the image
        img = cv2.imread(resolved_image_path, cv2.IMREAD_UNCHANGED)
        if img is not None:
            target_width = int(img.shape[1] * (scale / 100.0))
            target_height = int(img.shape[0] * (scale / 100.0))
            
            if target_width > 0 and target_height > 0:
                img_resized = cv2.resize(img, (target_width, target_height), interpolation=cv2.INTER_AREA)
                
                # Check for alpha channel and ensure it exists
                if img_resized.shape[2] == 3:
                    img_resized = cv2.cvtColor(img_resized, cv2.COLOR_BGR2BGRA)
                
                if rounded_corners > 0:
                    mask = np.zeros((target_height, target_width), dtype=np.uint8)
                    radius = min(int(rounded_corners * min(target_width, target_height) / 100), min(target_width, target_height) // 2)
                    if radius > 0:
                        cv2.rectangle(mask, (radius, 0), (target_width - radius, target_height), 255, -1)
                        cv2.rectangle(mask, (0, radius), (target_width, target_height - radius), 255, -1)
                        cv2.circle(mask, (radius, radius), radius, 255, -1)
                        cv2.circle(mask, (target_width - radius, radius), radius, 255, -1)
                        cv2.circle(mask, (radius, target_height - radius), radius, 255, -1)
                        cv2.circle(mask, (target_width - radius, target_height - radius), radius, 255, -1)
                        img_resized[:, :, 3] = cv2.bitwise_and(img_resized[:, :, 3], mask)
                
                alpha = img_resized[:, :, 3] / 255.0
                colors = img_resized[:, :, :3]
                
                h, w = frame.shape[:2]
                y1, x1 = int(y), int(x)
                y2, x2 = y1 + target_height, x1 + target_width
                
                if y1 < h and x1 < w and y2 > 0 and x2 > 0:
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
                        alpha_expanded * colors[src_y1:src_y2, src_x1:src_x2] + 
                        (1 - alpha_expanded) * roi
                    ).astype(np.uint8)

    # Convert BGR to RGB for Gradio
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return frame_rgb
