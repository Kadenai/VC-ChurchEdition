"""Resolução de caminhos de assets (logo, outro, áudio) de forma portátil.

Os configs (watermark_config.json etc.) podem conter caminhos absolutos salvos
em OUTRO sistema operacional (ex.: "C:\\Users\\...\\WEBUI_ASSETS\\x.png" gravado
no Windows e lido no Colab/Linux). Este módulo espelha a lógica de
webui/media_utils.resolve_existing_path para que os scripts do pipeline
(apply_watermark, append_outro, apply_audio) encontrem o arquivo local
equivalente em vez de pular o efeito silenciosamente.
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_ROOT = os.path.join(PROJECT_ROOT, "WEBUI_ASSETS")


def resolve_asset_path(path_value):
    """Devolve um caminho absoluto existente para o asset, ou None."""
    if not path_value:
        return None

    candidate = str(path_value)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)

    # Caminho relativo à raiz do projeto (formato preferido dos configs)
    normalized = candidate.replace("\\", "/")
    relative_candidate = os.path.join(PROJECT_ROOT, *[p for p in normalized.split("/") if p])
    if os.path.exists(relative_candidate):
        return os.path.abspath(relative_candidate)

    # Fallback cross-platform: procura pelo nome do arquivo dentro de WEBUI_ASSETS
    try:
        filename = os.path.basename(normalized)
        if filename:
            for sub in ("audio", "watermark", "outro"):
                guess = os.path.join(ASSETS_ROOT, sub, filename)
                if os.path.exists(guess):
                    return os.path.abspath(guess)
            if os.path.isdir(ASSETS_ROOT):
                for root, _, files in os.walk(ASSETS_ROOT):
                    if filename in files:
                        return os.path.abspath(os.path.join(root, filename))
    except Exception:
        pass

    return None
