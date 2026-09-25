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

## Jména a ochrana údajů

Jména se ukládají šifrovaně a jen když je v `.env` šifrovací klíč
(`IDENTITY_ENCRYPTION_KEY`). `spustit.bat` a `zalozit.bat` ho doplní samy.
**Klíč zálohujte spolu s databází** – bez něj uložená jména nejdou přečíst.

Skutečná data sportovců patří na laboratorní počítač nebo fakultní server,
ne na domácí notebook ani do veřejné ukázky (tam je nahrávání vypnuté).
