# Přístupy: kdo na co vidí a co smí

Role je jen **šablona výchozích hodnot**. Skutečný přístup nastaví správce
u každého účtu kolegy v **Kolegové → Přístup** a potvrdí ho. Dvě nezávislé
věci:

- **Na co vidí (rozsah dat):** sporty (všechny, nebo vybrané; volitelně
  jen vybrané týmy), jména sportovců, genetika sportovců, externí
  vyšetření, objednávky.
- **Co smí (oprávnění):** zadávat a importovat měření; sportovci (zakládat
  a upravovat, souhlasy, pozvánky, sdílení, plán, cíle); koncepty zpráv;
  vydávat a předávat zprávy; nastavení sportů (baterie, normy, pravidla,
  dotazníky, interní reference); nastavení testů (testy, ukazatele, MDC,
  popisy, přístroje – jen pro vybrané metodiky, tj. rodiny testů);
  exporty dat; úpravy knihovny článků.

Správce má vždy vše a jako jediný spravuje kolegy, pracoviště, provoz
a zálohy, pokyny pro model a dostane se do administrace Djanga. Sportovec
a trenér mají vlastní portál; na koho vidí, určuje účet a sdílení
potvrzené sportovcem (ne tato nastavení).

## Výchozí šablony

| | Správce | Laborant | Metodik | Výzkumník |
|---|---|---|---|---|
| sporty | všechny | přidělené | přidělené | přidělené |
| jména | ano | ano | ne | ne |
| genetika sportovců | ano | ne | ne | ne |
| vyšetření, objednávky | ano | ano | ne | ne |
| měření zadávat a importovat | ano | ano | ne | ne |
| sportovci | ano | ano | ne | ne |
| koncepty zpráv | ano | ano | ano | ne |
| vydávat a předávat zprávy | ano | ne | ano | ne |
| sporty, baterie, normy, pravidla, dotazníky | ano | ne | ano | ne |
| testy, ukazatele, MDC, přístroje | ano | ne | ano (své metodiky) | ne |
| exporty | ano | ne | ano | ne |
| knihovna článků (úpravy) | ano | ne | ano | ne |

**Nový účet kolegy nemá žádný sport**, dokud mu ho správce nepřidělí:
do té doby nevidí žádného sportovce. Krok *Přístupy kolegů* ve Stavu
pracoviště hlásí účty, u kterých správce přístup ještě nepotvrdil.

**Stávající účty** dostaly při aktualizaci přístup odpovídající dnešnímu
chování (všechny sporty, laborant i s genetikou a vydáváním), ale jako
nepotvrzený – správce ho projde a zúží. Do administrace Djanga se od této
verze dostane jen správce.

## Co rozsah sportů ovlivní

Seznam a hledání sportovců, karta sportovce (mimo rozsah neexistuje),
měření, zprávy, Dnešní testování, týmový přehled, Kdo je na řadě, exporty
a interní reference na kartě. Nastavení sportů ukazuje jen přidělené
sporty. **Import**: účet s rozsahem uloží jen soubor, jehož sportovci jsou
v jeho rozsahu; nové sportovce z importu nezakládá (nový sportovec by neměl
sport) a vidí jen importy, které nahrál sám (náhled nese jména ze souboru).
Hlídač sledované složky běží pod systémovým účtem bez omezení.

Bez oprávnění *Jména* se jména nedešifrují nikde: v seznamech, ve zprávách
(zpráva pod kódem), v e‑mailech ani v exportech.

## Metodik

Odpovídá za **sporty** (baterie, normy, pravidla, dotazníky, interní
reference, vydávání zpráv pro sportovce svých sportů) a za **metodiky
měření** = rodiny testů (silová plošina, dynamometrie, spiroergometrie,
složení těla, terénní testy, jiné): testy, ukazatele, MDC, popisy pro
klienta, sloupce exportů a přístroje. Jména sportovců nevidí, dokud mu je
správce nezapne; měření nezadává.

Co to znamená uvnitř stránek nastavení:

- **Sporty a baterie**: vidí a upravuje jen přidělené sporty; u sportu
  je napsáno, který metodik za něj odpovídá (správce tak vidí sporty bez
  metodika). Nový sport zakládá jen účet se všemi sporty (jinak by ho
  sám neviděl) – totéž u „nový sport“ při zakládání sportovce.
- **Testy, ukazatele, MDC, popisy, přístroje a profily importu**: upravit
  jde jen test, ukazatel nebo profil z přidělené rodiny testů; ostatní
  jsou ke čtení („jen čtení“). U testu je napsáno, který metodik za jeho
  metodiku odpovídá.
- **Normy a pravidla**: upravit a mazat jde jen normu nebo pravidlo
  přiděleného sportu; normu nebo pravidlo napříč sporty (bez sportu)
  zapisuje jen účet se všemi sporty. Cizí jsou v přehledu „jen čtení“.
- **Přehled** ukazuje rozsah účtu („Váš rozsah: Florbal · jen Ženy A“)
  a u účtu bez jmen připomene, že vidí kódy.

Ve zkušebním provozu je ukázkový účet `metodik` (sporty ukázkových
sportovců, metodika silová plošina, bez jmen) se stejným heslem jako
ostatní ukázkové účty.

## Jak se to vymáhá

- `apps/core/access.py`: `can(user, klíč)`, `manage(user)`, `scope(user)`,
  `scope_queryset(model, qs, user)`, `families(user)`, `summary(user)`,
  `unconfigured(org)`, `require(klíč)` pro pohledy, `grant()` pro skripty
  a testy. Záznam `core.Access` (1:1 k účtu), šablony `PRESETS`.
- `OrgScopedQuerySet.for_user` filtruje každý dotaz podle rozsahu
  (sportovec, tabulky se sportovcem, sport, tým, baterie; náhled importu
  podle nahrávajícího).
- `RoleAccessMiddleware` hlídá celé sekce a zapisující akce podle adresy
  (`SECTION_RULES`), pohledy klíčové akce (`access.can`, `require`).
- Menu a tlačítka berou `pristup` z context processoru.
- Každá změna přístupu je v auditu (`nastaveni=pristup`). Testy:
  `tests/test_pristupy.py`.
