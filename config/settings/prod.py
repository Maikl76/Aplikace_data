from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import env

DEBUG = False

# Tajný klíč podepisuje přihlašovací cookies. S vývojovým nebo ukázkovým
# klíčem by se dalo přihlášení podvrhnout, proto se bez skutečného klíče
# server nespustí. Doplní ho instalace (deploy/pa-update.sh, offline balíček).
PLACEHOLDER_KEYS = {"", "pouze-pro-vyvoj-nikdy-v-produkci", "zmente-me-na-nahodny-retezec",
                    "VLOZTE_VYGENEROVANY_KLIC", "__SECRET__"}
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if SECRET_KEY in PLACEHOLDER_KEYS or len(SECRET_KEY) < 32:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY chybí nebo je ukázkový. Do .env doplňte náhodný řetězec, např. "
        "z příkazu: python -c \"import secrets; print(secrets.token_urlsafe(50))\"")

# Bez explicitního seznamu hostů se aplikace v produkci nespustí.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# HTTPS a cookies – reverse proxy (Caddy/nginx) ukončuje TLS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Odhlášení po nečinnosti – aplikace běží na tabletu v laboratoři.
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=8 * 60 * 60)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
