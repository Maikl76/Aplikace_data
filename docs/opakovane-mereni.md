# Opakované měření: plán, Kdo je na řadě, připomínky

Dlouhodobé sledování stojí na tom, že se sportovec vrací. Aplikace proto
u každého sportovce zná termín dalšího měření, na Přehledu ukazuje, kdo je
na řadě, a umí připomenout e‑mailem. Nic se neodškrtává ručně, všechno
plyne z dat.

## Odkud se bere termín

1. **Interval u baterie testů** (Sporty a testy → baterie → *Opakování po
   N týdnech*). Platí pro všechny sportovce sportu (nebo kategorie), kteří
   nemají vlastní plán. Prázdné = bez plánu.
2. **Plán u sportovce** (karta sportovce → Testovací dny → *Plán
   opakování*): podle baterie, vlastní interval v týdnech, nebo konkrétní
   termín. Konkrétní termín má přednost; jakmile proběhne měření po něm,
   přestane platit a dál se počítá interval.
3. Termín = poslední měření s hodnotami + interval. Naplánovaný testovací
   den bez hodnot nebo objednávka čekající na schválení znamenají „už je
   domluveno“, sportovec pak na řadě není.

Stavy, které aplikace ukazuje: *do N dnů* (termín do 30 dnů), *prošlo
o N dnů*, *naplánováno*, *objednáno*, nebo termín bez zvýraznění.

## Kde se to ukazuje

- **Přehled** – karta *Kdo je na řadě* (prošlé termíny první) s tlačítkem
  *Nové měření* a volitelný krok *Na řadě* v denním postupu.
- **Sportovci** – sloupec *Další měření* a filtr *jen na řadě*.
- **Karta sportovce** – věta v kartě Testovací dny, krok *Měření* je po
  prošlém termínu znovu nehotový, tlačítko *Připomenout e‑mailem*, plán
  opakování a seznam odeslaných připomínek.
- **Portál sportovce** – *Příští měření: do …*, po prošlém termínu výzva
  a tlačítko *Objednat se* (když je objednávání zapnuté).
- **Portál trenéra** – odznak u sportovce, který je na řadě.

## Připomínky e‑mailem

Připomínka jde na uložený kontakt sportovce (Upravit údaje → e‑mail) a na
účty zákonných zástupců. Neobsahuje jméno ani výsledky, jen termín
a odkaz na objednání. Odchází nejdřív **14 dní před termínem** a při
prošlém termínu; témuž sportovci znovu nejdřív po 30 dnech.

Kdy se posílá:

- **Sama, jednou denně** – při prvním otevření Přehledu v daný den
  (laborant nebo správce). Nic není třeba nastavovat.
- **Denní údržbou** – na laboratorním počítači ji spouští `spustit.bat`
  (okno *Denni udrzba*), na PythonAnywhere plánovaná úloha (*Tasks* →
  denní úloha):

  ```
  ~/.virtualenvs/ftvs/bin/python ~/Aplikace_data/manage.py udrzba --jednou
  ```

  Připomínky jsou jedním z jejích kroků (viz `docs/provoz.md`); opakované
  spuštění nic nepošle dvakrát.
- **Příkazem `pripomenout_mereni`** samostatně, např. pro zkoušku. Volby:
  `--jen-vypsat` (jen vypíše, komu by šla), `--dny 21` (jiný předstih),
  `--odkaz https://…` (adresa aplikace do odkazu na objednání; výchozí je
  `PUBLIC_BASE_URL` z `.env`).
- **Ručně** z karty sportovce tlačítkem *Připomenout e‑mailem*.

Bez poštovního serveru (`EMAIL_HOST` v `.env`, viz
[objednávky](objednavky.md)) se nic neposílá; *Kdo je na řadě* funguje
i tak a termín předáte sami.

## Ochrana údajů

Záznam o připomínce (`RetestReminder`) nese jen datum, termín a počet
adres, ne adresy samotné. E‑mail neobsahuje jméno, kód ani výsledky.
Odeslání ruční připomínky je v auditu.
