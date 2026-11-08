# Import z VALD (ForceDecks, HumanTrak)

## Jak na to

1. Ve VALD Hubu vyexportujte výsledky: **ForceDecks → Test Results Export**
   (varianta „Results from all trials“, jeden řádek na pokus), u HumanTraku
   běžný export testů. Formát xlsx i csv.
2. V aplikaci **Import** → vyberte jeden nebo víc souborů → *Načíst
   a zkontrolovat*. Formát se pozná sám.
3. Na obrazovce kontroly zkontrolujte **sportovce v souboru** (kdo je nový,
   podle čeho se kdo poznal) a **hodnoty mimo věrohodný rozsah**.
4. *Uložit do databáze*.

Co se stane při uložení:

- každý test (sportovec + typ + čas) se uloží jako jedno provedení protokolu
  se všemi pokusy; bilaterální metriky i s levou a pravou stranou,
- testovací den vznikne podle data testu,
- nový sportovec dostane kód `FTVS-xxxx`; jméno se uloží do šifrované
  identity, rok narození a pohlaví do karty,
- aplikace si zapamatuje jeho **ID ve VALD** – příště ho pozná sama, i když
  se jméno napíše jinak. HumanTrak ID nemá, tam se páruje podle jména
  (bez ohledu na diakritiku); dva lidé se stejným jménem se naslepo
  nespárují, aplikace na to upozorní.

## Sledovaná složka

Nahrávání odpadne, když aplikace složku s exporty hlídá sama:

1. Ve VALD Hubu nastavte, kam se exporty ukládají (nebo je ukládejte do
   jedné složky ručně).
2. Do `.env` na počítači laboratoře doplňte `IMPORT_WATCH_DIR=` a cestu
   k té složce (např. `C:\Users\laborator\Documents\VALD exporty`);
   `IMPORT_WATCH_INTERVAL` je interval kontroly v sekundách (výchozí 30).
3. Spusťte aplikaci přes `spustit.bat` – otevře se navíc minimalizované okno
   „Sledovana slozka“ (`python manage.py hlidat_slozku`). Zavřením okna hlídání
   skončí, aplikace běží dál.

Co hlídač dělá s novým souborem (`apps/ingest/watch.py`):

- načte ho do Importu stejně jako ruční nahrání (nic se nezapisuje bez kontroly),
- když aplikace **všechny sportovce ze souboru jednoznačně pozná** (ID ve
  VALD, nebo jméno v jiném pořadí u někoho s naplánovaným testováním) a každý
  má na datum testu **naplánovaný testovací den** (Dnešní testování), import
  rovnou **uloží**; hodnoty mimo rozsah se uloží označené jako jindy,
- jinak import **čeká na kontrolu** v Importu – nepoznaný sportovec, neznámý
  ukazatel, hodnoty bez data, nenaplánovaný den,
- soubor, který už byl importován, přeskočí; nerozpoznaný formát ohlásí
  jednou a víc se o něj nepokouší; rozepsaný soubor (mladší než 5 s) nechá
  na příští kontrolu.

Soubory se nikam nepřesouvají ani nemažou – složka patří přístroji. Co se
s kterým souborem stalo, je v Importu v kartě **Sledovaná složka** (uloženo
samo / čeká na kontrolu / přeskočeno / nešlo načíst) a v auditu pod účtem
„Sledovaná složka“. Karta také ukazuje, zda hlídač běží (poslední kontrola).
Ruční kontrola jednou: `python manage.py hlidat_slozku --jednou`.

## Když aplikace sportovce nepozná

Typicky nový klient z objednávky, kterého VALD zná pod jinak napsaným jménem
(„Nováková Jana“ × „Jana Nováková“, překlep). V náhledu importu je u každého
sportovce ze souboru výběr **Patří k**:

- nabízejí se ti, kdo mají ve dnech ze souboru naplánované testování
  (Dnešní testování, schválená objednávka);
- stejná jména v jiném pořadí aplikace navrhne sama (s poznámkou „zkontrolujte“);
- „nový sportovec“ ho založí.

Po uložení si aplikace ID z VALD zapamatuje a příště sportovce pozná sama.

Export jde nahrát i přímo z testovacího dne (tlačítko **Nahrát export
z přístroje**) – v náhledu se pak předvybere sportovec toho dne. Datum se bere
z exportu, takže hodnoty se zapíšou do naplánovaných testů jen tehdy, když
datum v exportu sedí s datem testovacího dne.

## Z testovacího dne a za celou skupinu

Export nemusíte nahrávat přes menu Import:

- **V testovacím dni** tlačítko *Nahrát export z přístroje* nahraje soubor
  a náhled předvybere tohoto sportovce. Po uložení se aplikace vrátí do
  testovacího dne.
- **Na stránce testu** tlačítko *Nahrát export k tomuto testu*: hodnoty se
  zapíší přesně do tohoto provedení (záleží na tom u opakovaného měření
  téhož testu v jednom dni), řádky bez typu testu se berou jako tento test
  a náhled upozorní, když soubor nese i jiné testy – ty se zapíší ke svým
  testům téhož dne. Po uložení se aplikace vrátí na test. Tlačítko je jen
  u testů, které aplikace umí z exportu načíst.
- **U každého testu** v detailu dne i na stránce testu je napsáno, z čeho
  ho aplikace umí načíst (*import: VALD ForceDecks*), nebo že je *jen na
  ruční zadání*; pak buď zadáte hodnoty ručně, nebo přidáte přístroj
  průvodcem (`docs/novy-pristroj.md`).
- **V Dnešním testování** tlačítko *Nahrát export za skupinu* (pod tabulkou)
  nahraje jeden export pro celou skupinu. V náhledu jsou sportovci skupiny
  v nabídce přiřazení první – i ti, kdo ten den založený nemají –, řádky
  bez data se zapíší k vybranému dni a hodnoty se doplní do založených
  testů. Po uložení se aplikace vrátí do Dnešního testování stejného dne
  a skupiny.

V obou případech náhled říká, odkud se nahrávalo; sportovce, které aplikace
nepozná, přiřadíte stejně jako jindy.

## Opakované nahrání

- **Stejný soubor** podruhé aplikace odmítne.
- **Nový export se stejnými testy** nic nezdvojí: chybějící hodnoty doplní
  a hodnoty, které VALD mezitím přepočítal, aktualizuje.
- **Doplnili jste metriku do profilu importu?** V historii importů u souboru
  klikněte na *načíst znovu* – nová metrika se dopočítá zpětně.

## Víc testů téhož dne

Když se test ten den opakoval (např. před zátěží a po ní), **hodnotou dne je
první měření** – z něj se počítají trendy, pravidla a srovnání s minulým
testováním. Opakovaná měření jsou ve zprávě v tabulce vedle prvního
i s rozdílem. V administraci lze u provedení protokolu přepnout, které
měření je „hlavní“.

## Co se importuje

Určují to **profily importu** (Katalog → Profily importu): typ testu
z exportu → protokol, sloupec → metrika. Výchozí sada:

| Test | Sloupce |
|---|---|
| Countermovement Jump | Jump Height (Imp-Mom), RSI-modified (Imp-Mom), Concentric Peak Force (+ L/P), Peak Power / BM, Countermovement Depth, Contraction Time, Eccentric Braking RFD (+ L/P), Peak Landing Force (+ L/P), Body Weight |
| Isometric Mid-Thigh Pull | Peak Vertical Force (+ L/P), Peak Vertical Force / BM, Force at 100/200 ms (+ L/P), RFD 100/200 ms (+ L/P), Start Time to Peak Force |
| Single Leg Stand | Area of CoP Ellipse, Total Excursion, Mean Velocity – strana podle pokusu |
| Box Lift – Overhead (HumanTrak) | 10 úhlů (kyčel, koleno, rameno, trup, páteř); opakování a zátěž boxu jako podmínky testu |

Výška výskoku je **z impulzu (Imp-Mom)**, ne z doby letu – metody se liší
o několik cm a nesmí se míchat.

U sloupce stačí zadat souhrnný název, např. `Concentric Peak Force [N]`;
varianty `(Left)` a `(Right)` se najdou samy. Pole *násobek* převádí
hodnotu (hloubka protipohybu je v exportu záporná → −1). U časů vypněte
*i levá a pravá strana* – rozdíl stran tam nic neříká.

Profily se přenášejí s katalogem (`ulozit-katalog.bat`).

Jiný přístroj než VALD (DEXA, InBody…) se přidává průvodcem, viz
[novy-pristroj.md](novy-pristroj.md).

## Jména a ochrana údajů

Jména se ukládají šifrovaně a jen když je v `.env` šifrovací klíč
(`IDENTITY_ENCRYPTION_KEY`). `spustit.bat` a `zalozit.bat` ho doplní samy.
**Klíč zálohujte spolu s databází** – bez něj uložená jména nejdou přečíst.

Skutečná data sportovců patří na laboratorní počítač nebo fakultní server,
ne na domácí notebook ani do veřejné ukázky (tam je nahrávání vypnuté).
