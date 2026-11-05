# Genetika ve sportu

Modul pro panel genových variant (ACE, ACTN3, COL5A1, CYP1A2, IL6, MCM6/LCT,
SLC16A1, PPARGC1A, FTO, TCF7L2 – podle podkladů) a pro to, co z něj smí do
zprávy. Tahle fáze (kostra) řeší **obsah a data**: karty s revizí a schválením,
souhlas, vzorek a genotypy. Genetická zpráva a propojení s měřením jsou další
fáze (viz konec).

## Zásady

- **Obsah je data s verzí a historií.** Genová karta má stav *původní znění →
  návrh → v revizi → schváleno → nahrazeno/vyřazeno*. Původní znění z podkladů
  a schválené verze nikdo nepřepíše – změna je nová verze. Sporná tvrzení a co
  se má doplnit jsou revizní záznamy (původní znění, návrh, důvod, zdroj,
  rozhodnutí).
- **Schvaluje garant oblasti.** Za každou oblast (Výkon a trénink, Pohybový
  aparát, Regenerace, Kofein, Laktóza, Hmotnost a metabolický kontext) odpovídá
  metodik; jen on smí kartu své oblasti schválit, a jen bez blokujících
  nedostatků (interpretace pro každý genotyp, důvod u každého doporučení, žádný
  nepřípustný výrok).
- **Souhlas „Genetická data“ je brána ke všemu** a je jen pro dospělé (od
  18 let, podle data narození). Bez něj se genotyp neuloží; odvolání souhlasu
  genotypy smaže, vzorek zůstane jen jako záznam bez dat, vydané zprávy
  zůstávají.
- **Genotypy leží šifrovaně vlastním klíčem** (`GENETICS_ENCRYPTION_KEY`,
  jiný než klíč identity). Vidí je jen správce a laborant. Trenér genetiku
  nevidí nikdy, výzkumník vidí karty, ne genotypy. V ukázce (DEMO_MODE) se
  genotypy nezadávají.
- **Vypnutí.** Varianta jde vypnout (nikde se neukáže, genotypy zůstanou),
  z panelu jde vyřadit, karta jde vyřadit. Nic se nemaže.

## Kde co je

| Kde | Co |
|---|---|
| menu **Genetika** | průvodce nastavením (4 kroky s tlačítkem *Další krok*), přehled variant a karet s *Upravit* / *Schválit*, fronta „čeká na garanta“, garanti, panely, počet vzorků, výzkum; odkaz *Jak to funguje* |
| **Genetika → nastavení** | `/genetika/nastaveni/garanti/` (správce), `/genetika/nastaveni/karty/` (nahrání Wordu), `/genetika/nastaveni/panel/` (laboratoř, zápis genotypů, vypnutí variant) |
| **Genetika → karta** | čitelná verze karty, kontrola před schválením, tlačítka *Upravit*, *Poslat k revizi*, *Schválit*, *Vrátit k úpravě*, *Nová verze*, *Vyřadit* |
| **Genetika → karta → Upravit** | editor karty v aplikaci: biologie, texty pro genotypy, doporučení s důvody, scénáře z dotazníku, nepřípustné výroky, revizní záznamy; *Uložit a poslat k revizi* |
| **Genetika → Jak to funguje** | `/genetika/navod/`: obsah – lidé – zpráva, kdo co dělá, stav nastavení |
| **karta sportovce → Genetika** | postup v pěti krocích (souhlas → vzorek → ověření → dotazník → zpráva) s *Další krok*; zápis podepsaného souhlasu / odvolání, dotazník, vzorky, genotypy, *Ověřit příslušnost* výsledku, nový vzorek, sestavení genetické zprávy |
| **portál sportovce → Souhlasy a sdílení → Genetika** | sportovec souhlas uděluje a odvolává sám, vyplňuje dotazník; vydanou zprávu pro sportovce vidí v Mých výsledcích |
| **administrace → Genetika** (pro pokročilé) | totéž co editor plus důkazy, zdroje, interakce, podmínky scénářů nad měřením, vzorky (jen ke čtení) |

## Postup

Běžná práce se dělá v aplikaci: stránka **Genetika** vede čtyřmi kroky
nastavení, u každého říká, co chybí, a tlačítko *Další krok* otevře to, co je
na řadě. Stránka **Genetika → Jak to funguje** (`/genetika/navod/`) vysvětluje
celek (obsah – lidé – zpráva, kdo co dělá). Administrace Djanga je jen „pro
pokročilé“ (důkazy, zdroje, interakce, podmínky scénářů nad měřením); účet pro
ni potřebuje „Stav týmu“ (is_staff) a skupiny oprávnění srovná `seed_roles`
(spustit.bat i aktualizace serveru ho volají samy).

1. **Garanti oblastí** (správce; `/genetika/nastaveni/garanti/`). Ke každé
   oblasti aspoň jeden metodik z účtů správce / diagnostik. Bez garanta nejde
   karta oblasti schválit.
2. **Karty z podkladů** (správce nebo laborant; `/genetika/nastaveni/karty/`).
   Nahrajte Word s genovými kartami. Pro každou variantu vznikne verze 1
   *původní znění* (jen ke čtení) a verze 2 *návrh*; pozdější revizní texty
   z podkladů (ACTN3 v0.2, LCT) jsou rovnou v návrhu a rozdíl je zapsaný
   v revizních záznamech. Karty bez původního obsahu (SLC16A1, FTO, TCF7L2)
   vzniknou jako návrh s úkoly k doplnění. Zároveň vznikne panel „Panel
   variant z podkladů“. Varianty, které v katalogu už jsou, se nepřepíší.
   Ve veřejné ukázce (DEMO_MODE) je nahrávání vypnuté. Totéž umí příkaz:

       python manage.py nacist_genove_karty "C:\cesta\01_Genove_karty_plne_zneni_v02.docx"

3. **Panel a laboratoř** (`/genetika/nastaveni/panel/`). Která laboratoř
   genotypizuje; u každé varianty *Použít* (vypnutá varianta zmizí ze zpráv,
   uložené genotypy zůstanou) a zápis laboratoře ve tvaru `RR=CC, RX=CT, XX=TT`
   (předvyplněno z jiných zápisů varianty). Aplikace zápis nikdy nehádá: co
   nejde převést, uloží jako *nejasný zápis*. Není-li žádný panel, vznikne
   „Panel laboratoře“ se všemi variantami.
4. **Revize a schválení.** V tabulce karet otevře *Upravit* editor karty
   v aplikaci (`/genetika/karta/<id>/upravit/`): co gen dělá, text pro každý
   genotyp, doporučení s *důvodem* (doložená interpretace varianty / dotazník
   / obecný postup / budoucí měření – bez důvodu kartu nejde schválit),
   scénáře z dotazníku (zapnout jde jen s odpovědí, která je spouští; scénář
   s měřením jen s podmínkou z administrace), nepřípustné výroky (jeden na
   řádek) a rozhodnutí revizních záznamů. *Uložit a poslat k revizi* předá
   kartu garantovi; ten ji na stránce karty *schválí*, jen když kontrola před
   schválením nic neblokuje. Schválené znění je neměnné; *Nová verze* otevře
   rovnou editor nové verze.
5. **U sportovce** (karta sportovce → Genetika) vede postup pěti kroky:
   souhlas (v portálu, nebo laboratoř zapíše převzatý podepsaný) → vzorek
   a výsledek (opsané genotypy) → ověření příslušnosti (výsledek patří tomuto
   sportovci) → dotazník → zpráva. *Další krok* skočí na to, co je na řadě.
   Do zprávy jde jen ověřený vzorek.

## Klíč

`python manage.py zajisti_klic` doplní do `.env` i `GENETICS_ENCRYPTION_KEY`
(spustit.bat ho volá při každém startu). Klíč se nesmí měnit ani ztratit –
zálohujte ho spolu s databází, stejně jako klíč jmen.

## Přenos katalogu

Oblasti, varianty, panely, karty (včetně verzí, stavů a revizních záznamů)
a interakce se přenáší s katalogem (`ulozit-katalog.bat` / `nacist-katalog.bat`).
Garanti jsou účty a nepřenáší se; vzorky a genotypy do katalogu nepatří
nikdy. Načtení nahradí obsah karty se stejnou variantou a verzí obsahem ze
souboru.

## Dotazník ke genetickému vyšetření

Sdílený dotazník `genetika` (Katalog → Dotazníky) vzniká ze seedu podle osnovy
podkladů: osm oddílů (profil a cíle, trénink a výkon, pohybový aparát,
regenerace, kofein, laktóza a výživa, hmotnost a metabolický kontext,
dostupnost dalších informací). Není to validovaný formulář – laboratoř ho
dokončí v administraci; seed existující otázky nepřepisuje.

- Otázky mají druh (škála, číslo, ano/ne, jedna nebo více možností, text)
  a mohou nabízet **nevím** a **netýká se**. Tyto stavy jsou plnohodnotné
  odpovědi a nikdy se nepřekládají na „ne“.
- Vyplňuje ho sportovec v portálu (Souhlasy a sdílení → Genetika, až po
  udělení souhlasu), nebo laboratoř na kartě sportovce → Genetika →
  Dotazník (s volbou, zda odpovědi dával sportovec sám). Každé vyplnění je
  nový záznam; zpráva bere nejnovější.
- **Scénáře karet** („Výstup odpovědi: …“) se napojují na otázku a odpověď
  (v editoru karty volba *spouští odpověď…*; v administraci pole *otázka* a *shoda odpovědi*, např.
  `{"choices": ["vytrvalost"]}`). Převod z Wordu napojí ty, jejichž znění
  je známé; zapnout je (*aktivní*) může až garant po revizi. Scénáře
  s měřením zůstávají vypnuté – měření genotyp nepotvrzuje.

## Genetická zpráva

Sestavuje se na kartě sportovce → Genetika → *Sestavit koncept*, jen
z **ověřeného vzorku** a jen **pro sportovce nebo pro lékaře** (trenér
genetickou zprávu nedostává nikdy). Číslo zprávy má řadu `FTG-rok-číslo`.
Dál se chová jako ostatní zprávy: koncept → vydání (nevratné, PDF a strojová
příloha) → nová verze.

Obsah je deterministický a v pořadí podle podkladů:

1. **Cíl klienta a dostupné podklady** – z dotazníku (sport, zaměření, cíl),
   panel, vzorek, zda je dotazník vyplněn.
2. **Přehled zjištěných genotypů** – gen, oblast, genotyp, kvalita zápisu,
   verze karty. Vypnuté varianty se neuvádějí.
3. **Výsledky podle oblastí** – u každé varianty text pro zjištěný genotyp
   **doslova ze schválené verze karty** (pro lékaře odborné znění a důkazy),
   kontext z dotazníku jen z aktivních scénářů, které odpověď skutečně
   spouští, a doporučení s důvodem.
4. **Praktická doporučení a jejich důvody** – sloučená napříč kartami podle
   *klíče pro slučování*: stejný text = jedno doporučení s více důvody;
   různé texty pod jedním klíčem = **k odbornému posouzení** (zpráva nic
   nevybírá). Komentář diagnostika patří sem.
5. **Co by bylo vhodné doplnit nebo změřit** – doporučení s důvodem
   „budoucí měření“; když má doporučení přiřazený test, zpráva řekne, zda
   sportovec má výsledek z posledního roku (uvede hodnoty klíčových
   ukazatelů bez výkladu), nebo že chybí.
6. **Omezení interpretace a zdroje** – varianty bez interpretace s důvodem
   (chybějící nebo nejasný výsledek, neschválená karta, karta bez textu pro
   genotyp), pevná omezení, omezení karet, zdroje karet číslované [n], verze
   karet a dotazníku.

Souhrn na začátku je **spojovací**: bez modelu ho složí šablona; se
zapnutým modelem ho napíše model z faktů, které obsahují jen schválené
texty, sloučená doporučení a cíl klienta. Text se kontroluje proti
nepřípustným výrokům (globálním i z karet) a proti číslům – co neprojde,
se nahradí šablonou a důvod je v Doložitelnosti. Totéž hlídá text
diagnostika: souhrn ani komentář s nepřípustným výrokem zprávu nepustí
k vydání. Návrh doporučení modelem genetická zpráva nenabízí.

Při vydání se obsah zmrazí do snímku (verze karet jsou v Doložitelnosti);
pozdější změna karty vydanou zprávu nemění, nová verze zprávy bere nové
znění. Vydaná zpráva zůstává i po odvolání souhlasu; nový koncept bez
souhlasu nejde.

## Propojení s měřením

Zásada: **měření mluví první, genotyp je kontext.** Zpráva měření nikdy
nepopisuje jako potvrzení nebo vysvětlení genotypu.

- **Ukazatele oblasti.** Každá oblast má v administraci (Genetika → Oblasti)
  seznam ukazatelů z katalogu (*ukazatele oblasti*); seed doplní výchozí
  výběr jen do oblasti bez ukazatelů. V části 3 genetické zprávy je u každé
  oblasti **před genotypem** tabulka měření: poslední hodnota z posledního
  roku, norma slovy (stejně jako ve zprávě z měření) a změna proti minulému
  měření posouzená podle MDC. Vypne se volbou *ukázat měření ve zprávě*.
- **Únava a RPE.** Oblast se zapnutým *sledovat únavu a RPE* (výchozí
  Regenerace) ukáže subjektivní únavu z testovacích dnů a RPE po testech –
  jak je sportovec uvedl, bez výkladu.
- **Scénáře s měřením.** Scénář karty druhu *měření* má podmínku ve stejném
  zápisu jako pravidla (např. `{"z": "vo2max", "op": ">", "value": 1}`);
  vyhodnocuje se nad posledním testovacím dnem sportovce. Zapíná ho garant;
  ve zprávě je označený „z měření <datum>“. Špatně zapsaná podmínka se
  neuloží.
- **Pokus s kofeinem.** U provedení testu (stránka zadávání → *Podmínky
  provedení*) se zapíše dávka kofeinu v mg/kg (podmínka `kofein_mg_kg`).
  Zpráva takové provedení porovná s nejbližším provedením téhož testu bez
  kofeinu (klíčové ukazatele testu, rozdíl posouzený podle MDC) v části 3
  jako „Pokus s kofeinem“ – s poznámkou, že rozdíl mezi dvěma dny má i jiné
  příčiny a genotyp CYP1A2 ho nevysvětluje.
- **Souvislost ve zprávě z měření.** Zpráva z funkčního testování pro
  sportovce nebo pro lékaře dostane část *7. Souvislost s genetickým
  vyšetřením* – číslo a datum vydané genetické zprávy pro téhož čtenáře
  a zjištěné genotypy interpretovaných variant, s větou, že měření má
  přednost. Bez vydané genetické zprávy, bez platného souhlasu nebo pro
  trenéra se část neobjeví. Při vydání se zmrazí do snímku.
- Jazykový model dostane měření, únavu i pokus s kofeinem ve faktech
  (čísla z nich smí použít), s pravidlem uvádět je jen jako aktuální stav.

## Výzkum: anonymizovaný export a vlastní frekvence

Stránka Genetika (správce, laborant, výzkumník) nabízí **anonymizovaný
export** (ZIP) a **frekvence genotypů v populaci laboratoře**. Do obojího
vstupují jen sportovci s platným souhlasem **se sekundárním použitím pro
výzkum** a zároveň **s genetickými daty** a s ověřeným vzorkem.

- Export obsahuje `sportovci.csv` (pohlaví, věkové pásmo, sport, úroveň),
  `genotypy.csv` (z posledního ověřeného vzorku, jen aktivní varianty),
  `mereni.csv` (hodnoty dne všech klíčových ukazatelů po měsících,
  subjektivní únava), `dotaznik.csv` (jen volby a čísla, žádný volný text)
  a `README.txt` s popisem sloupců a podmínkami.
- Osoba má stálý identifikátor bez vazby na kód (hash odvozený tajným
  klíčem instance); kód ani jméno se neexportují, data jsou jen po měsících.
- Export se vydá **od 5 osob**; každé stažení je v auditu. Na offline
  serveru ho uloží `python manage.py vyzkumny_export --cil soubor.zip`.
- Frekvence se ukážou u varianty od 5 výsledků. Frekvence není mírou
  výhodnosti genotypu; karty dál uvádějí frekvence z literatury se zdrojem.
