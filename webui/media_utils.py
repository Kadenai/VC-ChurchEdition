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
    if isinstance(file_obj, dict):
        for key in ("path", "name"):
            value = file_obj.get(key)
            if value:
                return value
        data = file_obj.get("data")
        if data:
            return extract_file_path(data)
    if hasattr(file_obj, "path"):
        return file_obj.path
    if hasattr(file_obj, "name"):
        return file_obj.name
    if hasattr(file_obj, "model_dump"):
        try:
            return extract_file_path(file_obj.model_dump())
        except Exception:
            pass
    if isinstance(file_obj, list) and file_obj:
        return extract_file_path(file_obj[0])
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
    source_real = os.path.realpath(source_path)
    target_dir_real = os.path.realpath(target_dir)

    if (
        source_abs.startswith(target_dir_abs + os.sep) or source_abs == target_dir_abs or
        source_real.startswith(target_dir_real + os.sep) or source_real == target_dir_real
    ):
        return source_abs

    safe_base, ext = _sanitize_name(os.path.basename(source_abs))
    suffix = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    target_name = f"{safe_base}_{suffix}{ext}"
    target_path = os.path.join(target_dir, target_name)

    shutil.copy2(source_abs, target_path)
    return os.path.abspath(target_path)


def delete_asset_file(path):
    """Apaga um arquivo de asset SOMENTE se ele estiver dentro de WEBUI_ASSETS.

    Usado quando o usuário envia um arquivo novo (marca d'água/encerramento/áudio):
    o novo vira o padrão e o antigo é removido, evitando acúmulo. A trava de
    diretório impede apagar qualquer coisa fora de WEBUI_ASSETS por engano.
    """
    if not path:
        return False
    try:
        abs_path = os.path.abspath(path)
        assets_abs = os.path.abspath(ASSETS_ROOT)
        real_path = os.path.realpath(path)
        assets_real = os.path.realpath(ASSETS_ROOT)
        inside_assets = (
            abs_path.startswith(assets_abs + os.sep) or
            real_path.startswith(assets_real + os.sep)
        )
        if not inside_assets:
            return False
        if os.path.isfile(abs_path):
            os.remove(abs_path)
            return True
    except Exception:
        pass
    return False


def persist_replacing(file_obj, category, previous_path):
    """Persiste um upload e, se for um arquivo NOVO (diferente do anterior),
    apaga o anterior. Retorna (novo_caminho_ou_None, apagou_antigo).

    novo_caminho é None quando não houve upload (o chamador mantém o anterior).
    """
    persisted = persist_uploaded_file(file_obj, category)
    if not persisted:
        return None, False
    deleted = False
    previous_resolved = resolve_existing_path(previous_path)
    if previous_resolved and os.path.abspath(persisted) != os.path.abspath(previous_resolved):
        deleted = delete_asset_file(previous_resolved)
    return os.path.abspath(persisted), deleted


def to_project_relative(path_value):
    """Converte um caminho dentro do projeto para relativo (com '/'), p/ que os
    configs versionáveis funcionem em qualquer SO (Windows <-> Colab/Linux).
    Caminhos fora do projeto são devolvidos como estão."""
    if not path_value:
        return path_value
    try:
        abs_path = os.path.abspath(str(path_value))
        root = os.path.abspath(PROJECT_ROOT)
        if abs_path == root or abs_path.startswith(root + os.sep):
            return os.path.relpath(abs_path, root).replace("\\", "/")
    except Exception:
        pass
    return path_value


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
