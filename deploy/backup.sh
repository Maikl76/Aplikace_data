#!/usr/bin/env bash
# Denní záloha databáze. Spouštět z cronu na serveru.
#
# Tohle je jen dump. Pro obnovu k libovolnému okamžiku (PITR) je potřeba
# navíc archivace WAL – domluvte s fakultním IT.
#
# A hlavně: jednou za čtvrt roku obnovu VYZKOUŠEJTE. Záloha, kterou jste
# nikdy neobnovil, není záloha.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/ftvs}"
KEEP_DAYS="${KEEP_DAYS:-30}"
STAMP="$(date +%Y%m%d-%H%M)"

mkdir -p "$BACKUP_DIR"

docker compose exec -T db pg_dump -U ftvs -Fc ftvs \
    > "$BACKUP_DIR/ftvs-$STAMP.dump"

# Šifrování – záloha obsahuje tatáž citlivá data jako databáze.
if [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
    gpg --encrypt --recipient "$BACKUP_GPG_RECIPIENT" \
        --output "$BACKUP_DIR/ftvs-$STAMP.dump.gpg" \
        "$BACKUP_DIR/ftvs-$STAMP.dump"
    rm "$BACKUP_DIR/ftvs-$STAMP.dump"
fi

find "$BACKUP_DIR" -name 'ftvs-*.dump*' -mtime +"$KEEP_DAYS" -delete

echo "Záloha hotova: $BACKUP_DIR/ftvs-$STAMP.dump"
echo "POZOR: kopie musí existovat i mimo budovu."
