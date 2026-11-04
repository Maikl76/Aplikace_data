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
| menu **Genetika** | přehled variant, schválených a rozpracovaných karet, fronta „čeká na garanta“, garanti, panely, počet vzorků |
| **Genetika → karta** | čitelná verze karty, kontrola před schválením, tlačítka *Poslat k revizi*, *Schválit*, *Vrátit k úpravě*, *Nová verze*, *Vyřadit*; odkaz na úpravu v administraci |
| **karta sportovce → Genetika** | souhlas (zápis podepsaného souhlasu / odvolání), vzorky, genotypy, *Ověřit příslušnost* výsledku, nový vzorek |
| **portál sportovce → Souhlasy a sdílení → Genetika** | sportovec souhlas uděluje a odvolává sám |
| **administrace → Genetika** | oblasti a garanti, varianty, panely, karty (texty, doporučení, důkazy, zdroje, nepřípustné výroky, scénáře, revizní záznamy), interakce, vzorky (jen ke čtení) |

## Postup

1. **Garanti.** Správce v administraci (Genetika → Oblasti) přiřadí ke každé
   oblasti metodika. Bez garanta nejde karta oblasti schválit.
2. **Karty z podkladů.** Na počítači s databází:

       python manage.py nacist_genove_karty "C:\cesta\01_Genove_karty_plne_zneni_v02.docx"

   Pro každou variantu vznikne verze 1 *původní znění* (jen ke čtení) a verze 2
   *návrh*; pozdější revizní texty z podkladů (ACTN3 v0.2, LCT) jsou rovnou
   v návrhu a rozdíl je zapsaný v revizních záznamech. Karty bez původního
   obsahu (SLC16A1, FTO, TCF7L2) vzniknou jako návrh s úkoly k doplnění.
   Zároveň vznikne panel „Panel variant z podkladů“ se všemi variantami.
   Varianty, které už v katalogu jsou, příkaz nechá být.
3. **Revize.** Návrh se upravuje v administraci (odkaz z karty). Kontrola
   před schválením na stránce karty říká, co chybí. Doporučení musí mít
   *důvod* (doložená interpretace varianty / dotazník / obecný postup / budoucí
   měření); měření genotyp nepotvrzuje, scénáře s měřením zůstávají vypnuté.
4. **Schválení.** Autor pošle kartu *k revizi*; garant oblasti ji *schválí*.
   Tím se stane jediným zněním, které smí do zpráv; předchozí schválená verze
   je *nahrazena*. Další změna = *Nová verze* a znovu revize.
5. **Panel a laboratoř.** V administraci (Genetika → Panely) doplňte
   laboratoř a u každé varianty, jak laboratoř genotyp píše (převod zápisu,
   např. `{"RR": "CC"}`). Aplikace zápis nikdy nehádá: co nejde převést, uloží
   jako *nejasný zápis*.
6. **Souhlas a vzorek.** Sportovec dá souhlas v portálu, nebo laboratoř zapíše
   převzatý podepsaný souhlas na kartě sportovce → Genetika. Laboratoř založí
   vzorek a opíše genotypy z výsledku; diagnostik pak *ověří příslušnost*
   (výsledek patří tomuto sportovci). Do zprávy jde jen ověřený vzorek.

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

## Co je další fáze

- dotazník genetiky (typy otázek, stavy *nevím / netýká se / chybí*),
- genetická zpráva: text pro genotyp jen doslova ze schválené karty, sloučení
  doporučení, „co doplnit nebo změřit“ podle historie sportovce, snímek verzí
  karet; jazykový model píše nanejvýš spojovací souhrn,
- propojení s měřením (měření mluví první, genotyp je kontext), pokus
  s kofeinem přes podmínky testu, kombinovaná zpráva,
- výzkumný export (anonymizovaně, se souhlasem s výzkumem).
