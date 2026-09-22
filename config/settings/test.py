"""
Nastavení pro testy.

Testy běží s DEBUG=False. Produkční úložiště statických souborů se opírá
o manifest, který vzniká až při ``collectstatic`` – bez něj by každá
vykreslená stránka spadla na chybějící záznam. V testech jde o obsah
stránky, ne o otisky souborů, takže se použije prosté úložiště.

Soubory nahrané v testech jdou do paměti, ať po sobě testy nenechávají
nic na disku.
"""

from .dev import *  # noqa: F403

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Hashování hesel je v testech zbytečně pomalé.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
