# Srovnání v čase, cíle a popisy pro klienta

Zpráva, karta sportovce i portál dřív srovnávaly jen s minulým měřením
(proti MDC) a s normou. Od dávky „srovnání a cíle“ umí víc.

## Od začátku sezóny, osobní maximum, za 12 měsíců

Ke každé řadě klíčového ukazatele (hodnota dne, celek / obě strany) se
dopočítá (`apps/analytics/compare.py`):

- **od začátku sezóny** – změna proti prvnímu měření v této sezóně. Sezóna
  začíná měsícem nastaveným u sportu (Nastavení → Sporty a baterie →
  *Sezóna začíná*); bez nastavení lednem. Je-li poslední měření v sezóně
  jediné, píše se „první měření v sezóně“;
- **osobní maximum** (u ukazatelů, kde je lepší nižší hodnota, *rekord*) –
  nejlepší hodnota řady; poslední měření je „nové maximum“, „na úrovni
  maxima“ (rozdíl pod MDC), nebo „o X pod maximem“;
- **za 12 měsíců** – změna proti nejstaršímu měření v posledním roce,
  v jednotkách i v procentech, a počet měření za tu dobu.

Posouzení je vždy proti MDC, stejnými slovy jako změna proti minule. Bez
MDC se o zlepšení nemluví. Ukazuje se na dlaždicích (karta sportovce,
portál sportovce i trenéra), ve zprávě (tabulka *Vývoj v čase* a fakta pro
jazykový model: `od_zacatku_sezony`, `osobni_maximum`, `za_12_mesicu`)
a v grafech (tečkovaná čára začátku sezóny).

## Cíle

Diagnostik na kartě sportovce (*Cíle → Nastavit cíl*) zadá klíčový
ukazatel, cílovou hodnotu, dokdy a poznámku (např. s kým je cíl domluvený).
Výchozím bodem postupu je poslední naměřená hodnota. Jeden ukazatel má
nejvýš jeden platný cíl; zrušený cíl zůstává v databázi jako neplatný.

Postup (`apps/subjects/goals.py`) se počítá nad touž řadou jako dlaždice:

| stav | kdy |
|---|---|
| splněno | aktuální hodnota dosáhla cíle (datum prvního splnění se pamatuje) |
| v dosahu | zbývá méně než MDC – cíl je prakticky splněn |
| po termínu | termín prošel a cíl není splněn |
| zbývá X | jinak; ve zprávě „zbývá více než chyba měření“ |

Kde se cíl ukazuje: dlaždice a sekce *Cíle* na kartě sportovce, portál
sportovce i trenéra (jen ke čtení), čárkovaná čára v grafech vývoje,
ve zprávě tabulka *Cíle* a fakta `cile` (model o cíli píše jen to, co říká
pole `posouzeni`). Vydaná zpráva drží stav k datu měření.

## Popisy pro klienta

Ukazatele mají odborný název a jednotku, ale ne větu pro laika. V Nastavení
→ *Popisy pro klienta* správce doplní ke každému ukazateli větu pro
sportovce a větu pro trenéra a u testu, jak probíhá. Tlačítko *Navrhnout
chybějící modelem* nechá jazykový model navrhnout texty tam, kde chybí;
model dostane jen katalog (názvy, jednotky, směr, popis testu), žádná data
sportovců. Návrh je předvyplněný a uloží se až tlačítkem *Uložit*.

Texty se ukazují v portálu u klíčových ukazatelů (sportovec svou větu,
trenér svou), v seznamu měření (*Jak testy probíhají*) a ve vysvětlivkách
zprávy pro sportovce a trenéra (*Co ukazatele znamenají*); zpráva pro
lékaře je nemá. Portál má navíc slovníček pojmů (MDC, zlepšení, sezóna,
maximum, cíl, norma).
