# Baterie testů a Týmové testování

## Baterie testů (Sporty a testy)

Pro každý sport určíte, které testy se měří a v jakém pořadí. Baterie může
být i pro **kategorii** (např. hokej – dorost); sportovec s touto kategorií
dostane ji, ostatní baterii celého sportu. Kategorie se nastavuje u
sportovce (úprava údajů).

- **Přidat test:** výběr pod baterií → Přidat.
- **Pořadí:** šipky ↑ ↓.
- **Odebrat:** ✕. Naměřená data zůstanou, změní se jen to, co se nabízí příště.
- Nový sport dostane rovnou prázdnou baterii.
- **Smazat sport** (odkaz u sportu; správce nebo účet se všemi sporty): nejdřív
  stránka s tím, co se smaže s ním – baterie, týmy, normy a pravidla platná jen
  pro tento sport, odkaz u článků a sport v rozsahu dat účtů (účet, který by
  pak neviděl nikoho, jmenuje). Sport se **sportovci** (i neaktivními) smazat
  nejde – sportovce převeďte do jiného sportu, nebo sport nechte; stejně tak,
  když pravidla sportu už vytvořila nálezy ve zprávách. Naměřená data se
  nemažou nikdy; smazání jde do auditu.

Baterie se přenáší s katalogem (`ulozit-katalog.bat` / `nacist-katalog.bat`).

## Individuální testování (nový testovací den jednoho sportovce)

V menu nad Týmovým testováním, tlačítkem vpravo nahoře, nebo *Nové měření*
na kartě sportovce (`apps/measurements/session_setup.py`).

Po výběru sportovce se ukáže:

- **kdo to je:** sport, kategorie, tým; poslední testovací den a jeho testy,
  plán dalšího měření;
- **upozornění:** platné **omezení zátěže** od lékaře (z externího vyšetření,
  plné omezení červeně), chybějící souhlas s funkčním testováním, sportovec
  bez sportu, a že ve zvolený den už testovací den má – pak se nový nezaloží,
  zaškrtnuté testy se jen doplní do existujícího.

**Sada testů** předvyplní testy a jejich pořadí:

| volba | co zaškrtne |
|---|---|
| baterie sportu (ta, která sportovci patří podle kategorie, je první) | testy baterie v jejím pořadí |
| jiná baterie téhož sportu | třeba obecná místo kategorie |
| stejné testy jako minule | testy posledního testovacího dne před zvoleným datem |
| bez předvyplnění | nic, testy vyberete sami |
| baterie jiných sportů | host z jiného sportu |

Testy sady jsou nahoře s pořadovým číslem; pod nimi ostatní testy katalogu
pracoviště po rodinách (force plate, dynamometrie…), u každého přístroj,
počet pokusů a RPE. Zaškrtnutí jde libovolně upravit. Nabízejí se jen aktivní
testy sdílené nebo vlastní tohoto pracoviště (ne cizí); odvozené ukazatele
(DSI, EUR) se neměří, dopočítají se. Vypnutý test v baterii formulář jmenuje.

Testovací den si zapamatuje, **podle které baterie vznikl** – její pořadí
pak platí při zadávání, v režimu u přístroje i v Týmovém testování. Den
založený podle jiné baterie, než jaká sportovci patří, to má v záhlaví.
Platné omezení zátěže je vidět i v testovacím dni.

**Zopakovat poslední den** (karta sportovce, nebo *Zopakovat dnes* v detailu
minulého dne) založí dnešní testovací den se stejnými testy, jaké měl ten
minulý – i s testy mimo baterii; přenese se místo a fáze sezóny, hodnoty
ne. Když dnešní den už existuje, jen se do něj doplní chybějící testy.
Hodí se, když se sportovec vrací na kontrolu a má se měřit totéž.

## Týmové testování

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

Tlačítko **Přehled na týden** v Týmovém testování (a proužek *Tento týden*
na Přehledu) ukáže týden den po dni:

- **testovací dny po skupinách** (baterie) s počty hotovo / rozpracováno /
  čeká a jmény; odkaz vede do Týmového testování toho dne a skupiny,
- **objednávky** na termíny v týdnu (schválené i čekající na schválení) –
  jen s přístupem k objednávkám,
- **termíny dalšího měření** podle plánu opakování, které padnou do týdne,
  s tlačítkem *Nové měření*; nad týdnem upozornění na prošlé termíny,
- **dny s hodnotami bez zprávy** s odkazem do detailu dne.

Listuje se po týdnech (nebo zadáte kterýkoli den týdne). Nic se tu
nezadává – plánuje se v Týmovém testování a v Objednávkách.

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
