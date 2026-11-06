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
| Nastavení | stav pracoviště (kolegové, sporty a baterie, testy a klíčové ukazatele, MDC, přístroje a import, normy a pravidla, objednávky, genetika, klíče a model) a kategorie „kam co patří“; vlastní stránky: pracoviště a týmy, MDC u ukazatelů se zdrojem, sloupce exportů VALD | `apps/core/workplace.py`, `apps/catalog/settings_views.py` |
| Genetika | nastavení: garanti, genové karty, panel a laboratoř, revize a schválení; karta (8 kroků): varianta, co gen dělá, texty pro genotypy, doporučení s důvody, kontext z dotazníku, co zpráva říkat nesmí, zdroje a důkazy, kontrola a schválení; sportovec: souhlas, vzorek, ověření, dotazník, zpráva | `apps/genetics/setup_views.py`, `apps/genetics/card_steps.py`, `apps/genetics/views.py` |
| Testovací den | testy podle baterie (chybějící testy z baterie sportu), prostředí a únava (volitelné), hodnoty (test bez hodnot vede rovnou do zadávání), RPE (jen u testů, které ho vyžadují), kontrola (nestabilní pokusy, hodnoty mimo rozsah), zpráva (koncept nebo vydání) | `apps/measurements/steps.py` |
| Zpráva | koncept, souhrn (kdo ho napsal, zda je upravený), doporučení (návrh od modelu čeká na kontrolu), kontrola (čísla bez opory, nepřípustné výroky, souhlas u zprávy pro lékaře), vydání, předání (povinné jen u zprávy pro lékaře se souhlasem) | `apps/reports/steps.py` |
| Sportovec | údaje a souhlasy (sport, datum narození, souhlas s testováním), účet v portálu (volitelné), měření (naplánovaný den vede do zadávání), zpráva (koncept nebo vytvoření z posledního měření), předání nebo sdílení (volitelné) | `apps/subjects/steps.py` |
| Import | seznam: přístroje (volitelné), nahrát export, zkontrolovat a uložit (soubory čekající na kontrolu), výsledky v testovacích dnech; kontrola souboru: nahráno, sportovci rozpoznáni, vyžaduje pozornost, uložit, kam se zapsalo | `apps/ingest/steps.py` |
| Sporty a testy | sporty, baterie testů, klíčové ukazatele, MDC se zdrojem hodnoty (správce), normy a pravidla (volitelné) – stejné výpočty jako Stav pracoviště | `apps/catalog/steps.py` |
| Normy | normy u klíčových ukazatelů, hodnoty (průměr a SD, nebo percentily), zdroje, pravidla (zatím administrace); formulář normy v pěti částech s náhledem, kolika sportovcům sedí | `apps/catalog/steps.py` (`norm_steps`), `apps/catalog/norm_views.py` |
| Objednávky | nabídka a ceny, volné termíny, odkaz pro klienty, žádosti ke schválení, po schválení (volitelné) – na všech třech stránkách objednávek | `apps/booking/steps.py` |
| Články | knihovna: přidat článek, co dostane model, témata, zařazení (správce); jeden článek: identifikace, co dostane model, populace a témata, zařazení | `apps/evidence/steps.py` |
| AI zprávy | model běží, pokyny pro model (volitelné), vzorové zprávy (volitelné), hodnocení textů, zkušební sada (volitelné) | `apps/reports/steps.py` (`ai_steps`) |
| Portál sportovce | účet, souhlasy (souhlas s testováním), sdílení s trenérem (čekající žádosti), dotazník (RPE v den měření), výsledky | `apps/portal/steps.py` |
| Portál trenéra | žádost o sdílení, potvrzení sportovcem, přehled týmu | `apps/portal/steps.py` |

Kapitola *Průvodci a připomínky* v *O aplikaci* říká totéž uživatelům.

## Jak přidat kroky do nové části

1. Napište funkci `*_steps(...)`, která z dat složí seznam `step(...)`
   (`apps/core/steps.py`). Text kroku je jedna věta: co chybí, nebo co je
   hotové. Tlačítko vede přímo tam, kde se to řeší; kotva `#…` skáče na
   místo na stránce.
2. V pohledu dejte do kontextu `steps` (a `next_step`, když ho potřebují
   testy).
3. V šabloně vložte `{% steps steps heading="…" %}`; `compact=True` pro
   užší karty, `may_act=…` pro role jen ke čtení.
4. Napište test: pro každý krok stav „čeká“ i „hotovo“ a správný
   *Další krok*.
