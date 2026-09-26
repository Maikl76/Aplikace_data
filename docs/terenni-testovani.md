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

Další dotazníky (wellness, spánek…) se přidají v administraci
(*Katalog → Dotazníky*) – zatím se ale v aplikaci nabízí jen RPE.

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
