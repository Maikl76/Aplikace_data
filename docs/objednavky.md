# Objednávky testování od klientů

Klient si testování objedná sám na veřejné stránce **`/objednavka/`** (bez
přihlášení). Laboratoř žádost v aplikaci schválí (*Objednávky*) a aplikace
sama založí sportovce, souhlasy a testovací dny s objednanými testy.

Návod k ovládání je v aplikaci: **O aplikaci → Objednávky od klientů**.

## Příprava (jednou)

1. **Nabídka a ceny** – *Objednávky → Nabídka a ceny*: balíčky a jednotlivé
   testy, cena za osobu, které testy se po schválení založí.
2. **Volné termíny** – *Objednávky → Volné termíny*: vypsat hromadně.
3. **Odkaz** na formulář dát na web, do e-mailu, na plakát.

## Pro IT: co musí být vidět z internetu

Aplikace jinak může běžet jen ve fakultní síti. Z internetu stačí zpřístupnit:

| Cesta | K čemu |
|---|---|
| `/objednavka/` (včetně podstránek) | formulář, potvrzení e-mailu, stav objednávky |
| `/d/` (včetně podstránek) | RPE na telefonu sportovce |
| `/static/` | styly a skripty těchto stránek |

Vše ostatní (přihlášení, sportovci, výsledky) může zůstat jen ve fakultní síti
nebo za VPN. Veřejné stránky nic z databáze neukazují kromě nabídky a volných
termínů; stav objednávky vidí jen ten, kdo má odkaz s náhodným kódem.

## Nastavení (`.env`)

```
# poštovní server – bez něj se e-maily jen zapíšou do záznamu serveru
EMAIL_HOST=smtp.example.cz
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=Laboratoř FTVS <diagnostika@ftvs.cuni.cz>

# žádost uvidí laboratoř až po kliknutí na odkaz v e-mailu (ochrana před
# podvrženými objednávkami) – zapnout, až budou e-maily fungovat
BOOKING_VERIFY_EMAIL=True

# při více organizacích: pro kterou je formulář (zkratka)
BOOKING_ORGANIZATION=ftvs
```

## Ochrana údajů

- Jména, data narození, kontakty a zranění se ukládají **šifrovaně** (stejný
  klíč jako u identity sportovců). Bez klíče se formulář nenabízí.
- Objednávky vidí jen správce a diagnostik (role, které vidí jména).
- Proti robotům: skryté pole a nejvýš 5 objednávek z jedné adresy za hodinu.
