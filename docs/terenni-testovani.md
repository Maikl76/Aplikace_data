# Terénní testování, RPE a QR kódy

Převzato z aplikace pro studii SMOS (performance-tracker), která se osvědčila
při dvouměsíčním měření v terénu.

## Zadávání u přístroje

Otevřete test v testovacím dni (**Měření → den → test**).

- **Stopky** – u ukazatelů v sekundách je v políčku ikona stopek. Start a stop
  jde i mezerníkem, **Zapsat** vloží čas do políčka.
- **Čas jako min:s** – delší časy jde psát `6:45,3`; uloží se v sekundách (405,3).
- **Pauza mezi pokusy** – má-li protokol v katalogu vyplněnou „pauzu mezi pokusy“,
  nahoře je tlačítko *Pauza 3:00*. Odpočet na konci pípne a na tabletu zavibruje.
- **Uložit a další** – uloží a otevře další test dne v pořadí baterie sportu.
- **+ přidat pokus** – další sloupec pokusu (třeba když se pokus liší a měříte
  znovu); uložené pokusy se tím neztratí.

## Kontrola hned při zadávání

Mřížka hlídá dvě věci ještě při psaní, stejnými slovy jako později krok
Kontrola:

- **rozptyl pokusů** – když se platné pokusy téhož ukazatele liší víc, než
  je mez rozptylu v katalogu (`trial_cv_limit`), napíše „Pokusy se liší
  o 16 % (mez 10 %): pokus 3 se liší o 31 % od ostatních – změřit znovu?“,
- **věrohodný rozsah** – hodnota mimo rozsah metriky se označí a mřížka
  napíše „Pokus 3 mimo věrohodný rozsah (5–80 cm) – překlep, nebo chyba
  přístroje?“.

Totéž se spočítá po uložení (hláška nahoře a text pod ukazatelem), takže
upozornění nezávisí na JavaScriptu. Neplatný pokus se do rozptylu nepočítá.

## Režim u přístroje

Pro měření skupiny s tabletem u desky: v testovacím dni tlačítko **Režim
u přístroje** (nebo odkaz *u přístroje* v Dnešním testování) otevře celou
obrazovku bez menu:

- nahoře postup baterií (hotové testy zeleně, aktuální zvýrazněný, „test 2 z 5“),
- táž mřížka pokusů, stopky a pauza, RPE po zátěžovém testu přímo pod mřížkou
  s výzvou zeptat se, než sportovec odejde,
- velká tlačítka *Uložit hodnoty* a *Uložit a další test: …*; Enter skáče na
  další políčko (číselná klávesnice tabletu nemá tabulátor),
- po posledním testu **shrnutí dne**: co má hodnoty, co chybí, nestabilní
  pokusy, hodnoty mimo rozsah, chybějící RPE, odkaz na koncept zprávy
  a tlačítko **Další sportovec** (první test bez hodnot u dalšího sportovce
  téhož dne). *Opustit režim* vrátí běžnou obrazovku s menu.

Adresy: `/mereni/provedeni/<id>/u-pristroje/` a `/mereni/<den>/u-pristroje/hotovo/`.

## Hodnota dne z pokusů

U každé metriky je v katalogu pole **hodnota dne z pokusů**:

| Pravidlo | Kdy |
|---|---|
| průměr platných pokusů | výchozí (výskoky, VALD) |
| nejlepší pokus | sprint (nejkratší čas), síla stisku, rychlost podání |
| poslední pokus | kde se testuje do selhání apod. |

Podle toho se počítá zpráva, grafy, týmový přehled i stranové rozdíly. Ve zprávě
je u takové metriky poznámka „nejlepší pokus“.

## RPE (vnímané úsilí)

Škála **CR-10** (0 = klid … 10 = maximální), Borg v úpravě Fostera.

- **Po testu** – u protokolů se zaškrtnutým „po testu zaznamenat RPE“ (Wingate,
  spiroergometrie) je škála přímo pod zadávací mřížkou.
- **Kdykoli v testovacím dni** – karta *RPE* vpravo: vyberte, po čem (test, nebo
  celý den), a buď klepněte na číslo a **Zapsat**, nebo **Vyplní sportovec (QR)**.
- **Sportovec na svém telefonu** – naskenuje QR kód a vybere číslo. Nepřihlašuje se,
  stránka neukazuje jméno ani výsledky. Odkaz platí 12 hodin. Opakované vyplnění
  přepíše předchozí odpověď.

RPE je ve zprávě u testu („RPE 9/10 (velmi těžké)“), RPE za celý den v hlavičce,
a obojí dostává i jazykový model jako kontext.

Další dotazníky (wellness, spánek…) se připraví v *Nastavení → Dotazníky*
(otázky: škála, číslo, ano/ne, výběr, text) a v testovacím dni se nabídnou
pod **Další dotazníky** – vyplní je operátor, nebo sportovec přes QR kód.

## Prostředí

V testovacím dni karta **Prostředí** – teplota a vlhkost. Jdou zadat i při
zakládání dne. Objeví se v hlavičce zprávy.

## QR karty sportovců

Na kartě sportovce ikona QR, v **Týmovém přehledu** tlačítko **QR karty** pro celou
skupinu (tisk 2 karty vedle sebe). Naskenováním karty tabletem se otevře dnešní
testovací den sportovce; když ještě není, aplikace nabídne ho založit podle baterie.

## Tablet a telefony v síti laboratoře

`spustit.bat` pouští aplikaci jen pro tento počítač (adresa 127.0.0.1) – tablet
ani telefon ji neotevřou. Pro zadávání z tabletu a RPE na telefonu spusťte místo
něj **`spustit-sit.bat`**:

1. Dvakrát klikněte na `spustit-sit.bat`.
2. V okně najděte řádek `IPv4 Address . . . : 192.168.x.x`.
3. Na tabletu otevřete `http://192.168.x.x:8000`.
4. Když se Windows zeptá na bránu firewall, povolte **jen soukromou síť**.

Tablet i telefony musí být ve stejné Wi-Fi jako počítač. Používejte jen v síti
laboratoře, ne na veřejné Wi-Fi. QR karty tiskněte z adresy `http://192.168.x.x:8000`
(ne z localhost), jinak povedou na adresu, kterou tablet nezná.

Na fakultním serveru tohle odpadá – aplikace tam poběží pod stálou adresou.
