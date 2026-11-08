# Práce na více počítačích

Kód je na GitHubu a každý počítač má jeho kopii. Co se přenáší a co ne:

| Co | Kde je | Jak se přenáší |
|---|---|---|
| kód aplikace | GitHub | `spustit.bat` (dělá `git pull`) |
| nastavení – sporty a týmy, testy, metriky, MDC, baterie, normy, pravidla, články, dotazníky, přístroje, nabídka, genetika, volby pracoviště | databáze počítače | **Nastavení → Přenos nastavení** (balíček ke stažení a nahrání), nebo `ulozit-katalog.bat` → `nacist-katalog.bat` přes GitHub |
| sportovci, měření, zprávy, objednávky, účty | databáze počítače (`db.sqlite3`) | **nepřenáší se** |
| nastavení (`.env`), LM Studio a model | počítač | **nepřenáší se** – každý stroj má svoje |

Na počítačích jsou jen vymyšlená data (`seed_demo`), takže každý má svoje
a nic se nemusí slaďovat. Databázi nesynchronizujte přes OneDrive ani
Dropbox: soubor se při souběžném otevření poškodí a jednou by se tak snadno
dostala skutečná data sportovců tam, kam nepatří.

## Nový počítač (jednou)

1. Nainstalujte **Python** (https://www.python.org/downloads/, zaškrtněte
   *Add python.exe to PATH*) a **Git** (https://git-scm.com/download/win).
2. V příkazovém řádku:

   ```
   git clone -b claude/redesign-testing-recommendations-app-o29wru https://github.com/Maikl76/Aplikace_data.git
   ```

3. Ve složce `Aplikace_data` dvakrát klikněte na **`zalozit.bat`**.
4. Pro jazykový model nainstalujte LM Studio podle
   [lokalni-ai.md](lokalni-ai.md) a v souboru `.env` (`notepad .env`)
   upravte `LLM_MODEL` podle modelu, který na tomhle počítači máte.
   Pokud je ve jménu uživatele diakritika, přesuňte složku LM Studia – viz
   tamtéž.

## Každý den

Dvojklik na **`spustit.bat`**. Stáhne nejnovější verzi, upraví databázi,
spustí aplikaci a otevře prohlížeč. Okno nechte otevřené.

## Přenos nastavení mezi instancemi

Co nastavíte v aplikaci (nový test, MDC, norma, pravidlo, článek, genová
karta, baterie, sport, nabídka objednávek, dotazník, volby pracoviště),
uloží se do databáze té instance. Aby to měla i druhá instance – zkušební
provoz na webu, druhý počítač, jednou fakultní server:

1. V instanci, kde jste to nastavili: **Nastavení → Přenos nastavení →
   Stáhnout balíček**. Uloží se soubor `nastaveni-<zkratka>-<datum>.json`.
2. V druhé instanci: **Nastavení → Přenos nastavení → Nahrát balíček**.
   Ukáže se náhled, co je nové, co se změní a co je stejné; nic se nezapíše,
   dokud nekliknete **Načíst do této aplikace**.

Funguje oběma směry (web → počítač i počítač → web) a jen pro správce.
Historie přenosů na téže stránce říká, kdy se co stáhlo a načetlo.

Pravidla:

- Načtení **přidává a mění, nikdy nemaže**: co jste v jedné instanci
  smazali, v druhé zůstane (smažte to tam ručně).
- Záznamy se párují podle kódů; stejné položky se nepřepisují, takže je
  v náhledu vidět, co přenos opravdu změní.
- Když se totéž upraví na obou stranách, platí to, co se načetlo později.
  Dokud se nastavení teprve tvoří, domluvte se, kde se co upravuje,
  a přenášejte často.
- Nepřenáší se sportovci, měření, zprávy, objednávky a termíny, účty
  kolegů a jejich přístupy, klíče v `.env` ani jazykové modely.

Alternativa přes GitHub (počítače s gitem): **`ulozit-katalog.bat`** uloží
balíček do `katalog/katalog.json` a nahraje ho, **`nacist-katalog.bat`** ho
na druhém počítači načte. Na serveru totéž příkazem
`python manage.py import_katalog --organizace <zkratka>`; zkratku
organizace je potřeba zadat, pokud se na serveru jmenuje jinak.


## Záloha laboratorního počítače

Na laboratorním počítači jsou skutečná měření, ne jen ukázková data.
Jednou týdně (a před každou větší změnou) dvakrát klikněte na
**`zalohovat.bat`**. Uloží databázi, nahrané soubory a soubor `.env`
s klíči do složky `Zalohy-FTVS` ve vašem profilu; jinam ji uloží
`zalohovat.bat "E:\zalohy"`. Složku pak zkopírujte mimo počítač – na
šifrovaný disk nebo síťové úložiště fakulty; obsahuje jména sportovců.
Nechává se posledních deset záloh, starší se mažou samy. Kromě toho
se jednou denně zálohuje samo – do podsložky `Zalohy-FTVS\denni`
(posledních sedm), viz `docs/provoz.md` a Nastavení → Provoz a zálohy.

Bez `.env` jsou jména v záloze databáze nečitelná (klíč
`IDENTITY_ENCRYPTION_KEY`), proto patří do zálohy i on.

Obnova: zavřete okno aplikace, soubory `db.sqlite3`, `.env` a složku
`media` nahraďte těmi ze zálohy a spusťte `spustit.bat`.
