"""
Dávkové soubory pro Windows.

cmd čte .bat v kódové stránce konzole, ne v UTF-8 – diakritika by se
rozsypala a u cest se jménem „Vágner“ by se rozbilo i víc. Proto jen ASCII.
Konce řádků musí být CRLF, jinak cmd špatně skáče na návěští (goto chyba).
"""

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BATS = sorted(ROOT.glob("*.bat"))


def test_davkove_soubory_existuji():
    assert {p.name for p in BATS} >= {"zalozit.bat", "spustit.bat",
                                       "ulozit-katalog.bat", "nacist-katalog.bat"}


@pytest.mark.parametrize("path", BATS, ids=lambda p: p.name)
def test_jen_ascii_a_crlf(path):
    data = path.read_bytes()
    assert data.isascii()
    assert b"\n" not in data.replace(b"\r\n", b"")


@pytest.mark.parametrize("path", BATS, ids=lambda p: p.name)
def test_bezi_ze_sve_slozky(path):
    """Dvojklik z Průzkumníka nemusí začít ve složce aplikace."""
    assert 'cd /d "%~dp0"' in path.read_text()


# --- aktualizace přes git pull -------------------------------------------------------
#
# Místní změna souboru aplikace (fly.toml po pokusu o nasazení) zastavila git pull
# hláškou „Your local changes … would be overwritten by merge“. Proto se před
# stažením místní změny odloží do git stash (nic se nesmaže).
#
# cmd čte .bat průběžně: když git pull přepíše soubor, který právě běží, cmd
# pokračuje od bajtu, kde ve STARÉ verzi končil řádek git pull. Začátek souboru
# až po git pull se proto už nesmí měnit a staré verze musí po aktualizaci
# navázat na celý řádek, ne na půlku příkazu.

PULL = b"git pull || goto chyba\r\n"
STASH = b"git -c user.name=aplikace -c user.email=aplikace@localhost stash push"
PULLING = [p for p in BATS if PULL in p.read_bytes()]
# kde končil řádek git pull ve verzích před pojistkou (všechny měly stejný začátek)
OLD_RESUME = {"spustit.bat": 392, "nacist-katalog.bat": 413, "ulozit-katalog.bat": 239,
              "ulozit-ukazku-zpravy.bat": 227}
FROZEN = {'spustit.bat': '209dffba17b47f08', 'nacist-katalog.bat': '67bfd9b5a3b3f1f1', 'ulozit-katalog.bat': '3f637f26e849b475', 'ulozit-ukazku-zpravy.bat': '82b33e40b857ee94'}


def test_aktualizuji_vsechny_ocekavane():
    assert {p.name for p in PULLING} == set(OLD_RESUME) == set(FROZEN)


@pytest.mark.parametrize("path", PULLING, ids=lambda p: p.name)
def test_pred_stazenim_odlozi_mistni_zmeny(path):
    data = path.read_bytes()
    assert b"git diff --quiet HEAD --" in data
    assert data.index(STASH) < data.index(PULL)


@pytest.mark.parametrize("name", sorted(OLD_RESUME))
def test_po_aktualizaci_ze_stare_verze_cmd_navaze_na_cely_radek(name):
    data = (ROOT / name).read_bytes()
    resume = OLD_RESUME[name]
    assert data[resume - 2:resume] == b"\r\n"
    # pojistka proběhne znovu (strom je po pull čistý) a git pull jen ohlásí „Already up to date“
    assert data[resume:].startswith(b"rem Mistni zmeny")


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_zacatek_az_po_git_pull_se_nemeni(name):
    data = (ROOT / name).read_bytes()
    prefix = data[: data.index(PULL) + len(PULL)]
    assert hashlib.sha256(prefix).hexdigest()[:16] == FROZEN[name], (
        f"{name}: řádky až po git pull nemeňte – soubor, který git pull za běhu přepíše, "
        "by cmd četl od staré pozice. Nové příkazy patří až za git pull.")
