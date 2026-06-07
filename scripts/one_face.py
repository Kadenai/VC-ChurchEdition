import cv2
import numpy as np


def resize_with_padding(frame):
        frame_height, frame_width = frame.shape[:2]
        target_aspect_ratio = 9 / 16

        if frame_width / frame_height > target_aspect_ratio:
            new_width = frame_width
            new_height = int(frame_width / target_aspect_ratio)
        else:
            new_height = frame_height
            new_width = int(frame_height * target_aspect_ratio)

        # Criação de uma tela preta
        result = np.zeros((new_height, new_width, 3), dtype=np.uint8)

        # Cálculo das margens
        pad_top = (new_height - frame_height) // 2
        pad_left = (new_width - frame_width) // 2

        # Colocar o frame original na tela
        result[pad_top:pad_top+frame_height, pad_left:pad_left+frame_width] = frame

        # Redimensionar para as dimensões finais
        return cv2.resize(result, (1080, 1920), interpolation=cv2.INTER_AREA)


def crop_center_zoom(frame):
    """
    Crops the center of the frame to fill 9:16 aspect ratio (Zoom effect).
    """
    frame_height, frame_width = frame.shape[:2]
    target_aspect_ratio = 9 / 16

    # Calculate crop dimensions to FILL the target ratio
    if frame_width / frame_height > target_aspect_ratio:
        # Source is wider than target (e.g. 16:9 source, 9:16 target) -> Crop Width
        new_width = int(frame_height * target_aspect_ratio)
        new_height = frame_height
    else:
        # Source is taller than target -> Crop Height
        new_width = frame_width
        new_height = int(frame_width / target_aspect_ratio)

    start_x = (frame_width - new_width) // 2
    start_y = (frame_height - new_height) // 2

    # Ensure bounds
    start_x = max(0, start_x)
    start_y = max(0, start_y)

    crop_img = frame[start_y:start_y+new_height, start_x:start_x+new_width]

    # Resize to final 1080x1920
    return cv2.resize(crop_img, (1080, 1920), interpolation=cv2.INTER_AREA)
