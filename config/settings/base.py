"""
Společná nastavení. Dev i produkce z nich vycházejí a liší se jen v tom,
co se opravdu liší – viz dev.py a prod.py.

Zásada: žádná hodnota specifická pro prostředí nesmí být v kódu. Všechno
jde z proměnných prostředí (.env lokálně, systémové proměnné na serveru),
aby byl stejný obraz kontejneru použitelný na notebooku i na serveru.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="pouze-pro-vyvoj-nikdy-v-produkci")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --- aplikace ---------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

LOCAL_APPS = [
    "apps.core",          # organizace, uživatelé, role, audit
    "apps.subjects",      # sportovci, oddělená identita, souhlasy
    "apps.catalog",       # protokoly, metriky, normy
    "apps.measurements",  # session, pokusy, měření, raw soubory
    "apps.ingest",        # adaptéry na přístroje, staging, validace
    "apps.analytics",     # z-skóry, trendy, MDC/SWC, asymetrie
    "apps.evidence",      # knihovna vědeckých článků
    "apps.rules",         # pravidla jako data + nálezy
    "apps.reports",       # generování a předávání zpráv
    "apps.external",      # šev pro AKESO
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- databáze ---------------------------------------------------------
# Vždy PostgreSQL, i lokálně. SQLite se chová jinak v typech a neumí
# pgvector – rozdíly by se projevily až při nasazení.

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://ftvs:ftvs@db:5432/ftvs"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- lokalizace -------------------------------------------------------

LANGUAGE_CODE = "cs-cz"
TIME_ZONE = "Europe/Prague"
USE_I18N = True
USE_TZ = True

# --- statické soubory a média ----------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Raw exporty z přístrojů a vygenerovaná PDF jdou do objektového úložiště.
# Lokálně lze nechat USE_S3=False a ukládat na disk; kód je stejný.
if env.bool("USE_S3", default=False):
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default=None)
    AWS_S3_FILE_OVERWRITE = False       # raw soubory se nikdy nepřepisují
    AWS_DEFAULT_ACL = None
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

# --- fronta úloh ------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TIMEZONE = TIME_ZONE

# --- vlastní nastavení aplikace --------------------------------------

# Klíč pro šifrování jména a kontaktu v subjects.SubjectIdentity.
# Prázdná hodnota = identita se neuloží (vývoj na syntetických datech).
IDENTITY_ENCRYPTION_KEY = env("IDENTITY_ENCRYPTION_KEY", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
