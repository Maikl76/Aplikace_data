#!/usr/bin/env bash
# Aktualizace ukázky na PythonAnywhere po změnách v repozitáři.
#
#     bash ~/Aplikace_data/deploy/pa-update.sh
#
# Stáhne novou verzi, doinstaluje knihovny, upraví databázi, doplní do
# katalogu nové testy a restartuje webovou aplikaci. Data v ukázce zůstanou.
#
#     bash ~/Aplikace_data/deploy/pa-update.sh --nova-data
#
# Totéž, ale ukázková data se smažou a vygenerují znovu – hodí se, když
# nová verze přinesla věci, které stará vygenerovaná data nemají
# (baterie testů, Wingate, RPE…). Funguje jen v ukázkovém režimu.

# Celé je to ve funkci: bash čte skript průběžně a git pull ho může
# uprostřed běhu přepsat. Funkci načte celou předem, takže se to nerozbije.
main() {
    set -euo pipefail

    local VENV="$HOME/.virtualenvs/ftvs"
    local APP="$HOME/Aplikace_data"
    local PY="$VENV/bin/python"
    export DJANGO_SETTINGS_MODULE=config.settings.prod

    cd "$APP"
    echo "Stahuji novou verzi..."
    git pull --ff-only

    echo "Doinstalovávám knihovny..."
    "$VENV/bin/pip" install --no-cache-dir --quiet -r requirements/demo.txt

    if [ "${1:-}" = "--nova-data" ]; then
        if ! grep -qiE '^DEMO_MODE=(true|1|yes)' .env; then
            echo "Nová data jdou vygenerovat jen v ukázce (DEMO_MODE=True v .env)." >&2
            exit 1
        fi
        local DB
        DB="$(grep -E '^DATABASE_URL=sqlite:///' .env | sed 's|^DATABASE_URL=sqlite:///||')"
        if [ -z "$DB" ]; then
            echo "V .env jsem nenašel databázi SQLite (DATABASE_URL=sqlite:///...)." >&2
            exit 1
        fi
        echo "Mažu stará ukázková data ($DB)..."
        rm -f "$DB"
        "$PY" manage.py migrate --noinput --verbosity 0
        "$PY" manage.py bootstrap_demo
    else
        "$PY" manage.py migrate --noinput
        # Nové metriky, protokoly a dotazníky; úpravy z administrace zůstanou.
        "$PY" manage.py seed_catalog --jen-chybejici
        "$PY" manage.py prepocitat_odvozene
    fi

    "$PY" manage.py collectstatic --noinput --verbosity 0

    # Změna času u WSGI souboru = restart webové aplikace na PythonAnywhere.
    # Doména je vždycky malými písmeny, uživatelské jméno ne – bez převodu
    # by touch u jména s velkým písmenem vytvořil nový prázdný soubor
    # a aplikace by se tiše nerestartovala.
    # Účet může být na evropském (…_eu_pythonanywhere_com) i hlavním
    # (…_pythonanywhere_com) serveru – zkusí se obojí.
    local WSGI="" candidate ME
    ME="${USER:-$(whoami)}"
    for candidate in "/var/www/${ME,,}_eu_pythonanywhere_com_wsgi.py" \
                     "/var/www/${ME,,}_pythonanywhere_com_wsgi.py"; do
        if [ -f "$candidate" ]; then WSGI="$candidate"; break; fi
    done
    if [ -z "$WSGI" ]; then
        echo "Nenašel jsem WSGI soubor ve /var/www – je webová aplikace založená (záložka Web)?" >&2
        exit 1
    fi
    touch "$WSGI"

    echo "Hotovo – ukázka běží na nové verzi. V prohlížeči stiskněte Ctrl+F5."
}

main "$@"
exit
