#!/usr/bin/env bash
# Aktualizace aplikace na fakultním serveru.
#
#     bash deploy/server-update.sh            # nejnovější vydaná verze (větev main)
#     bash deploy/server-update.sh v1.4       # konkrétní verze (tag)
#     bash deploy/server-update.sh --zpet     # návrat na verzi před poslední aktualizací
#
# Postup: záloha databáze → stažení verze → sestavení → úprava databáze
# (migrace) → doplnění katalogu → restart → kontrola, že aplikace odpovídá.
# Data zůstávají; aplikace je nedostupná zhruba minutu.

# Celé ve funkci – git pull může skript uprostřed běhu přepsat.
main() {
    set -euo pipefail
    cd "$(dirname "$0")/.."

    local COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
    local PREVIOUS_FILE=".predchozi-verze"
    local target="${1:-main}"

    if [ "$target" = "--zpet" ]; then
        [ -f "$PREVIOUS_FILE" ] || { echo "Není zaznamenaná předchozí verze." >&2; exit 1; }
        target="$(cat "$PREVIOUS_FILE")"
        echo "Návrat na verzi $target."
        echo "POZOR: pokud nová verze změnila databázi, obnovte i zálohu pořízenou"
        echo "před aktualizací (viz docs/aktualizace-serveru.md, část Návrat)."
    fi

    echo "1/6 Záloha databáze..."
    bash deploy/backup.sh

    echo "2/6 Stahuji verzi $target..."
    git rev-parse HEAD > "$PREVIOUS_FILE"
    git fetch --quiet --tags origin
    if git show-ref --verify --quiet "refs/remotes/origin/$target"; then
        git checkout --quiet "$target"
        git merge --quiet --ff-only "origin/$target"
    else
        git checkout --quiet "$target"          # tag nebo konkrétní commit
    fi
    echo "   verze: $(git describe --tags --always)"

    echo "3/6 Sestavuji..."
    $COMPOSE build --quiet web worker

    echo "4/6 Upravuji databázi a doplňuji katalog..."
    $COMPOSE run --rm web python manage.py migrate --noinput
    $COMPOSE run --rm web python manage.py seed_catalog --jen-chybejici
    $COMPOSE run --rm web python manage.py prepocitat_odvozene

    echo "5/6 Restartuji..."
    $COMPOSE up -d

    echo "6/6 Kontroluji, že aplikace odpovídá..."
    local ok=""
    for _ in $(seq 1 30); do
        if $COMPOSE exec -T web python -c \
            "import urllib.request; urllib.request.urlopen('http://localhost:8000/zdravi/', timeout=3)" \
            >/dev/null 2>&1; then ok=1; break; fi
        sleep 2
    done
    if [ -z "$ok" ]; then
        echo "Aplikace po aktualizaci neodpovídá. Logy: $COMPOSE logs --tail 50 web" >&2
        echo "Návrat na předchozí verzi: bash deploy/server-update.sh --zpet" >&2
        exit 1
    fi
    echo "Hotovo – běží verze $(git describe --tags --always)."
}

main "$@"
exit
