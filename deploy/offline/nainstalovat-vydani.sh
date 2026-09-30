#!/usr/bin/env bash
# Instalace a aktualizace aplikace na serveru BEZ internetu (z flash disku).
#
#   sudo bash nainstalovat-vydani.sh /media/usb/ftvs-v1.1.tar.gz   # instalace i aktualizace
#   sudo bash nainstalovat-vydani.sh --zpet                        # návrat na předchozí verzi
#   sudo bash nainstalovat-vydani.sh --ai /media/usb/ftvs-ai-….tar.gz  # jazykový model (jednou)
#   sudo bash nainstalovat-vydani.sh --stav                        # co běží
#   sudo bash nainstalovat-vydani.sh --zaloha                      # záloha (i denně z cronu)
#   sudo bash nainstalovat-vydani.sh --obnovit /opt/ftvs/zalohy/….dump  # obnova databáze
#
# Všechno žije v /opt/ftvs (jiné místo: FTVS_DIR=/cesta):
#   .env        nastavení a tajné klíče – vznikne při první instalaci, pak se nemění
#   verze/      rozbalené verze aplikace (poslední tři)
#   aktualni    odkaz na běžící verzi
#   zalohy/     záloha databáze před každou aktualizací
#   certs/      certifikát od IT (volitelně)
#   ai/         jazykový model (volitelně)
# Data (databáze, nahrané soubory) jsou v úložištích Dockeru projektu „ftvs“
# a přechod na jinou verzi je nemění.

FTVS_DIR="${FTVS_DIR:-/opt/ftvs}"
export FTVS_DIR

compose() {
    local profiles=()
    [ -d "$FTVS_DIR/ai" ] && grep -q '^LLM_ENABLED=True' "$FTVS_DIR/.env" 2>/dev/null \
        && profiles=(--profile ai)
    docker compose -p ftvs --env-file "$FTVS_DIR/.env" \
        -f "$FTVS_DIR/aktualni/docker-compose.yml" "${profiles[@]}" "$@"
}

running() {
    [ -L "$FTVS_DIR/aktualni" ] && [ -n "$(compose ps -q db 2>/dev/null)" ]
}

backup() {
    local label="$1"
    running || return 0
    local file
    file="$FTVS_DIR/zalohy/ftvs-$(date +%Y%m%d-%H%M)-${label}.dump"
    echo "   záloha databáze: $file"
    compose exec -T db pg_dump -U ftvs -Fc ftvs > "$file"
}

health() {
    echo "   kontroluji, že aplikace odpovídá..."
    for _ in $(seq 1 45); do
        if compose exec -T web python -c "
import os, urllib.request
host = os.environ['DJANGO_ALLOWED_HOSTS'].split(',')[0]
req = urllib.request.Request('http://localhost:8000/zdravi/',
                             headers={'Host': host, 'X-Forwarded-Proto': 'https'})
urllib.request.urlopen(req, timeout=3)" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

first_env() {
    # Při první instalaci: .env ze šablony, hesla a klíče vygeneruje obraz aplikace.
    local version="$1" host="${FTVS_HOST:-}"
    if [ -z "$host" ]; then
        read -r -p "Adresa serveru, jak ji budou psát laboratoře (např. diagnostika.ftvs.cuni.cz): " host
    fi
    [ -n "$host" ] || { echo "Adresa je potřeba." >&2; exit 1; }
    local secrets
    secrets="$(docker run --rm "ftvs-web:${version}" python -c "
import secrets
from cryptography.fernet import Fernet
print(secrets.token_urlsafe(50), secrets.token_hex(16), Fernet.generate_key().decode())")"
    read -r secret dbpass idkey <<< "$secrets"
    sed -e "s|__HOST__|${host}|g" -e "s|__SECRET__|${secret}|" \
        -e "s|__DBPASS__|${dbpass}|g" -e "s|__IDKEY__|${idkey}|" \
        "$FTVS_DIR/aktualni/server.env.example" > "$FTVS_DIR/.env"
    chmod 600 "$FTVS_DIR/.env"
    echo "   vytvořeno $FTVS_DIR/.env (hesla a klíč k jménům)."
    echo "   !!! Soubor .env zazálohujte zvlášť – bez klíče nejdou přečíst jména. !!!"
}

install() {
    local package="$1" tmp src version target previous="" first=""
    [ -f "$package" ] || { echo "Soubor $package neexistuje." >&2; exit 1; }
    mkdir -p "$FTVS_DIR/verze" "$FTVS_DIR/zalohy" "$FTVS_DIR/certs"

    echo "1/7 Rozbaluji a kontroluji balíček..."
    tmp="$(mktemp -d "$FTVS_DIR/.rozbaleni.XXXX")"
    tar -xzf "$package" -C "$tmp"
    src="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
    (cd "$src" && sha256sum --quiet -c SHA256SUMS) \
        || { echo "Balíček je poškozený (kontrolní součty nesedí)." >&2; exit 1; }
    version="$(head -1 "$src/VERZE")"
    echo "   verze $version"

    echo "2/7 Načítám programy do Dockeru (chvíli to trvá)..."
    docker load -i "$src/obrazy.tar" >/dev/null
    rm "$src/obrazy.tar"

    echo "3/7 Záloha databáze..."
    backup "pred-${version}"

    echo "4/7 Přepínám na verzi $version..."
    [ -L "$FTVS_DIR/aktualni" ] && previous="$(readlink "$FTVS_DIR/aktualni")"
    target="$FTVS_DIR/verze/$version"
    rm -rf "$target"
    mv "$src" "$target"
    rm -rf "$tmp"
    ln -sfn "$target" "$FTVS_DIR/aktualni"
    if [ -n "$previous" ] && [ "$previous" != "$target" ]; then
        echo "$previous" > "$FTVS_DIR/predchozi"
    fi
    if [ ! -f "$FTVS_DIR/.env" ]; then
        first=1
        first_env "$version"
    fi

    echo "5/7 Upravuji databázi..."
    compose up -d db
    compose run --rm web python manage.py migrate --noinput
    if [ -n "$first" ]; then
        compose run --rm web python manage.py seed_catalog
        compose run --rm web python manage.py seed_roles
    else
        compose run --rm web python manage.py seed_catalog --jen-chybejici
        compose run --rm web python manage.py prepocitat_odvozene
    fi

    echo "6/7 Spouštím..."
    compose up -d --remove-orphans

    echo "7/7 Kontrola..."
    if ! health; then
        echo "Aplikace neodpovídá. Posledních 40 řádků záznamu:" >&2
        compose logs --tail 40 web >&2
        echo "Návrat na předchozí verzi: sudo bash $0 --zpet" >&2
        exit 1
    fi

    # Uklid: nechat poslední tři verze.
    ls -1dt "$FTVS_DIR"/verze/*/ 2>/dev/null | tail -n +4 | while read -r old; do
        [ "$(realpath "$old")" = "$(realpath "$FTVS_DIR/aktualni")" ] && continue
        docker image rm "ftvs-web:$(basename "$old")" >/dev/null 2>&1 || true
        rm -rf "$old"
    done

    echo
    echo "Hotovo – běží verze $version: https://$(grep '^FTVS_HOST=' "$FTVS_DIR/.env" | cut -d= -f2)"
    if [ -n "$first" ]; then
        echo
        echo "První instalace – založte účet správce:"
        echo "  sudo FTVS_DIR=$FTVS_DIR docker compose -p ftvs --env-file $FTVS_DIR/.env \\"
        echo "       -f $FTVS_DIR/aktualni/docker-compose.yml run --rm web python manage.py createsuperuser"
    fi
}

rollback() {
    [ -f "$FTVS_DIR/predchozi" ] || { echo "Předchozí verze není zaznamenaná." >&2; exit 1; }
    local previous
    previous="$(cat "$FTVS_DIR/predchozi")"
    [ -d "$previous" ] || { echo "Předchozí verze už na disku není ($previous)." >&2; exit 1; }
    echo "Návrat na $(basename "$previous")."
    backup "pred-navratem"
    # Zapamatovat si, odkud se vracíme – další --zpet přepne zase tam.
    readlink "$FTVS_DIR/aktualni" > "$FTVS_DIR/predchozi"
    ln -sfn "$previous" "$FTVS_DIR/aktualni"
    compose up -d --remove-orphans
    health || { echo "Ani předchozí verze neodpovídá – viz: compose logs web" >&2; exit 1; }
    echo "Hotovo. Pokud nová verze změnila databázi a laboratoře mezitím nic"
    echo "nezadaly, obnovte i zálohu z $FTVS_DIR/zalohy (viz offline-server.md)."
}

install_ai() {
    local package="$1" tmp model wanted
    [ -f "$package" ] || { echo "Soubor $package neexistuje." >&2; exit 1; }
    [ -f "$FTVS_DIR/.env" ] || { echo "Nejdřív nainstalujte aplikaci." >&2; exit 1; }
    echo "Instaluji jazykový model..."
    tmp="$(mktemp -d "$FTVS_DIR/.ai.XXXX")"
    case "$package" in
        # Z GitHubu přijde rozdělený na části (…part-00, …part-01) – spojit.
        *.part-[0-9][0-9]) cat "${package%.part-*}".part-[0-9][0-9] | tar -xz -C "$tmp" ;;
        *) tar -xzf "$package" -C "$tmp" ;;
    esac
    docker load -i "$tmp"/*/ollama-obraz.tar >/dev/null
    model="$(cat "$tmp"/*/MODEL)"
    # Obraz pod jménem, které čeká docker-compose.yml (kdyby se balilo z jiného zdroje).
    wanted="$(sed -n '/^  llm:/,/image:/s/^ *image: *//p' "$FTVS_DIR/aktualni/docker-compose.yml")"
    [ -n "$wanted" ] && docker tag "$(cat "$tmp"/*/OBRAZ)" "$wanted"
    rm -rf "$FTVS_DIR/ai"
    mv "$tmp"/*/ollama "$FTVS_DIR/ai"
    rm -rf "$tmp"
    sed -i -e "s|^LLM_ENABLED=.*|LLM_ENABLED=True|" -e "s|^LLM_MODEL=.*|LLM_MODEL=${model}|" \
        -e "s|^LLM_BASE_URL=.*|LLM_BASE_URL=http://llm:11434/v1|" "$FTVS_DIR/.env"
    compose up -d --remove-orphans
    echo "Hotovo – zprávy píše model $model. Na serveru bez grafické karty to trvá déle."
}

daily_backup() {
    running || { echo "Databáze neběží – není co zálohovat." >&2; exit 1; }
    backup "denni"
    # Denní zálohy starší než 30 dní pryč; zálohy před aktualizací zůstávají.
    find "$FTVS_DIR/zalohy" -name '*-denni.dump' -mtime +30 -delete
}

restore() {
    local file="$1"
    [ -f "$file" ] || { echo "Soubor $file neexistuje." >&2; exit 1; }
    running || { echo "Databáze neběží." >&2; exit 1; }
    echo "Obnova databáze ze zálohy $(basename "$file")."
    echo "Všechno, co se zadalo po jejím vytvoření, se ztratí."
    local answer
    read -r -p "Opravdu obnovit? Napište ano: " answer
    [ "$answer" = "ano" ] || { echo "Nic se nezměnilo."; exit 0; }
    backup "pred-obnovou"
    compose stop web
    compose exec -T db pg_restore -U ftvs -d ftvs --clean --if-exists --no-owner < "$file"
    compose up -d
    health || { echo "Aplikace po obnově neodpovídá – viz: compose logs web" >&2; exit 1; }
    echo "Hotovo."
}

status() {
    [ -L "$FTVS_DIR/aktualni" ] || { echo "Aplikace není nainstalovaná."; exit 0; }
    echo "Verze: $(head -1 "$FTVS_DIR/aktualni/VERZE")  ($(sed -n 3p "$FTVS_DIR/aktualni/VERZE"))"
    compose ps
    echo "Zálohy: $(ls -1 "$FTVS_DIR/zalohy" | wc -l) v $FTVS_DIR/zalohy"
}

main() {
    set -euo pipefail
    command -v docker >/dev/null || { echo "Na serveru chybí Docker." >&2; exit 1; }
    case "${1:-}" in
        --zpet) rollback ;;
        --stav) status ;;
        --zaloha) daily_backup ;;
        --obnovit) restore "${2:?Zadejte soubor se zálohou}" ;;
        --ai) install_ai "${2:?Zadejte soubor s AI balíčkem}" ;;
        ""|-h|--help) sed -n 2,10p "$0" ;;
        *) install "$1" ;;
    esac
}

main "$@"
exit
