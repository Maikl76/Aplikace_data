# Import studie PRODEF

Studie TAČR PRODEF (pětidenní simulovaný operační stres, ramena Stres
a Kontrola, bloky čtvrtek–pondělí) se do aplikace načte ze **sešitu pro
spoluautory** (xlsx). Na jejích datech jde ukázat celý postup aplikace:
probandi → měření → vyhodnocení (výchozí měření, MDC, semafor
připravenosti, opakování v rámci dne) → doporučení.

## Ochrana dat

- **Data studie do repozitáře nepatří.** Sešit zůstává tam, kde ho máte
  (počítač laboratoře), a import ho čte odtamtud. `.gitignore` hlídá
  `*.xlsx`, `*.xls`, `*.pptx` a složku `vyzkum/` – do gitu se omylem nedostanou.
- **Do veřejného zkušebního provozu** (PythonAnywhere, DEMO_MODE) jen se
  souhlasem vedoucího projektu. Bez něj příkaz odmítne běžet; se souhlasem
  se spouští s `--souhlas-vedouciho`.
- **Heslo k sešitu** se nikam neukládá: příkaz se na něj zeptá (při psaní se
  nezobrazuje), nebo ho vezme z proměnné prostředí `XLSX_HESLO` a hned ji
  smaže. Odšifrovaný sešit vzniká jen v paměti, na disk se nezapíše.
- Probandi jsou v aplikaci pod kódem studie (`PRODEF-P07`), **bez jmen**.
  Nenačítá se nic z vstupního zdravotního dotazníku (CIQ), léky, kofein,
  nikotin, strava, střelba, HRV, POMS ani STAI.
- Import se zapíše do auditu; `--smazat` odebere všechno, co založil.

## Jak načíst

**Na počítači laboratoře (Windows):** přetáhněte sešit myší na
`nacist-prodef.bat` ve složce aplikace (nebo ho spusťte a zadejte cestu).
Zeptá se na heslo, ukáže, co v sešitu našel, a načte po potvrzení `ANO`.

**Příkazem:**

    python manage.py import_prodef cesta/k/sesitu.xlsx --nanecisto   # jen ukázat, co by se načetlo
    python manage.py import_prodef cesta/k/sesitu.xlsx                # načíst
    python manage.py import_prodef cesta/k/sesitu.xlsx --zeptat       # ukázat a zeptat se
    python manage.py import_prodef --mdc-z-kontroly                   # MDC z kontrolní skupiny
    python manage.py import_prodef --smazat                           # odebrat studii z aplikace

Opakovaný import nic nezdvojí: proband se pozná podle kódu, provedení testu
podle odkazu do sešitu (proband, den, test, měřicí bod) a jeho pokusy se
nahradí hodnotami z aktuálního sešitu. Ručně změněné výchozí měření
u probanda import nepřepíše. Když je v aplikaci víc pracovišť, přidejte
`--pracoviste zkratka`.

## Co se kam načte

| v sešitu | v aplikaci |
|---|---|
| list Probandi (kdo nastoupil) | sportovci `PRODEF-Pxx`, sport *PRODEF – simulovaný operační stres*, tým *PRODEF Stres* / *PRODEF Kontrola*, kategorie = rameno, přibližný rok narození z věku, v poznámce blok |
| den 1–5, datum | testovací den (místo „PRODEF, Den 3 – sobota (SMOS)“) |
| měřicí bod 1–4 | provedení testu; **bod 1 je hlavní měření dne**, body 2–4 opakování dne s pozicí „po zátěžovém bloku N“ (z listu MASTER) |
| VALD_CMJ, VALD_IMTP, VALD_SLS (pokus = řádek) | pokusy a hodnoty přes **profily importu VALD ForceDecks** – stejné sloupce → ukazatele jako běžný export z VALD Hubu, i levá a pravá strana |
| VALD_BoxLift | box lift přes profil HumanTrak; opakování a zátěž jako podmínky testu |
| kod_opravy (přeřazení, přepočet vážení) | hodnoty už opravené v sešitu, u hodnoty poznámka „oprava v sešitu: Z1“ |
| CMJ_kontrola, IMTP_kontrola_kategorie, SLS_kontrola_kategorie | hodnota se nemění (jako v sešitu), kvalita *podezřelá hodnota* s poznámkou |
| Prostředí (posilovna) | teplota a vlhkost u testovacího dne |
| Noční formulář, KSS, VAS únava, ranní dotazník (svalová únava) – 1. časový bod dne | dotazník *PRODEF – ranní připravenost (import)*: hodiny spánku, KSS 1–9, únava VAS 0–100, svalová únava 1–5, s prahy signálu 6 h / 7 / 60 / 4 jako v analýze studie; dotazník je neaktivní, v testovacích dnech se nenabízí |
| den 2 (pátek, před první zátěží) | **výchozí měření** probanda |

Ranní dotazník ze dne bez měření VALD (čtvrtek nástupu) se nenačte – založil
by prázdný testovací den, který by se tvářil jako naplánovaný.

## Co v aplikaci ukázat

1. **Týmový přehled** → *PRODEF Stres* / *PRODEF Kontrola*, volba *změna proti
   výchozímu měření*: poslední měření každého probanda proti pátku, posouzené
   proti MDC, a sloupec *Připravenost* (semafor posledního dne).
2. **MDC z vlastních dat** (Nastavení → MDC u ukazatelů → *spočítat z dat*):
   skupina *tým PRODEF Kontrola*, odstup **1 den** – typická chyba
   a MDC90/95 z kontrolní skupiny, která se mezi dny neměla měnit. Totéž
   udělá `import_prodef --mdc-z-kontroly` pro výšku výskoku, vrcholovou sílu
   IMTP a plochu elipsy CoP (uloží MDC90 se zdrojem).
3. **Testovací den** probanda ze stresové skupiny v sobotu nebo neděli:
   karta *Připravenost* se signály (spánek, ospalost, únava, svalová únava
   a pokles výkonu nad MDC proti pátku).
4. **Karta probanda**: dlaždice „proti výchozímu“ a grafy s modrým pásmem
   výchozí ± MDC.
5. **Zpráva** z dne se zátěží: tabulka *Opakovaná měření téhož dne* s pozicí
   (před zátěží / po bloku 1–3) a tučně změnami větší než MDC; s aktivními
   příklady pravidel semaforu (Nastavení → Pravidla) i doporučení.

## Poznámky k výpočtům

- **IMTP:** sešit (list MASTER) bere u vrcholové síly nejlepší pokus,
  katalog aplikace průměr pokusů. Pro stejné hodnoty jako MASTER nastavte
  u *Vrcholová síla (IMTP)* hodnotu dne „nejlepší pokus“ (Nastavení →
  Testy) – změní se tím ale hodnota dne u všech sportovců pracoviště.
- **MDC** se ukládá ke sdílenému ukazateli – platí pro všechny sportovce
  pracoviště. Na počítači, kde jsou i běžní sportovci laboratoře, zvažte,
  jestli MDC z vojenské studie chcete i pro ně.
- Semafor potřebuje aspoň 4 posouzené ukazatele, takže ho mají dny
  s ranním dotazníkem (dny 2–5).
