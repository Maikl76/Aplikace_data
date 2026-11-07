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

**Zopakovat poslední den** (karta sportovce, nebo *Zopakovat dnes* v detailu
minulého dne) založí dnešní testovací den se stejnými testy, jaké měl ten
minulý – i s testy mimo baterii; přenese se místo a fáze sezóny, hodnoty
ne. Když dnešní den už existuje, jen se do něj doplní chybějící testy.
Hodí se, když se sportovec vrací na kontrolu a má se měřit totéž.

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

Pod tabulkou jsou dvě akce **za celou skupinu**:

- **Export za celou skupinu** – jeden export z přístroje pro všechny. V náhledu
  importu jsou sportovci skupiny v nabídce přiřazení první (i ti, kdo ten den
  založený nemají), řádky bez data se zapíší k vybranému dni a hodnoty se
  doplní do založených testů. Po uložení se aplikace vrátí do Dnešního
  testování (z testovacího dne zase do něj).
- **Koncepty zpráv pro hotové dny** – pro každý den skupiny, který má hodnoty
  u všech testů baterie a zatím žádnou zprávu, vznikne koncept najednou (pro
  koho: podle sdílení s trenérem, nebo zvolíte). Dny, které už zprávu mají
  nebo nejsou hotové, se přeskočí a aplikace to řekne. Každý koncept pak
  zkontrolujete a vydáte jako dosud. Poslední sloupec tabulky ukazuje
  *zpráva* (odkaz) nebo *bez zprávy*.

## Přehled na týden

Tlačítko **Přehled na týden** v Dnešním testování (a proužek *Tento týden*
na Přehledu) ukáže týden den po dni:

- **testovací dny po skupinách** (baterie) s počty hotovo / rozpracováno /
  čeká a jmény; odkaz vede do Dnešního testování toho dne a skupiny,
- **objednávky** na termíny v týdnu (schválené i čekající na schválení) –
  jen s přístupem k objednávkám,
- **termíny dalšího měření** podle plánu opakování, které padnou do týdne,
  s tlačítkem *Nové měření*; nad týdnem upozornění na prošlé termíny,
- **dny s hodnotami bez zprávy** s odkazem do detailu dne.

Listuje se po týdnech (nebo zadáte kterýkoli den týdne). Nic se tu
nezadává – plánuje se v Dnešním testování a v Objednávkách.

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
