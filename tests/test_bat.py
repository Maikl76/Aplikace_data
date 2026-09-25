"""
Dávkové soubory pro Windows.

cmd čte .bat v kódové stránce konzole, ne v UTF-8 – diakritika by se
rozsypala a u cest se jménem „Vágner“ by se rozbilo i víc. Proto jen ASCII.
Konce řádků musí být CRLF, jinak cmd špatně skáče na návěští (goto chyba).
"""

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
