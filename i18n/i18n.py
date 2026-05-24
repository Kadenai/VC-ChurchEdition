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


class I18nAuto:
    def __init__(self, language=None):
        if language in ["Auto", None]:
            system_locale = locale.getdefaultlocale()[0]
            language = system_locale or "en_US"

        locale_path = os.path.join(LOCALE_DIR, f"{language}.json")
        if not os.path.exists(locale_path):
            language = "en_US"

        self.language = language
        self.language_map = load_language_list(language)

    def __call__(self, key):
        return self.language_map.get(key, key)

    def __repr__(self):
        return "Use Language: " + self.language
