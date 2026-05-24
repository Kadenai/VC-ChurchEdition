import os
import json
import cv2
import numpy as np

try:
    from media_utils import extract_file_path, persist_uploaded_file, resolve_existing_path
except ImportError:
    from webui.media_utils import extract_file_path, persist_uploaded_file, resolve_existing_path

CONFIG_FILE = "watermark_config.json"

def load_watermark_config():
    defaults = {
        "enabled": True,
        "watermark_image_path": "WEBUI_ASSETS/watermark/IP_Brotas_full_logo_white_1779639398_05bc7f69.png",
        "position_x": 480,
        "position_y": 0,
        "scale": 15,
        "opacity": 30
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
        except Exception as e:
            print(f"Error loading watermark config: {e}")

    defaults["watermark_image_path"] = resolve_existing_path(defaults.get("watermark_image_path"))
    return defaults

def save_watermark_config(enabled, watermark_image_path, position_x, position_y, scale, opacity):
    existing_cfg = load_watermark_config()
    persisted_path = persist_uploaded_file(watermark_image_path, "watermark")
    if not persisted_path:
        persisted_path = resolve_existing_path(extract_file_path(watermark_image_path))
    if not persisted_path:
        persisted_path = existing_cfg.get("watermark_image_path")

    config = {
        "enabled": enabled,
        "watermark_image_path": persisted_path,
        "position_x": position_x,
        "position_y": position_y,
        "scale": scale,
        "opacity": opacity
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return "Configurações de Marca d'água salvas com sucesso!"
    except Exception as e:
        return f"Erro ao salvar configurações: {e}"

def generate_watermark_preview(image_path, x, y, scale, opacity):
    # Create a base frame: dark gray 1080x1920 to simulate 9:16 video
    frame = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    
    # Add some text to make it look like a video preview space
    cv2.putText(frame, "PREVIEW DO", (300, 900), cv2.FONT_HERSHEY_SIMPLEX, 2, (100, 100, 100), 5)
    cv2.putText(frame, "VÍDEO AQUI", (300, 1000), cv2.FONT_HERSHEY_SIMPLEX, 2, (100, 100, 100), 5)
    
    resolved_image_path = resolve_existing_path(extract_file_path(image_path))
    if resolved_image_path and os.path.exists(resolved_image_path):
        # Overlay the watermark image
        img = cv2.imread(resolved_image_path, cv2.IMREAD_UNCHANGED)
        if img is not None:
            target_width = int(img.shape[1] * (scale / 100.0))
            target_height = int(img.shape[0] * (scale / 100.0))
            
            if target_width > 0 and target_height > 0:
                img_resized = cv2.resize(img, (target_width, target_height), interpolation=cv2.INTER_AREA)
                
                # Check for alpha channel
                if img_resized.shape[2] == 4:
                    alpha = img_resized[:, :, 3] / 255.0
                    colors = img_resized[:, :, :3]
                else:
                    alpha = np.ones((target_height, target_width))
                    colors = img_resized[:, :, :3]
                    
                # Apply the global opacity factor
                alpha = alpha * (opacity / 100.0)
                
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
