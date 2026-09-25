"""
Hlídá, aby se odlehčená sada knihoven pro ukázku nerozešla s plnou.

Ukázka má běžet na stejném kódu jako provoz. Kdyby v demo.txt přibyla
knihovna, která v base.txt není, ukázka by se od provozu tiše lišila.
"""

import re
from pathlib import Path

REQ = Path(__file__).resolve().parent.parent / "requirements"


def _packages(path: Path) -> set[str]:
    names = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-r"):
            continue
        name = re.split(r"[<>=!;\[ ]", line, maxsplit=1)[0]
        names.add(name.lower().replace("_", "-"))
    return names


def test_demo_je_podmnozinou_base():
    navic = _packages(REQ / "demo.txt") - _packages(REQ / "base.txt")
    assert not navic, f"V demo.txt jsou knihovny, které base.txt nemá: {navic}"


def test_demo_obsahuje_to_co_se_importuje_pri_startu():
    """Celery se importuje v config/__init__.py – bez něj aplikace nenaběhne."""
    demo = _packages(REQ / "demo.txt")
    for nutne in ("django", "django-environ", "celery", "whitenoise", "cryptography"):
        assert nutne in demo, f"{nutne} chybí v demo.txt"
