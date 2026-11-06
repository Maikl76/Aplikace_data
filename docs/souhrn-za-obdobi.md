# Souhrnná zpráva za období a plnění doporučení

## Souhrn za období

Zpráva z jednoho testovacího dne odpovídá na „jak dopadlo tohle měření“.
Souhrn za období (`Report.Kind.PERIOD`, `apps/reports/period.py`) odpovídá
na „kam se to za půl roku posunulo“:

- vzniká z karty sportovce: *Zprávy → Souhrnná zpráva za období* (od, do, pro
  koho); potřebuje aspoň dvě měření s hodnotami v období,
- **klíčové ukazatele za období**: první a poslední hodnota v období, změna
  a posouzení proti MDC (stejná slova jako u změny proti minule), nejlepší
  hodnota v období, cíl,
- **hodnoty po měřeních** (ukazatel × den), **grafy vývoje** s čarou cíle
  a začátkem sezóny, **cíle**,
- **doporučení v období**: doporučení z vydaných zpráv z měření v období
  (přednostně pro téhož čtenáře) a jak se plnila,
- souhrn napíše šablona (`period.compose`), nebo jazykový model
  (`period.compose_report`) z faktů `period.facts` – se stejnou kontrolou
  čísel jako zpráva z měření; pokyny přidávají poznámku, že jde o období.

Vydání, upozornění e‑mailem, otevření v portálu, nová verze i předání
fungují jako u ostatních zpráv; vydaná zpráva drží snímek HTML. Pravidla se
v souhrnu znovu nevyhodnocují – nálezy patří k testovacím dnům.

## Plnění doporučení z minulé zprávy

Uzavřená smyčka (`apps/reports/followup.py`, model `RecommendationReview`):

1. Při dalším testovacím dni najde aplikace **poslední vydanou zprávu**
   sportovce před tímto dnem, která má doporučení (z pravidel v snímku při
   vydání, nebo komentář diagnostika).
2. V testovacím dni je karta *Doporučení z minulé zprávy* a krok
   *Doporučení z minula*: u každého doporučení jedním klikem **plnilo se /
   částečně / neplnilo se / nelze říct** a nepovinná poznámka. Posouzení
   patří k tomuto dni; při další zprávě se dá změnit.
3. Nová zpráva z toho dne na to naváže: fakta pro model mají pole
   `doporuceni_z_minula` (text, plnění, poznámka), souhrn ze šablony je
   vypíše a ve zprávě je tabulka *Plnění doporučení z minulé zprávy*.
   Souhrn za období shrne doporučení všech zpráv v období s plněním.
4. Trenér i sportovec vidí v portálu u *Doporučení z poslední zprávy*
   pro sebe, jak se plnila (posouzení z pozdějšího dne).

Neposouzené doporučení zůstává „neposouzeno“ – model o něm nic netvrdí.
