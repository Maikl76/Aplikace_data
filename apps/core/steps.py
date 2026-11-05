"""
Kroky průvodce: jeden tvar pro celou aplikaci.

Krok se nikdy neodškrtává ručně – stav plyne z dat. Každý krok říká
jednou větou, co chybí, a má tlačítko, které vede přímo tam. Značka
{% steps %} (apps/core/templatetags/ui.py) je vykreslí všude stejně:
v genetice, v přehledu, u sportovce, v nastavení pracoviště.

Krok je slovník s klíči:
  n, title, done, text          – povinné
  url, button                   – tlačítko; url "#kotva" = skok na stránce
  optional                      – volitelný krok nebrání „vše hotovo“
  admin_only                    – tlačítko jen správci, ostatním „nastavuje správce“
  count                         – kolik položek čeká (odznak u názvu)
"""


def step(n, title, done, text="", *, url="", button="", optional=False, admin_only=False,
         count=None) -> dict:
    return {"n": n, "title": title, "done": bool(done), "text": text, "url": url,
            "button": button, "optional": optional, "admin_only": admin_only, "count": count}


def next_step(steps):
    """První nehotový povinný krok; když jsou všechny povinné hotové, první nehotový volitelný."""
    pending = [s for s in steps if not s["done"]]
    required = [s for s in pending if not s.get("optional")]
    return (required or pending or [None])[0]


def grid_class(count: int) -> str:
    """Třídy mřížky pro daný počet kroků (celé řetězce, aby je našel Tailwind)."""
    return {
        1: "grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-3",
        4: "md:grid-cols-2 xl:grid-cols-4", 5: "sm:grid-cols-2 lg:grid-cols-5",
        6: "sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6",
        7: "sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7",
        8: "sm:grid-cols-2 lg:grid-cols-4",
    }.get(count, "sm:grid-cols-2 lg:grid-cols-3")
