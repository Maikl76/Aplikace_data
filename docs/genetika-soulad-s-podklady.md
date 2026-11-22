# Genetika: soulad s podklady v02

Kontrola modulu Genetika proti třem obsahovým podkladům:
*01 Genové karty – plné znění v02*, *02 Dotazník, fenotyp a report v02*
a *03 Kontrola úplnosti a revize v02*. Podklady samotné nejsou v repozitáři;
obsah karet z nich nese `katalog/karty/*.json` (viz [genetika.md](genetika.md)).

Značení: **✔** bylo v aplikaci už dřív · **doplněno** = upraveno při této
kontrole · **k rozhodnutí** = věcné rozhodnutí garanta nebo vedení projektu.

## 01 Genové karty

| Požadavek podkladu | V aplikaci | Stav |
|---|---|---|
| Sedm plných karet (ACE, ACTN3, COL5A1, CYP1A2, IL6, LCT, PPARGC1A) v úplném původním znění | v1 *původní znění* (jen ke čtení) v souborech karet; co se nezařadilo do polí, je v *poznámce z podkladů* | ✔ |
| Tři karty bez původního obsahu (SLC16A1, FTO, TCF7L2) | v1 návrh s úkoly z osnovy v revizních záznamech | ✔ |
| Pozdější texty ACTN3 v0.2 odlišené od původních | v2 návrh: revidované texty, důkazy E01–E05, nepřípustné výroky, zdroje S1–S6; rozdíl proti v1 v revizních záznamech | ✔ |
| ACTN3 „Zdroje a změny proti původní kartě“ | doslovně v přehledu změn návrhu v2 (i do existujícího katalogu, pokud přehled nikdo neupravil) | doplněno |
| Interakce a kombinace „zachované hypotézy s označením k revizi“ | 18 kombinací v souborech karet, načtou se jako *hypotézy* jednou ke kartě (smazaná se nevrátí); u karty i v *Interakcích variant* | doplněno |
| Oprava AMPD1 rs1760279 → rs17602729; chybný zápis jen jako doklad | v seznamu variant kombinace správné rsID, název a předpoklad v původním znění, oprava v *důkazech a poznámkách* | doplněno |
| Interakce mimo panel (AMPD1, MMP3, ADORA2A, CRP, FADS1, PPARA) nelze z testu vyhodnotit | štítek *mimo panel* s chybějícími rsID; kombinace do zprávy nejdou | ✔ (formulář nově přijme i varianty mimo katalog) |
| Kombinace s tréninkem, zátěží nebo neurčeným genotypem | poznámka, že z genetického výsledku ji vyhodnotit nejde / genotyp druhé varianty chybí | doplněno |
| Frekvence: původní hodnoty označené k ověření | původní hodnoty bez souboru se do návrhu nepřebírají (revizní záznam *Frekvence genotypů*) | ✔ |

## 02 Dotazník, fenotyp a report

| Požadavek podkladu | V aplikaci | Stav |
|---|---|---|
| Osnova dotazníku po oddílech; „nevím“, „netýká se“ a chybějící odpověď se nezamění za „ne“ | sdílený dotazník *genetika*, osm oddílů, stavy odpovědí | ✔ |
| Odlišit subjektivní bolest od doložené diagnózy | otázka *Byly obtíže vyšetřeny lékařem nebo fyzioterapeutem?* | doplněno |
| Kofein: načasování vůči zátěži **a spánku** | *Kofein před výkonem* + nově *Kofein méně než 6 hodin před spaním* | doplněno |
| Laktóza: množství, četnost, načasování obtíží, souvislost se zátěží | nově *četnost mléčných výrobků a nápojů* a *kdy se obtíže objevují* (po jídle / při zátěži) | doplněno |
| Regenerace: časové období odpovědí | „poslední 4 týdny“ u únavy, bolestivosti, spánku a zátěže v osnově (nové instalace; v existující upraví laboratoř v Katalog → Dotazníky) | doplněno |
| Hmotnost: diagnózy jen v rozsahu, který zpráva použije | léky a doplňky ano; diagnózy se neptají, dokud je žádná karta nepoužívá | k rozhodnutí (s kartami FTO, TCF7L2) |
| V1: fenotypové výsledky nejsou vstupem, jen evidence dostupnosti | přepínač **Měření v genetické zprávě** na stránce Genetika: *Jen dostupnost (V1)* / *Hodnoty měření* | doplněno, **k rozhodnutí**: pro V1 přepnout na *Jen dostupnost* |
| U výsledku hodnota, jednotka, datum, metoda, protokol a kvalita; norma jen s referenčním souborem | v režimu hodnot: test (protokol a verze), kvalita (platné pokusy, ručně upravená / podezřelá hodnota), norma jen s citací souboru | doplněno |
| Chybějící měření: kterou vlastnost upřesnit, proč pro cíl klienta, jakou metodou; podle cíle, ne podle varianty | část 5 nabízí měření podle cíle klienta (*pro cíl klienta* u doporučení v kroku 4); texty karet podle vzoru z podkladu, „Jeho výsledek v této zprávě není k dispozici.“ | doplněno |
| Ověření vstupu (příslušnost, identita varianty, zápis genotypu); „nevalidní“ = nejasný vstup | ověření příslušnosti vzorku, kanonický zápis genotypu, kvalita zápisu | ✔ |
| Přesný text pro zjištěný genotyp ze schválené karty; jinak bez interpretace s důvodem | část 3 a 6 | ✔ |
| U každého závěru rozlišit laboratorní nález, odpověď klienta a měření | část 3: **Co víme** se štítky *laboratorní nález* / *dotazník* / *měření* | doplněno |
| Doporučení s tím, co ho odůvodňuje; nejasná kombinace k odbornému posouzení | důvod u každého doporučení, rozpor pod jedním klíčem → *K odbornému posouzení* | ✔ |
| Sloučení napříč kartami bez mechanického výběru a bez skóre | slučování podle klíče, žádné genetické skóre; stejná obecná doporučení mají v návrzích karet jedno znění, takže se spojí (s důvody všech karet) a rozpor „k odbornému posouzení“ zůstane jen pro skutečně odlišná doporučení | ✔, znění sjednoceno |
| Uchovat verzi karet **a dotazníku**; pozdější úprava nemění vydaný report | verze karet a panelu, nově *verze otázek* dotazníku (otisk), snímek při vydání | doplněno |
| Pořadí zprávy 1–6 | stejné | ✔ |
| U každé oblasti: co víme → co z toho lze vyvodit → jaký další krok dává smysl | část 3 po oblastech v těchto třech krocích; další krok odkazuje na číslovaná doporučení (část 4) a měření (část 5) | doplněno |
| Nesmí slibovat výkon, účinek suplementu ani přesné riziko | nepřípustné výroky (karty i společné), kontrola souhrnu modelu | ✔ |

## 03 Kontrola úplnosti a revize

| Požadavek podkladu | V aplikaci | Stav |
|---|---|---|
| Část karty *Interakce*: kombinace, důkazy a dostupnost variant | stránka karty ukazuje všechny kombinace varianty (i z jiných karet), *důkazy a poznámky*, štítek *mimo panel* / *všechny varianty v panelu* | doplněno |
| Část *Revize*: co ponechat, co upravit, co vyřadit, vždy s odůvodněním | rozhodnutí *ponechat původní znění / upravit podle návrhu / vyřadit z karty* s povinným odůvodněním; u interpretací a vysvětlení pro klienta se propíše do textu karty | doplněno |
| Žádná část se neztratí bez záznamu; původní znění a rozhodnutí v historii | v1 jen ke čtení, revizní záznamy s kým a kdy rozhodnuto | ✔ |
| Populační frekvence: konkrétní soubor a dohledatelný zdroj | frekvence bez zdroje schválení **zastaví**; zdroj bez URL/DOI upozorní; klient frekvence ve zprávě nevidí | doplněno |
| COL5A1: neúplný fragment „elders in Taiwan. Experimental Gerontology, 82, 46-52.“ doplnit, nebo po ověření vyřadit | zdroj S5 + revizní záznam; nerozhodnutý záznam teď blokuje schválení. Kontrola v PubMedu: roč. 82 (2016) má na těchto stranách jiné články (s. 39–49 a 50–57) – citaci se ověřit nepodařilo | k rozhodnutí (garant: doplnit, jinak vyřadit) |
| Formulace pro klienta musí projít kontrolou důkazů; zachování původního textu není schválení | schvaluje jen garant oblasti, bez blokujících nedostatků; značky [OVĚŘIT] / [DOPLNIT] blokují | ✔ |
| Fenotypové scénáře zachované, ale ne v aktivní V1 | scénáře s měřením vypnuté; v režimu *Jen dostupnost* se nevyhodnocují vůbec | ✔ |
| Panel deseti variant z Excelu je rozhodující | panel laboratoře s deseti variantami | ✔ |
