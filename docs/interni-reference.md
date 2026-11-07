# Interní referenční hodnoty laboratoře

Normy se zdrojem (Nastavení → Normy) jsou citovatelné srovnání: průměr ± SD
nebo percentily z literatury, zpráva proti nim staví výsledek. Pro spoustu
ukazatelů ale norma pro daný sport, pohlaví a věk neexistuje. Laboratoř
má přitom vlastní měření stovek sportovců – a právě z nich vznikají
**interní referenční hodnoty**: pásmo P25–P75 a medián pro skupinu
sportovců stejného sportu, pohlaví a věkového pásma.

Je to orientace laboratoře, ne norma: nemá zdroj, nejde citovat
a **nikdy nejde do zprávy ani do portálu**. Vidí ji jen laboratoř – na
kartě sportovce a v týmovém přehledu.

## Co se počítá

- **Hodnota sportovce** = hodnota dne z jeho *posledního* měření
  ukazatele (průměr nebo nejlepší pokus podle ukazatele, platné pokusy,
  hlavní provedení – stejně jako v grafech). Každý sportovec vstupuje
  jednou, ať byl měřen jednou nebo desetkrát.
- **Skupina** = sport × pohlaví × věkové pásmo v den měření:
  do 14, 15–17, 18–23, 24–34, 35 a více let. Sportovci bez sportu nebo
  s pohlavím „jiné / neuvedeno“ do skupin nevstupují a pásmo u nich
  nevidíte. Věk se bere z data narození (identita), jinak z roku narození.
- **Pásmo** = 25. a 75. percentil, medián jako čára. Žádný průměr ± SD:
  u malých skupin jsou percentily odolnější vůči jedné odlehlé hodnotě.
- **Minimum**: skupina se použije až od nastaveného počtu sportovců
  (výchozí 8, nejméně 3). Když na něj nedosáhne, zkusí se tentýž sport
  a pohlaví bez rozlišení věku („všechny věky“); jinak se pásmo neukáže.
- Jen **klíčové ukazatele** (ty, které jdou na kartu a do týmového
  přehledu), každá kombinace strany, režimu a rychlosti zvlášť.

## Souhlasy – z koho se počítá

Nastavení → Interní reference, jen správce:

- **jen sportovci s platným souhlasem s výzkumem** (výchozí, bezpečnější
  volba) – rozsah souhlasu *Sekundární použití pro výzkum (anonymizovaně)*,
  odvolaný nebo prošlý souhlas sportovce z výpočtu vyřadí;
- **všichni aktivní sportovci pracoviště** – zapněte jen tehdy, když
  souhlas s testováním vašeho pracoviště interní srovnání výslovně
  pokrývá. Za volbu ručí správce; je v auditu.

Stránka ukazuje, kolik sportovců do výpočtu vstupuje a kolik skupin má
dost sportovců; stejné kroky jsou ve Stavu pracoviště přes odkaz u norem.

## Kde se pásmo ukáže

- **Karta sportovce (laboratoř)**: v dlaždici klíčového ukazatele řádek
  s odznakem *interní* – pásmo, medián, skupina, počet sportovců a kde
  v pásmu poslední hodnota leží (*nad P75* zeleně u ukazatele, kde je
  vyšší lepší; *pod P25* oranžově; u ukazatelů bez „lepší–horší“ modře).
  V grafu vývoje šedé pásmo s tečkovaným mediánem – jen když ukazatel
  **nemá normu**; dvě pásma přes sebe by nešla číst, norma má přednost.
- **Týmový přehled**: řádek *interní* v patičce s pásmem nejčastější
  skupiny týmu a v popisku každé buňky, kde v pásmu sportovec leží.
  Barvy buněk dál patří srovnání s týmem (z-skóre).
- **Nikde jinde**: portál sportovce a trenéra, zprávy (text šablony,
  model i PDF), souhrny za období ani exporty interní reference
  nedostanou. Interní reference se ani nepřenášejí s katalogem.

## Pro programátora

`apps/analytics/reference.py`: `ReferenceIndex(organization)` spočítá
všechny skupiny jedním dotazem (`band_for(subject, metric, qualifiers)`,
`band(...)`, `overview()`, `summary()`), `Band.position(value)` dává
slovní polohu a stupeň. Graf: `charts.trend_chart(..., band=)`, dlaždice
`overview.kpi_tiles(..., reference=)`, týmový přehled
`team.team_table(..., reference=)` – index dostávají jen pohledy
laboratoře (`subject_detail`, `team`); portál ani zprávy ho nepředávají.
Nastavení pracoviště: `Organization.reference_enabled`,
`reference_min_subjects`, `reference_source`. Testy: `tests/test_reference.py`.
