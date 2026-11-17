# Výchozí měření, MDC z vlastních dat a semafor připravenosti

Tři pomůcky pro vyhodnocení opakovaných měření jednotlivce i skupiny. Drží
se postupu aplikace: klienti → měření → vyhodnocení → doporučení. Všechno
se posuzuje proti MDC (nejmenší detekovatelné změně) – bez ní aplikace
o zlepšení ani zhoršení nemluví.

## Výchozí měření

Den, ke kterému se vztahují další měření: začátek studie, den před
soustředěním, první měření po návratu ze zranění. Změna proti němu se
posuzuje stejně jako změna proti minule – proti MDC ukazatele
(`apps/analytics/baseline.py`, srovnání v `apps/analytics/compare.py`).

Kde se nastaví:

- **u sportovce** – karta sportovce → *Testovací dny* → *Výchozí měření*:
  testovací den s hodnotami a popis (např. „začátek studie“); tamtéž se
  zruší. Nebo přímo v testovacím dni tlačítkem *Nastavit tento den jako
  výchozí měření*;
- **pro celou skupinu** – *Týmový přehled* → *Výchozí měření skupiny*:
  každý sportovec dostane svůj **první měřený testovací den od zvoleného
  data**. Ve studii s víc bloky (každý blok jiné týdny) tak každý blok
  dostane svůj začátek. Kdo od data nic naměřeného nemá, zůstane beze změny.

Hodnota výchozího měření je hodnota dne z hlavního provedení testu – když
se ten den měřilo víckrát (před a po zátěži), platí první měření, stejně
jako všude jinde v aplikaci.

Kde se výchozí měření projeví:

| místo | co ukáže |
|---|---|
| dlaždice na kartě sportovce a v portálu | „proti výchozímu −4,5 cm (−11 %) · zhoršení“, u výchozího dne štítek *výchozí měření* |
| grafy vývoje (karta, portál, zpráva) | od výchozího dne čárkovaná čára a **modré pásmo výchozí ± MDC** – bod v pásmu se od výchozího neliší víc než chyba měření |
| zpráva, *Vývoj v čase* | sloupec *Proti výchozímu* (změna, %, posouzení) a vysvětlivka |
| fakta pro jazykový model | `proti_vychozimu_mereni` (datum, popis, hodnota, změna, procento, posouzení) |
| týmový přehled | volba *změna proti výchozímu měření*; CSV pak má i sloupce změny a posouzení |
| pravidla | `{"change": "…", "against": "vychozi", …}` |
| semafor připravenosti | výkon se posuzuje proti výchozímu měření (bez něj proti minulému) |

## MDC z vlastních dat

Nastavení → *MDC u ukazatelů* → u ukazatele *spočítat z dat*
(`apps/analytics/reliability.py`). Vyberete skupinu (tým, sport, nebo
všichni v rozsahu účtu), období a největší odstup měření ve dnech.

Výpočet:

1. Z každého sportovce se vezmou po sobě jdoucí měřené dny v období (nejvýš
   tolik dní od sebe, kolik je nastaveno) – každá dvojice je jeden pár.
2. Páry se seskupí podle pořadí (1. → 2. den, 2. → 3. den …) a od rozdílů
   ve skupině se odečte její průměrná změna. Systematický posun celé skupiny
   (učení, únava) není náhodná chyba měření.
3. **TE** = SD rozdílů / √2, sdružené přes skupiny párů (Hopkins 2000).
4. **MDC90** = 1,645 · √2 · TE, **MDC95** = 1,96 · √2 · TE (Weir 2005).
5. **SWC** = 0,2 × SD mezi osobami z prvního měření každého.

Stránka ukáže i TE v procentech (z logaritmů, pro orientaci), 90%
interval spolehlivosti TE (z rozdělení χ²), MDC v procentech průměru
a upozornění: málo dat, hrubý odhad (méně než 15 osob nebo 20 stupňů
volnosti; pro přesný odhad Hopkins doporučuje kolem 50 osob a aspoň tři
měření), posun skupiny jako celku. Uložení zapíše TE, MDC (90, nebo 95)
a volitelně SWC k ukazateli a do pole *zdroj* sám doplní skupinu, období,
počet osob a párů a vzorec; změna jde do auditu.

Odhad je jen tak dobrý jako výběr dat: období, kdy se skupina zlepšovala,
chybu nadhodnotí. Nejlepší je kontrolní skupina studie nebo opakované
měření v krátkém odstupu.

## Semafor připravenosti

„Jak je na tom dnes“ z toho, co se ten den změřilo a vyplnilo
(`apps/analytics/readiness.py`):

- **subjektivní signály** – odpovědi dotazníků dne za prahem nastaveným
  u otázky;
- **výkonové signály** – klíčový ukazatel testu se proti výchozímu měření
  (bez něj proti minulému) **zhoršil víc, než je MDC**. Jeden ukazatel je
  jeden signál, ať má kombinací (stran, rychlostí) kolik chce; u stran se
  bere ta horší.

Počet signálů dá barvu: **0–1 zelená, 2–3 oranžová, 4 a víc červená**.
Ukazatel bez MDC nebo bez žádoucího směru a otázka bez odpovědi (i „nevím“)
se nepočítají – nedá se o nich nic říct, a proto se ani nevydávají za
„v pořádku“. Semafor se ukáže, až když jsou posouzené **aspoň 4 ukazatele**
(jinak by nemohl být červený a „zelená“ z jediného výskoku by nic neříkala);
v praxi tedy den s vyplněným ranním dotazníkem. Semafor nehodnotí jedno číslo, ale shodu víc nezávislých
signálů. Je to pomůcka pro rozhodnutí o zátěži, ne diagnóza.

Kde je vidět: karta *Připravenost* v testovacím dni (všechny signály
s hodnotami a prahy), sloupec *Připravenost* v týmovém přehledu (poslední
testovací den každého, klepnutím na den), a přes pravidla ve zprávě.

### Ranní dotazník

Katalog má sdílený dotazník **Ranní připravenost** (`ranni`), který se
nabízí v každém testovacím dni (*Další dotazníky* → *Vyplnit* nebo QR pro
telefon sportovce):

| otázka | odpověď | signál |
|---|---|---|
| Kolik hodin jste dnes v noci spali? (`spanek_h`) | číslo, h | méně než 6 h – „málo spánku“ |
| Jak ospalý/á se teď cítíte? (`kss`) | Karolinská škála ospalosti 1–9 (Åkerstedt a Gillberg 1990) | aspoň 7 – „ospalost“ |
| Jak velkou únavu teď cítíte? (`unava`) | 0–10 | aspoň 7 – „únava“ |
| Jak velkou bolest svalů teď cítíte? (`bolest_svalu`) | 1–5 | aspoň 4 – „bolest svalů“ |

Práh signálu má každá otázka škály, čísla nebo ano/ne v Nastavení →
*Dotazníky* → otázka → *Signál do semaforu připravenosti* (operátor, práh,
signál slovy). Vlastní dotazník pracoviště tak může do semaforu přispívat
také.

### Pravidla

Pravidla mají dva nové druhy podmínky (stavitel v Nastavení → *Pravidla*
je nabízí):

    {"answer": "ranni.spanek_h", "op": "<", "value": 6}   # odpověď v dotazníku dne
    {"readiness": "*", "op": ">=", "value": 4}            # počet signálů semaforu

Pole šablon: u odpovědi `{otazka}`, `{odpoved}`, `{dotaznik}`, `{value_txt}`,
`{threshold_txt}`; u semaforu `{pocet}`, `{signaly}`, `{barva}`, `{proti}`.
Změna proti výchozímu měření (`"against": "vychozi"`) nabízí navíc
`{proti}`, `{srovnani_datum}` a `{delta_pct_txt}`.

Katalog zakládá dva **neaktivní** příklady: *semafor připravenosti červený*
(doporučí snížit objem a intenzitu a zaměřit se na regeneraci) a *oranžový*.
Zapíná je ten, kdo za prahy ručí – pro jiné sporty a skupiny mohou být
potřeba jinak.

### Odkud prahy jsou

Prahy barev (0–1 / 2–3 / 4+) i otázky vycházejí z pilotního vyhodnocení
pětidenní simulované zátěže (stresová a kontrolní skupina): v kontrolní
skupině vyšel semafor v posledních dnech zelený u 17–18 z 20 osob a nikdy
červený, ve stresové skupině byl červený u většiny. Prahy jsou výchozí,
ne norma – každé pracoviště je může v Nastavení upravit.

## Zkušební provoz

Příkaz `python manage.py ukazkova_pripravenost` (spouští ho sám
`deploy/pa-update.sh`) v ukázce (DEMO_MODE) nastaví prvním sportovcům se
třemi a víc měřenými dny výchozí měření na první z nich a k poslednímu dni
vyplní ranní dotazník **fiktivními** odpověďmi (jeden červeně, jeden
oranžově, ostatní zeleně). Kdo výchozí měření nebo dotazník už má, zůstane
beze změny. Mimo ukázku jen pro vyjmenované sportovce (`--kody`).

## Literatura

Citace ověřené v PubMed:

- Hopkins WG. Measures of reliability in sports medicine and science.
  *Sports Med* 2000;30(1):1–15. https://doi.org/10.2165/00007256-200030010-00001
- Weir JP. Quantifying test–retest reliability using the intraclass
  correlation coefficient and the SEM. *J Strength Cond Res* 2005;19(1):231–240.
  https://doi.org/10.1519/15184.1
- Åkerstedt T, Gillberg M. Subjective and objective sleepiness in the
  active individual. *Int J Neurosci* 1990;52(1–2):29–37.
  https://doi.org/10.3109/00207459008994241
