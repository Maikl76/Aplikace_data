# Baterie testů a Dnešní testování

## Baterie testů (Sporty a testy)

Pro každý sport určíte, které testy se měří a v jakém pořadí. Baterie může
být i pro **kategorii** (např. hokej – dorost); sportovec s touto kategorií
dostane ji, ostatní baterii celého sportu. Kategorie se nastavuje u
sportovce (úprava údajů).

- **Přidat test:** výběr pod baterií → Přidat.
- **Pořadí:** šipky ↑ ↓.
- **Odebrat:** ✕. Naměřená data zůstanou, změní se jen to, co se nabízí příště.
- Nový sport dostane rovnou prázdnou baterii.

Baterie se přenáší s katalogem (`ulozit-katalog.bat` / `nacist-katalog.bat`).

## Nový testovací den

Po výběru sportovce se testy zaškrtnou podle baterie jeho sportu
a kategorie. Odškrtnout nebo přidat jde podle potřeby.

## Dnešní testování

Vyberete baterii a datum a vidíte všechny sportovce daného sportu
(a kategorie) proti testům baterie:

- **hotovo** – test má naměřené hodnoty,
- **zadat** – test je založený, čeká na hodnoty,
- **—** – nic.

Zaškrtnete sportovce a **Založit testování pro vybrané** – každému vznikne
testovací den se všemi testy baterie. Hodnoty pak zadáte ručně, nebo
nahrajete export z přístroje: **import doplní hodnoty do založených testů**
(nevznikne vedle nich druhý).

Vypočtené ukazatele (DSI, EUR) se v baterii nezakládají, dopočítají se samy.

## Týmový přehled

Menu **Týmový přehled** ukáže všechny aktivní sportovce skupiny (sport, případně
kategorie podle baterie) a v sloupcích klíčové ukazatele testů baterie –
tedy metriky, které mají v katalogu u protokolu zaškrtnuté „klíčová metrika“.

V každé buňce je poslední hlavní měření sportovce (opakování po zátěži se
nepočítá) a dvě informace, které se nepletou:

- **šipka** – změna proti minulému měření téhož sportovce, posouzená proti MDC
  stejně jako ve zprávě (bez MDC se o zlepšení nemluví),
- **barva pozadí** – postavení v týmu: zelená = o 1 SD a víc lepší než průměr
  skupiny, oranžová = o 1 SD a víc horší. Bere se ohled na to, zda je lepší
  vyšší, nebo nižší hodnota (u plochy CoP je lepší menší). Počítá se až od
  4 změřených sportovců.

Hodnoty starší než 120 dní jsou zašedlé. Podrobnosti (datum, změna, odchylka
od průměru) se ukážou po najetí myší. Klepnutím na záhlaví se řadí, tlačítko
**CSV pro Excel** stáhne tabulku (středník, desetinná čárka).
