#!/usr/bin/env bash
# Aktualizace ukázky na PythonAnywhere po změnách v repozitáři.
#
#     cd ~/Aplikace_data && git pull && bash deploy/pa-update.sh
#
# Stáhne novou verzi, ZAZÁLOHUJE databázi a nahrané soubory (~/Zalohy-FTVS,
# posledních 10 záloh), upraví databázi, doplní do katalogu nové testy
# a do ukázky chybějící ukázkové účty a restartuje webovou aplikaci.
# Data v ukázce – účty, zprávy, cokoli jste tu zadali – zůstanou.
#
#     bash deploy/pa-update.sh --nova-data
#
# POZOR: smaže VŠECHNA data ukázky (účty, zprávy, sportovce, články,
# objednávky…) a vygeneruje nová ukázková. Zeptá se a chce opsat SMAZAT.
# Předtím se udělá záloha, takže to jde vrátit.
#
#     bash deploy/pa-update.sh --obnovit [složka zálohy]
#
# Vrátí ukázku do stavu ze zálohy – bez složky z poslední zálohy před
# aktualizací. Chce opsat OBNOVIT; současný stav se předtím zazálohuje.

# Celé je to ve funkci: bash čte skript průběžně a git pull ho může
# uprostřed běhu přepsat. Funkci načte celou předem, takže se to nerozbije.
main() {
    set -euo pipefail

    local VENV="$HOME/.virtualenvs/ftvs"
    local APP="$HOME/Aplikace_data"
    local PY="$VENV/bin/python"
    local BACKUPS="$HOME/Zalohy-FTVS"
    local MODE="${1:-}"
    export DJANGO_SETTINGS_MODULE=config.settings.prod

    case "$MODE" in
        ""|--nova-data|--obnovit) ;;
        *) echo "Neznámý přepínač „$MODE“. Povolené: --nova-data, --obnovit." >&2; exit 1 ;;
    esac

    cd "$APP"
    local DB
    DB="$(grep -E '^DATABASE_URL=sqlite:///' .env | tr -d '\r' | sed 's|^DATABASE_URL=sqlite:///||' || true)"

    # --- potvrzení předem: mazání a obnova jsou vědomý krok -------------------
    local ANSWER RESTORE_FROM=""
    if [ "$MODE" = "--nova-data" ]; then
        if ! grep -qiE '^DEMO_MODE=(true|1|yes)' .env; then
            echo "Nová data jdou vygenerovat jen v ukázce (DEMO_MODE=True v .env)." >&2
            exit 1
        fi
        if [ -z "$DB" ]; then
            echo "V .env jsem nenašel databázi SQLite (DATABASE_URL=sqlite:///...)." >&2
            exit 1
        fi
        echo
        echo "POZOR: --nova-data SMAŽE VŠECHNA data ukázky – účty, zprávy, sportovce,"
        echo "měření, články, objednávky, všechno, co jste tu zadali – a vygeneruje nová."
        echo "Pro běžnou aktualizaci spusťte skript BEZ --nova-data; data zůstanou."
        echo "Před smazáním se udělá záloha do $BACKUPS (vrátit: --obnovit)."
        read -r -p "Opravdu smazat? Napište SMAZAT: " ANSWER
        if [ "$ANSWER" != "SMAZAT" ]; then
            echo "Nic se nesmazalo."
            exit 1
        fi
    elif [ "$MODE" = "--obnovit" ]; then
        RESTORE_FROM="${2:-}"
        if [ -z "$RESTORE_FROM" ]; then
            RESTORE_FROM="$(ls -1d "$BACKUPS"/ftvs-zaloha-*-pred-aktualizaci* 2>/dev/null | tail -n 1 || true)"
        fi
        if [ -z "$RESTORE_FROM" ] || [ ! -f "$RESTORE_FROM/db.sqlite3" ] || [ -z "$DB" ]; then
            echo "Zálohu k obnově jsem nenašel. Zálohy jsou v $BACKUPS:" >&2
            ls -1 "$BACKUPS" >&2 2>/dev/null || echo "  (žádné)" >&2
            echo "Obnova jiné zálohy: bash deploy/pa-update.sh --obnovit $BACKUPS/NAZEV" >&2
            exit 1
        fi
        echo
        echo "Obnovím ukázku ze zálohy $(basename "$RESTORE_FROM") – databázi a nahrané soubory."
        echo "Současný stav se předtím zazálohuje."
        read -r -p "Pokračovat? Napište OBNOVIT: " ANSWER
        if [ "$ANSWER" != "OBNOVIT" ]; then
            echo "Nic se nezměnilo."
            exit 1
        fi
    fi

    if [ "$MODE" != "--obnovit" ]; then
        echo "Stahuji novou verzi..."
        git pull --ff-only

        echo "Doinstalovávám knihovny..."
        "$VENV/bin/pip" install --no-cache-dir --quiet -r requirements/demo.txt
    fi
    # Tajný klíč Djanga je v produkčním nastavení povinný – bez něj by se
    # nespustil ani následující příkaz. Chybí-li nebo je ukázkový, doplní se.
    if ! grep -qE '^DJANGO_SECRET_KEY=.{32,}$' .env \
       || grep -qE '^DJANGO_SECRET_KEY=(VLOZTE|zmente|__SECRET__|pouze-pro-vyvoj)' .env; then
        local KEY
        KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(50))')"
        sed -i '/^DJANGO_SECRET_KEY=/d' .env
        printf '\n# Tajný klíč Djanga (podpis přihlášení). Neměňte ho.\nDJANGO_SECRET_KEY=%s\n' "$KEY" >> .env
        echo "Do .env byl doplněn DJANGO_SECRET_KEY."
    fi
    # Disk na PythonAnywhere je síťový: režim WAL by mohl ztratit data.
    if ! grep -qE '^SQLITE_WAL=' .env; then
        printf '\n# Disk na PythonAnywhere je síťový – režim WAL by tu mohl ztratit data.\nSQLITE_WAL=False\n' >> .env
    fi
    # Šifrovací klíč (jména, objednávky) – doplní se jen jednou, pak se nemění.
    "$PY" manage.py zajisti_klic

    # --- záloha před každou změnou databáze ---------------------------------
    if [ -n "$DB" ] && [ -f "$DB" ]; then
        echo "Zálohuji databázi a nahrané soubory..."
        local LABEL="pred-aktualizaci"
        [ "$MODE" = "--obnovit" ] && LABEL="pred-obnovou"
        "$PY" manage.py zalohovat --cil "$BACKUPS" --ponechat 10 --popis "$LABEL"
    fi

    case "$MODE" in
        --nova-data)
            echo "Mažu data ukázky ($DB)..."
            # i s pomocnými soubory deníku – jinak by je nová databáze převzala
            rm -f "$DB" "$DB-wal" "$DB-shm" "$DB-journal"
            "$PY" manage.py migrate --noinput --verbosity 0
            "$PY" manage.py bootstrap_demo
            ;;
        --obnovit)
            echo "Obnovuji ze zálohy..."
            rm -f "$DB" "$DB-wal" "$DB-shm" "$DB-journal"
            cp "$RESTORE_FROM/db.sqlite3" "$DB"
            if [ -d "$RESTORE_FROM/media" ]; then
                rm -rf "$APP/media"
                cp -a "$RESTORE_FROM/media" "$APP/media"
            fi
            # záloha může být ze starší verze
            "$PY" manage.py migrate --noinput
            ;;
        *)
            "$PY" manage.py migrate --noinput
            # Nové metriky, protokoly a dotazníky; úpravy z administrace zůstanou.
            "$PY" manage.py seed_catalog --jen-chybejici
            "$PY" manage.py prepocitat_odvozene
            ;;
    esac

    if [ "$MODE" != "--obnovit" ]; then
        # Ukázkové zprávy od AI uložené z laboratorního počítače (demo/ukazkove_zpravy/).
        "$PY" manage.py nacist_ukazky_zprav
        # Ukázkový přístroj DEXA pro průvodce „Nový přístroj“.
        "$PY" manage.py ukazkovy_pristroj
        # Účty portálu (sportovec, rodic, trener), pokud chybí – existující nechá být.
        "$PY" manage.py ukazkove_ucty
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

    # Po restartu: databáze, kterou předchozí verze přepnula do režimu WAL,
    # se vrátí do klasického režimu (jde to, jen když ji nikdo jiný nemá otevřenou).
    sleep 5
    "$PY" manage.py rezim_databaze --opakovat 10 || true
    # Kontrola: databáze, zápis, účty bez pracoviště, poslední chyba webu.
    "$PY" manage.py kontrola_ukazky || true

    local LAST
    LAST="$(ls -1d "$BACKUPS"/ftvs-zaloha-* 2>/dev/null | tail -n 1 || true)"
    if [ -n "$LAST" ]; then
        echo "Záloha před změnou: $LAST"
        echo "Vrátit ji jde příkazem: bash deploy/pa-update.sh --obnovit $LAST"
    fi
    echo "Hotovo – ukázka běží na nové verzi. V prohlížeči stiskněte Ctrl+F5."
}

main "$@"
exit
