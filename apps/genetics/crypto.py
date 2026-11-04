"""
Šifrování genotypů.

Genotyp je genetický údaj (zvláštní kategorie podle čl. 9 GDPR). Leží
v databázi šifrovaně a klíč je jiný než klíč k identitě: kdo se dostane
k jednomu klíči, nepřečte obojí. Klíč žije v .env (``GENETICS_ENCRYPTION_KEY``),
doplní ho ``zajisti_klic``; bez něj aplikace genotypy neukládá ani nečte.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

CHYBI = ("GENETICS_ENCRYPTION_KEY není nastaven. Doplní ho „python manage.py zajisti_klic“ "
         "(spustit.bat ho volá sám). Klíč zálohujte spolu s databází – bez něj uložené "
         "genotypy nejdou přečíst.")


def configured() -> bool:
    return bool(getattr(settings, "GENETICS_ENCRYPTION_KEY", ""))


def _fernet():
    from cryptography.fernet import Fernet

    key = getattr(settings, "GENETICS_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured(CHYBI)
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()
