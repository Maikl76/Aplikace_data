"""
Šifrování oddělené identity.

Jméno a kontakt sportovce se ukládají šifrovaně, klíč žije v konfiguraci
aplikace, ne v databázi. Šifrovaný sloupec nejde prohledávat, proto se
vedle ukládá hash pro přesné vyhledání ("najdi Nováka").
"""

import hashlib

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet():
    from cryptography.fernet import Fernet

    key = settings.IDENTITY_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured(
            "IDENTITY_ENCRYPTION_KEY není nastaven. Pro vývoj na syntetických "
            "datech identitu neukládejte; pro provoz klíč vygenerujte: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()


def search_hash(value: str) -> str:
    """
    Deterministický hash pro přesné vyhledání. Solí se tajným klíčem, aby
    ho nešlo zpětně dohledat slovníkovým útokem na běžná příjmení.
    """
    if not value:
        return ""
    salt = (settings.IDENTITY_ENCRYPTION_KEY or "").encode()
    return hashlib.sha256(salt + value.strip().lower().encode()).hexdigest()
