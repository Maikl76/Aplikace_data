#!/usr/bin/env bash
# Připraví jednorázový balíček s jazykovým modelem pro server BEZ internetu.
#
#     bash deploy/offline/pripravit-ai-balicek.sh             # výchozí gemma3:4b
#     bash deploy/offline/pripravit-ai-balicek.sh gemma3:12b  # větší model (potřebuje víc paměti)
#
# Potřebuje počítač s Dockerem a internetem. Výsledek (několik GB):
# dist/ftvs-ai-gemma3-4b.tar.gz – přenést na flash disku a na serveru:
#
#     sudo bash nainstalovat-vydani.sh --ai /media/usb/ftvs-ai-gemma3-4b.tar.gz
#
# Model se přenáší jen jednou; aktualizace aplikace ho nemění.
# OLLAMA_IMAGE=… – jiný zdroj obrazu Ollama (výchozí ollama/ollama:latest).

main() {
    set -euo pipefail
    cd "$(dirname "$0")/../.."

    local model="${1:-gemma3:4b}"
    local image="${OLLAMA_IMAGE:-ollama/ollama:latest}"
    local name="ftvs-ai-${model//[:\/]/-}"
    local work="dist/${name}"

    echo "1/3 Stahuji Ollamu a model ${model} (podle rychlosti sítě i desítky minut)..."
    docker pull --quiet "$image" >/dev/null
    rm -rf "$work"
    mkdir -p "$work/ollama"
    box="ftvs-ai-priprava-$$"  # globální – čte ho past při ukončení
    docker run -d --name "$box" -v "$PWD/$work/ollama:/root/.ollama" "$image" >/dev/null
    trap 'docker rm -f "$box" >/dev/null 2>&1 || true' EXIT
    sleep 3
    docker exec "$box" ollama pull "$model"
    # Soubory modelu patří v kontejneru rootovi – vrátit je tomu, kdo balí.
    docker exec "$box" chown -R "$(id -u):$(id -g)" /root/.ollama
    docker rm -f "$box" >/dev/null

    echo "2/3 Balím..."
    docker save -o "$work/ollama-obraz.tar" "$image"
    echo "$model" > "$work/MODEL"
    echo "$image" > "$work/OBRAZ"

    echo "3/3 Komprimuji..."
    tar -czf "dist/${name}.tar.gz" -C dist "$name"
    rm -rf "$work"
    echo "Hotovo: dist/${name}.tar.gz ($(du -h "dist/${name}.tar.gz" | cut -f1))"
}

main "$@"
exit
