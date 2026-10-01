# Nový přístroj – import z dalšího přístroje bez programování

Aplikace umí od začátku exporty z VALD (ForceDecks, HumanTrak). Další
přístroj – **DEXA**, InBody, Tanita, Biodex, spiroergometrie… – přidá
správce sám průvodcem, pokud přístroj umí uložit výsledky jako **tabulku**
(CSV nebo Excel). Stačí jeden ukázkový export a pár kliknutí.

Na vyzkoušení je v repozitáři vymyšlený export
[`demo/ukazkovy-export-dexa.csv`](../demo/ukazkovy-export-dexa.csv).

## Kde

**Import → Přístroje → Přidat přístroj.** Vidí to jen role Správce.

## Čtyři kroky

**1. Ukázkový soubor.** Název přístroje (jak mu v laboratoři říkáte),
který test měří (např. *Složení těla*) a jeden běžný export z přístroje.
Ze souboru se uloží jen **názvy sloupců**; pár řádků se ukáže jako ukázka
hodnot a po uložení přístroje se zahodí.

**2. Kdo a kdy.** Ve kterém sloupci je jméno (v jednom sloupci, nebo
křestní jméno a příjmení zvlášť) a **datum měření** (povinné). Nepovinně
ID člověka v přístroji, čas, datum narození a pohlaví. Aplikace je
předvyplní podle názvů sloupců a ukáže hodnotu z prvního řádku.

> ID z přístroje stojí za to vybrat: páruje spolehlivěji než jméno.
> Jakmile se člověk jednou spáruje, příští export ho pozná i s překlepem
> ve jméně.

**3. Naměřené hodnoty.** U každého sloupce s čísly vyberte metriku, nebo
nechte *nepoužít*. Řádky označené **návrh** předvyplnila aplikace podle
názvu sloupce a jednotky – zkontrolujte je.

- **Metrika chybí?** *＋ Nová metrika* – název, jednotka a co je lepší.
  Založí se v katalogu a přidá k testu. Věrohodný rozsah a MDC doplníte
  později v Katalogu → Metriky.
- **Upřesnit** – strana (levá / pravá), část těla (paže, noha, trup) a
  **převod**. Když přístroj píše gramy a metrika je v kg, převod je 0,001
  (u g, ms a mm ho aplikace nastaví sama).
- Dlouhý export (DEXA má desítky sloupců): pole *Hledat sloupec*,
  přepínače *jen sloupce s čísly* a *jen přiřazené*.

**4. Uložit.** Lišta dole ukazuje, kolik sloupců se bude importovat.

## Pak už jen Import

Export z přístroje nahrajte v **Importu** jako z VALD – aplikace ho pozná
podle sloupců sama. Dál je to stejné: kontrola před uložením, párování
sportovců (i s objednaným termínem), uložení.

Jeden řádek exportu = jedno měření jednoho člověka. Víc řádků téhož
člověka se stejným datem (a časem) jsou pokusy jednoho testu.

## Když výrobce změní export

Import → Přístroje → *upravit* → **Nový ukázkový soubor**. Aplikace řekne,
které sloupce zmizely; přiřazení, které platí dál, zůstane. Nové nebo
přejmenované sloupce přiřaďte a uložte. Staré importy jdou doplnit
tlačítkem *načíst znovu* v historii importů.

## Přenos na jiný počítač a na server

Přístroje (jen nastavení, žádná data) se přenášejí s katalogem
(`ulozit-katalog.bat` / `nacist-katalog.bat`), stejně jako profily importu.

## Co průvodce neumí

- Výsledky jen v **PDF** nebo jako obrázek grafu – to je potřeba
  doprogramovat (adaptér v `apps/ingest/adapters/`).
- Víc různých testů v jednom souboru se sloupcem „typ testu“ (jako VALD).
  Pro každý test přidejte přístroj zvlášť, nebo exportujte testy zvlášť.
