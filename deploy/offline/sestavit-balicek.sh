#!/usr/bin/env bash
# Sestaví instalační balíček pro server BEZ internetu (přenos na flash disku).
#
#     bash deploy/offline/sestavit-balicek.sh v1.1
#
# Potřebuje počítač s Dockerem a internetem (dělá to i GitHub sám při
# označení verze – viz .github/workflows/offline-balicek.yml).
# Výsledek: dist/ftvs-v1.1.tar.gz – obsahuje aplikaci i všechny programy,
# které server potřebuje (databázi, HTTPS bránu), a instalační skript.
#
# REGISTRY_MIRROR=mirror.gcr.io/library/  – když Docker Hub omezuje stahování.

main() {
    set -euo pipefail
    cd "$(dirname "$0")/../.."

    local version="${1:?Zadejte verzi, např. v1.1}"
    local mirror="${REGISTRY_MIRROR:-}"
    local postgres="${mirror}postgres:16-alpine"
    local caddy="${mirror}caddy:2"
    local ollama="${OLLAMA_IMAGE:-ollama/ollama:latest}"
    local name="ftvs-${version}"
    local work="dist/${name}"

    echo "1/4 Sestavuji obraz aplikace ftvs-web:${version}..."
    docker build --quiet \
        --build-arg BASE_IMAGE="${mirror}python:3.12-slim" \
        --build-arg REQUIREMENTS=requirements/base.txt \
        -t "ftvs-web:${version}" . >/dev/null

    echo "2/4 Stahuji databázi a HTTPS bránu..."
    docker pull --quiet "$postgres" >/dev/null
    docker pull --quiet "$caddy" >/dev/null

    echo "3/4 Balím..."
    rm -rf "$work"
    mkdir -p "$work"
    docker save -o "$work/obrazy.tar" "ftvs-web:${version}" "$postgres" "$caddy"
    sed -e "s|__VERZE__|${version}|" -e "s|__POSTGRES_IMAGE__|${postgres}|" \
        -e "s|__CADDY_IMAGE__|${caddy}|" -e "s|__OLLAMA_IMAGE__|${ollama}|" \
        deploy/offline/docker-compose.yml > "$work/docker-compose.yml"
    cp deploy/offline/Caddyfile deploy/offline/server.env.example \
       deploy/offline/nainstalovat-vydani.sh docs/offline-server.md "$work/"
    {
        echo "$version"
        echo "commit $(git rev-parse --short HEAD 2>/dev/null || echo neznamy)"
        echo "sestaveno $(date -u +%Y-%m-%dT%H:%MZ)"
    } > "$work/VERZE"
    (cd "$work" && sha256sum obrazy.tar docker-compose.yml Caddyfile \
        nainstalovat-vydani.sh VERZE > SHA256SUMS)

    echo "4/4 Komprimuji..."
    tar -czf "dist/${name}.tar.gz" -C dist "$name"
    rm -rf "$work"
    echo "Hotovo: dist/${name}.tar.gz ($(du -h "dist/${name}.tar.gz" | cut -f1))"
}

main "$@"
exit
