from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# V dev režimu se e-maily jen vypisují do konzole.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
