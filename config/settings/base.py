"""
Společná nastavení. Dev i produkce z nich vycházejí a liší se jen v tom,
co se opravdu liší – viz dev.py a prod.py.

Zásada: žádná hodnota specifická pro prostředí nesmí být v kódu. Všechno
jde z proměnných prostředí (.env lokálně, systémové proměnné na serveru),
aby byl stejný obraz kontejneru použitelný na notebooku i na serveru.
"""

import os
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
    "apps.booking",       # objednávky testování od klientů
    "apps.portal",        # portál sportovce a trenéra
    "apps.genetics",      # genové karty, panel variant, souhlas a genotypy
]

THIRD_PARTY_APPS = [
    "axes",               # zámek účtu po opakovaně špatném heslu
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RoleAccessMiddleware",   # trenér/sportovec zatím ne, výzkumník jen čte
    "axes.middleware.AxesMiddleware",
]

# --- přihlášení -------------------------------------------------------
# Ochrana proti hádání hesla: po několika špatných pokusech se dvojice
# (účet, adresa) na čtvrt hodiny zamkne. Ukázka je veřejná a účet se
# jmenuje „admin“ – bez zámku by šlo heslo zkoušet donekonečna.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = env.int("AXES_COOLOFF_MINUTES", default=15) / 60   # hodiny
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/uzamceno.html"

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
                "apps.core.context_processors.demo_mode",
                "apps.core.context_processors.read_only",
                "apps.core.context_processors.booking_counts",
                "apps.core.context_processors.remark_counts",
                "apps.core.context_processors.access_flags",
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

# SQLite (laboratorní počítač, notebook, ukázka): souhrn zprávy píše model
# ve vlákně, zatímco se dál pracuje. Timeout nechá druhého zapisujícího
# počkat, IMMEDIATE zamkne hned na začátku transakce místo až při prvním
# zápisu – bez toho by občas skončil na „database is locked“.
#
# Režim WAL (čtení souběžně se zápisem) jen na MÍSTNÍM disku. Přes síťový
# disk (PythonAnywhere má NFS) WAL nefunguje a může ztratit data – tam
# zůstává klasický deník. Výchozí: zapnuto na Windows (laboratorní PC,
# notebook), jinde vypnuto; přepíše SQLITE_WAL v .env. Režim nastavuje
# při každém připojení apps/core/sqlite.py (umí i převést zpět).
SQLITE_WAL = env.bool("SQLITE_WAL", default=os.name == "nt")
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {}).update({
        "timeout": 20,
        "transaction_mode": "IMMEDIATE",
    })

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

# Nahrané soubory (exporty z přístrojů, PDF zpráv, dokumenty souhlasů) jsou
# na disku ve složce media – zálohuje ji zalohovat.bat / deploy/backup.sh.
# Objektové úložiště (S3/MinIO) ani fronta úloh (Celery/Redis) se nepoužívají:
# model píše souhrn ve vlákně aplikace. Přibudou, až bude potřeba.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- vlastní nastavení aplikace --------------------------------------

# Demo režim: veřejně dostupná ukázka pro kolegy. Zobrazí varovný pruh
# a odmítne nahrávání souborů – aby se do ukázky omylem nedostala reálná
# data sportovců. Do ostrého provozu patří False.
DEMO_MODE = env.bool("DEMO_MODE", default=False)

# Jazykový model pro text zprávy. Vypnutý = text se skládá ze šablon.
# Rozhraní je kompatibilní s OpenAI, takže funguje s Ollamou, LM Studiem
# i serverovými nástroji (vLLM, llama.cpp). Model běží lokálně – data
# neopouštějí počítač ani server, na kterém aplikace běží.
LLM_ENABLED = env.bool("LLM_ENABLED", default=False)
LLM_BASE_URL = env("LLM_BASE_URL", default="http://localhost:11434/v1")
# Častá záměna při ruční úpravě .env: celý řádek vložený za rovnítko
# („LLM_MODEL=LLM_MODEL=…“) nebo název v uvozovkách. Model se pak nenajde.
LLM_MODEL = (env("LLM_MODEL", default="gemma3:4b").strip().strip("\"'")
             .removeprefix("LLM_MODEL=").strip())
LLM_API_KEY = env("LLM_API_KEY", default="").strip()  # jen cloudový model ve zkušebním provozu
LLM_TIMEOUT = env.int("LLM_TIMEOUT", default=300)
# Souhrn zprávy píše model na pozadí – stránka nečeká a velký model smí
# psát déle, než by vydržel webový požadavek.
LLM_BACKGROUND = env.bool("LLM_BACKGROUND", default=True)
LLM_TEMPERATURE = env.float("LLM_TEMPERATURE", default=0.2)

# E-maily (potvrzení objednávky, schválení). Bez EMAIL_HOST se nic
# neodesílá, zprávy se jen vypíšou do logu – objednávky fungují i tak.
EMAIL_HOST = env("EMAIL_HOST", default="")
# Veřejná adresa aplikace do e-mailů posílaných mimo prohlížeč (připomínky
# dalšího měření z příkazu), např. https://ftvs.pythonanywhere.com
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="").rstrip("/")

# Sledovaná složka s exporty z přístroje: hlídač (hlidat_slozku, spouští ho
# spustit.bat) nový export sám založí do importu a jednoznačný uloží.
IMPORT_WATCH_DIR = env("IMPORT_WATCH_DIR", default="").strip().strip("\"'")
IMPORT_WATCH_INTERVAL = env.int("IMPORT_WATCH_INTERVAL", default=30)

# Denní údržba (apps/core/maintenance.py, příkaz udrzba): záloha SQLite do
# BACKUP_DIR/denni (výchozí ~/Zalohy-FTVS), úklid starých importů, připomínky
# měření a jednou týdně e-mail správci se stavem pracoviště. Bez běžícího
# příkazu ji jako pojistku spustí první otevření Přehledu v daný den.
BACKUP_DIR = env("BACKUP_DIR", default="").strip().strip("\"'")
BACKUP_KEEP_DAILY = env.int("BACKUP_KEEP_DAILY", default=7)
STATUS_MAIL_WEEKDAY = env.int("STATUS_MAIL_WEEKDAY", default=0)   # 0 = pondělí … 6 = neděle
MAINTENANCE_IN_WEB = env.bool("MAINTENANCE_IN_WEB", default=True)
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_BACKEND = env("EMAIL_BACKEND", default=(
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Laboratoř FTVS <noreply@localhost>")

# Objednávky: pro kterou organizaci je veřejný formulář (zkratka) a zda
# se musí potvrdit e-mail, než žádost uvidí laboratoř (chrání před
# podvrženými objednávkami; zapněte, až budou e-maily nastavené).
BOOKING_ORGANIZATION = env("BOOKING_ORGANIZATION", default="")
BOOKING_VERIFY_EMAIL = env.bool("BOOKING_VERIFY_EMAIL", default=False)

# Klíč pro šifrování jména a kontaktu v subjects.SubjectIdentity.
# Prázdná hodnota = identita se neuloží (vývoj na syntetických datech).
IDENTITY_ENCRYPTION_KEY = env("IDENTITY_ENCRYPTION_KEY", default="")
# Genotypy mají vlastní klíč: kdo získá klíč k identitě, nepřečte genetiku a naopak.
GENETICS_ENCRYPTION_KEY = env("GENETICS_ENCRYPTION_KEY", default="")

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
