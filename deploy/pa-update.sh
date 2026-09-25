#!/usr/bin/env bash
# Aktualizace ukázky na PythonAnywhere po změnách v repozitáři.
#
#     bash ~/Aplikace_data/deploy/pa-update.sh
#
# Stáhne novou verzi, doinstaluje knihovny, provede migrace a restartuje
# webovou aplikaci. Data v ukázce zůstanou.

set -euo pipefail

VENV="$HOME/.virtualenvs/ftvs"
APP="$HOME/Aplikace_data"
export DJANGO_SETTINGS_MODULE=config.settings.prod

cd "$APP"
git pull --ff-only
"$VENV/bin/pip" install --no-cache-dir --quiet -r requirements/demo.txt
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput --verbosity 0

# Změna času u WSGI souboru = restart webové aplikace na PythonAnywhere.
touch "/var/www/${USER}_eu_pythonanywhere_com_wsgi.py"

echo "Hotovo – ukázka běží na nové verzi."
