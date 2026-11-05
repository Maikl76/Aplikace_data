# Průvodci: kroky napříč aplikací

Aplikace vede uživatele kroky. Každý postup má stejný tvar: číslo nebo
fajfka, název, jedna věta co chybí, tlačítko, a vpravo nahoře *Další krok*.
Kdo se naučí jednu část, umí všechny.

## Zásady

- **Nic se neodškrtává ručně.** Stav kroku vždy plyne z dat; krok je hotový,
  když data říkají, že je hotový. Volitelný krok je označený a nebrání
  tomu, aby postup hlásil „vše hotovo“.
- **Jedna součástka.** Kroky vykresluje značka `{% steps %}`
  (`apps/core/templatetags/ui.py`, šablona `templates/core/_steps.html`);
  krok je slovník z `apps/core/steps.py` (`step(...)`, `next_step(...)`).
  Tlačítka se ukážou jen tomu, kdo smí jednat (`may_act`); krok
  `admin_only` ukáže ostatním „nastavuje správce“.
- **Připomínka u každého postupu.** Odkaz *Připomínka* v hlavičce kroků
  (a tlačítko dole v menu) otevře formulář s předvyplněnou stránkou
  a krokem. Správce připomínky vyřizuje v menu *Připomínky* s odpovědí;
  vyřízené zůstávají. Model `Remark` v `apps/core/models.py`.
- **Administrace jen pro pokročilé.** Co se dělá běžně, má být v aplikaci;
  u kroku, který ještě vede do administrace, to tlačítko říká.

## Kde kroky jsou

| Část | Kroky | Kde se počítají |
|---|---|---|
| Přehled, denní režim | kdo dnes přijde, hodnoty, kontrola (nestabilní pokusy, hodnoty mimo rozsah, chybějící RPE), zprávy (dnešní dny bez zprávy, koncepty), předání (vydané zprávy pro lékaře se souhlasem bez záznamu o předání) | `apps/core/daily.py` |
| Stav pracoviště | kolegové, sporty a baterie, testy a klíčové ukazatele, MDC, přístroje a import, normy a pravidla, objednávky, genetika, klíče a model | `apps/core/workplace.py` |
| Genetika | nastavení: garanti, karty z Wordu, panel a laboratoř, revize a schválení; sportovec: souhlas, vzorek, ověření, dotazník, zpráva | `apps/genetics/setup_views.py`, `apps/genetics/views.py` |
| Testovací den | testy podle baterie (chybějící testy z baterie sportu), prostředí a únava (volitelné), hodnoty (test bez hodnot vede rovnou do zadávání), RPE (jen u testů, které ho vyžadují), kontrola (nestabilní pokusy, hodnoty mimo rozsah), zpráva (koncept nebo vydání) | `apps/measurements/steps.py` |
| Zpráva | koncept, souhrn (kdo ho napsal, zda je upravený), doporučení (návrh od modelu čeká na kontrolu), kontrola (čísla bez opory, nepřípustné výroky, souhlas u zprávy pro lékaře), vydání, předání (povinné jen u zprávy pro lékaře se souhlasem) | `apps/reports/steps.py` |
| Sportovec | údaje a souhlasy (sport, datum narození, souhlas s testováním), účet v portálu (volitelné), měření (naplánovaný den vede do zadávání), zpráva (koncept nebo vytvoření z posledního měření), předání nebo sdílení (volitelné) | `apps/subjects/steps.py` |
| Import | seznam: přístroje (volitelné), nahrát export, zkontrolovat a uložit (soubory čekající na kontrolu), výsledky v testovacích dnech; kontrola souboru: nahráno, sportovci rozpoznáni, vyžaduje pozornost, uložit, kam se zapsalo | `apps/ingest/steps.py` |
| Sporty a testy | sporty, baterie testů, klíčové ukazatele, MDC (správce, zatím v administraci), normy a pravidla (volitelné, správce) – stejné výpočty jako Stav pracoviště | `apps/catalog/steps.py` |
| Objednávky | nabídka a ceny, volné termíny, odkaz pro klienty, žádosti ke schválení, po schválení (volitelné) – na všech třech stránkách objednávek | `apps/booking/steps.py` |
| Články | knihovna: přidat článek, co dostane model, témata, zařazení (správce); jeden článek: identifikace, co dostane model, populace a témata, zařazení | `apps/evidence/steps.py` |
| AI zprávy | model běží, pokyny pro model (volitelné), vzorové zprávy (volitelné), hodnocení textů, zkušební sada (volitelné) | `apps/reports/steps.py` (`ai_steps`) |

Portál sportovce a trenéra dostane kroky jako poslední; návrh je
v tabulce níže.

## Návrh pro další části

| Část | Kroky | Z čeho aplikace pozná „hotovo“ |
|---|---|---|
| Portál sportovce | účet, souhlasy, sdílení s trenérem, dotazník, výsledky | žádost trenéra; dotazník k dnešnímu měření; nová zpráva |
| Portál trenéra | žádost o sdílení kódem, potvrzení sportovcem, přehled týmu | čekající žádosti; potvrzená sdílení |
