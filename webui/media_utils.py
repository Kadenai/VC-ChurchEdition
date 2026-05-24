import os
import re
import shutil
import time
import urllib.parse
import uuid

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_ROOT = os.path.join(PROJECT_ROOT, "WEBUI_ASSETS")


def extract_file_path(file_obj):
    if file_obj is None:
        return None
    if isinstance(file_obj, str):
        return file_obj
    if hasattr(file_obj, "name"):
        return file_obj.name
    if isinstance(file_obj, list) and file_obj:
        first = file_obj[0]
        if hasattr(first, "name"):
            return first.name
        return str(first)
    return str(file_obj)


def resolve_existing_path(path_value):
    if not path_value:
        return None

    candidate = str(path_value)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)

    relative_candidate = os.path.join(PROJECT_ROOT, candidate)
    if os.path.exists(relative_candidate):
        return os.path.abspath(relative_candidate)

    # Cross-platform fallback: when running on Linux/Colab but the config
    # holds a Windows-style path (e.g. "C:\\Users\\...\\WEBUI_ASSETS\\audio\\foo.mp3"),
    # try to locate the same file inside the local WEBUI_ASSETS tree by name.
    # This lets users zip a Windows project and run it on Colab without
    # losing references to uploaded watermarks/audio/outro assets.
    try:
        # Normalize separators so we can pick the basename regardless of OS.
        normalized = candidate.replace("\\", "/")
        filename = os.path.basename(normalized)
        if filename:
            # Look for the file inside the asset categories the WebUI uses.
            for sub in ("audio", "watermark", "outro"):
                guess = os.path.join(ASSETS_ROOT, sub, filename)
                if os.path.exists(guess):
                    return os.path.abspath(guess)
            # Last resort: walk ASSETS_ROOT for a matching filename.
            if os.path.isdir(ASSETS_ROOT):
                for root, _, files in os.walk(ASSETS_ROOT):
                    if filename in files:
                        return os.path.abspath(os.path.join(root, filename))
    except Exception:
        pass

    return None


def _sanitize_name(filename):
    base, ext = os.path.splitext(filename)
    safe_base = re.sub(r"[^A-Za-z0-9_-]", "_", base).strip("_")
    if not safe_base:
        safe_base = "uploaded"
    return safe_base, ext.lower()


def persist_uploaded_file(file_obj, category):
    source_path = extract_file_path(file_obj)
    source_path = resolve_existing_path(source_path)
    if not source_path:
        return None

    target_dir = os.path.join(ASSETS_ROOT, category)
    os.makedirs(target_dir, exist_ok=True)

    source_abs = os.path.abspath(source_path)
    target_dir_abs = os.path.abspath(target_dir)

    if source_abs.startswith(target_dir_abs + os.sep) or source_abs == target_dir_abs:
        return source_abs

    safe_base, ext = _sanitize_name(os.path.basename(source_abs))
    suffix = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    target_name = f"{safe_base}_{suffix}{ext}"
    target_path = os.path.join(target_dir, target_name)

    shutil.copy2(source_abs, target_path)
    return os.path.abspath(target_path)


def as_posix_abs(path_value):
    return os.path.abspath(path_value).replace("\\", "/")


def build_file_url_candidates(path_value):
    abs_posix = as_posix_abs(path_value)
    encoded_query = urllib.parse.quote(abs_posix, safe="")
    encoded_path = urllib.parse.quote(abs_posix, safe="/:")

    candidates = [
        f"/gradio_api/file={encoded_query}",
        f"/file={encoded_query}",
        f"/file/{encoded_path}",
    ]

    unique = []
    seen = set()
    for item in candidates:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def build_file_url(path_value):
    candidates = build_file_url_candidates(path_value)
    return candidates[0]
