from .base import *  # noqa: F403
from .base import STORAGES, env

# Ladicí režim ukazuje při chybě nastavení i data z požadavku. Na jednom
# počítači to nevadí; při zpřístupnění do sítě laboratoře (spustit.bat sit)
# se vypíná proměnnou DJANGO_DEBUG=False.
DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = ["*"]

if not DEBUG:
    # Bez ladicího režimu statické soubory podává WhiteNoise rovnou ze
    # zdrojových složek – bez manifestu, který vzniká až při collectstatic.
    STORAGES["staticfiles"] = {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}
    WHITENOISE_USE_FINDERS = True

# V dev režimu se e-maily jen vypisují do konzole.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
