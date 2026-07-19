"""Detecção de ambiente e nome da pasta legada "Cortes IPB".

A exportação automática para "Cortes IPB" não existe mais (o download é feito
pela galeria do WebUI). O nome continua aqui só para que pastas antigas com
vídeos do usuário sigam protegidas da limpeza.
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CORTES_IPB_NAME = "Cortes IPB"


def is_colab():
    return bool(os.environ.get("COLAB_RELEASE_TAG")) or os.path.isdir("/content")
