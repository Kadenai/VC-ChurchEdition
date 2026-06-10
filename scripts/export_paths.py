"""Destino da exportação final ("Cortes IPB") com consciência de ambiente.

No Windows/desktop os vídeos finais vão para a Área de Trabalho, como sempre.
No Google Colab não existe Desktop visível (~/Desktop = /root/Desktop, que morre
com a VM): exportamos para dentro de VIRALS — que no Colab é um symlink para o
Google Drive — garantindo que a única cópia dos vídeos finais fique persistida.
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CORTES_IPB_NAME = "Cortes IPB"


def is_colab():
    return bool(os.environ.get("COLAB_RELEASE_TAG")) or os.path.isdir("/content")


def get_cortes_ipb_dir(base_dir=None):
    """Pasta onde os vídeos finais são copiados. Não cria a pasta."""
    root = base_dir or PROJECT_ROOT
    if is_colab():
        virals = os.path.join(root, "VIRALS")
        # Resolve o symlink para gravar direto no Drive mesmo que o link mude
        real_virals = os.path.realpath(virals) if os.path.exists(virals) else virals
        return os.path.join(real_virals, CORTES_IPB_NAME)
    return os.path.join(os.path.expanduser("~"), "Desktop", CORTES_IPB_NAME)
