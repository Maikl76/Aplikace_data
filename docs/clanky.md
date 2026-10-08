# Vědecké články ve zprávách

Knihovna článků je v aplikaci v **Sporty a testy → Články** (spravuje ji
správce; ostatní ji vidí jen ke čtení). Do zprávy ani k jazykovému modelu
se nedostane nic, co člověk nezařadil.

## Jak se článek dostane do zprávy

| Cesta | Kdy | Ve zprávě |
|---|---|---|
| **Pravidlo** | pravidlo, ke kterému je článek připojený, u měření našlo nález | v citovaných zdrojích vždy |
| **Téma** | článek se vztahuje k ukazateli nebo testu, který se u sportovce měřil | jen když na něj souhrn nebo komentář odkazuje číslem [n] |

U témat dostane model nejvýš 8 článků. Přednost mají ukazatele, které se
proti minulému měření změnily víc než o chybu měření (MDC) nebo mají
stranový rozdíl nad prahem, pak články se shodným sportem a silnějším
důkazem (metaanalýza → RCT → kohorta → …) a novější.

Čísla [1], [2]… se zafixují při vzniku konceptu zprávy. Když mezitím
přibude nebo se zařadí další článek, souhrn i návrh doporučení dál
ukazují na tytéž články. Nová verze zprávy dostane aktuální výběr.

## Co z článku dostane model

Jen to, co ověřil člověk:

- **hlavní zjištění pro praxi** – 1–3 věty, co studie zjistila a co to
  znamená pro testování nebo trénink (když chybí, použije se interní
  poznámka kurátora),
- **omezení** – malý vzorek, jiná populace, jen korelace…,
- **úroveň evidence** a **populace studie** (sport, pohlaví, věk, úroveň, n),
- zda populace **odpovídá sportovci** (pohlaví, věk v den testování),
- **proč je článek u zprávy** (k nálezu, k ukazateli se změnou…).

Abstrakt model nedostává – vykládal by si ho po svém. Čísla, která napíšete
do hlavního zjištění, smí model ve zprávě použít (kontrola čísel je bere
jako podložená citovaným článkem). Pevná pravidla modelu: necitovat nic
jiného, co studie zjistila brát jen z hlavního zjištění, a u nesedící
populace to uvést.

## Přidání článku

1. **Přidat článek** → vložte DOI, PMID nebo odkaz na PubMed / doi.org →
   **Doplnit údaje**. Název, autoři, časopis, rok, abstrakt a návrh úrovně
   evidence (podle typu publikace) se stáhnou z PubMedu; článek, který
   v PubMedu není, se dohledá v Crossrefu. Odchází jen DOI/PMID.
2. Doplňte **hlavní zjištění**, **omezení** a **populaci**.
3. V části **Kdy se článek použije** zaškrtněte ukazatele a testy (témata),
   případně pravidla.
4. Uložte a v seznamu **Zařaďte**. Zařazený článek bez hlavního zjištění
   aplikace ohlásí – model by znal jen jeho název.

Dohledání potřebuje internet. Na offline serveru se údaje vyplní ručně,
nebo články přijdou s katalogem: na počítači s internetem `ulozit-katalog.bat`,
na druhém počítači `nacist-katalog.bat` (na serveru `python manage.py
import_katalog`). Přenášejí se včetně témat a vazeb na pravidla.

## Do budoucna

Až bude článků stovky, dá se výběr k tématu doplnit sémantickým
vyhledáváním (embedding model, např. `nomic-embed-text` v LM Studiu).
Pravidla zůstanou stejná: jen zařazené články, jen ověřené shrnutí.
