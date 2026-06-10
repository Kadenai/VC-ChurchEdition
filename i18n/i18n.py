import json
import locale
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCALE_DIR = os.path.join(BASE_DIR, "locale")


def load_language_list(language):
    locale_path = os.path.join(LOCALE_DIR, f"{language}.json")
    with open(locale_path, "r", encoding="utf-8") as f:
        language_list = json.load(f)
    return language_list


def _detect_system_language():
    """Detecta o idioma do sistema sem usar locale.getdefaultlocale()
    (deprecado no Python 3.12 e marcado para remoção)."""
    try:
        lang = locale.getlocale()[0]
        # No Windows pode vir como "Portuguese_Brazil" — só aceita o formato xx_YY
        if lang and len(lang) >= 2 and "_" in lang and len(lang.split("_")[0]) == 2:
            return lang
    except (ValueError, TypeError):
        pass
    env_lang = os.environ.get("LANG") or os.environ.get("LC_ALL") or ""
    if env_lang:
        return env_lang.split(".")[0]
    return "en_US"


class I18nAuto:
    def __init__(self, language=None):
        if language in ["Auto", None]:
            language = _detect_system_language()

        locale_path = os.path.join(LOCALE_DIR, f"{language}.json")
        if not os.path.exists(locale_path):
            language = "en_US"

        self.language = language
        self.language_map = load_language_list(language)

    def __call__(self, key):
        return self.language_map.get(key, key)

    def __repr__(self):
        return "Use Language: " + self.language
