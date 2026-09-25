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
# Doména je vždycky malými písmeny, uživatelské jméno ne – bez převodu
# by touch u jména s velkým písmenem vytvořil nový prázdný soubor
# a aplikace by se tiše nerestartovala.
# Účet může být na evropském (…_eu_pythonanywhere_com) i hlavním
# (…_pythonanywhere_com) serveru – zkusí se obojí.
WSGI=""
for candidate in "/var/www/${USER,,}_eu_pythonanywhere_com_wsgi.py" \
                 "/var/www/${USER,,}_pythonanywhere_com_wsgi.py"; do
    if [ -f "$candidate" ]; then WSGI="$candidate"; break; fi
done
if [ -z "$WSGI" ]; then
    echo "Nenašel jsem WSGI soubor ve /var/www – je webová aplikace založená (záložka Web)?" >&2
    exit 1
fi
touch "$WSGI"

echo "Hotovo – ukázka běží na nové verzi."
