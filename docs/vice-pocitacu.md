# Práce na více počítačích

Kód je na GitHubu a každý počítač má jeho kopii. Co se přenáší a co ne:

| Co | Kde je | Jak se přenáší |
|---|---|---|
| kód aplikace | GitHub | `spustit.bat` (dělá `git pull`) |
| katalog – testy, metriky, MDC, normy, pravidla, články | databáze počítače | `ulozit-katalog.bat` → `nacist-katalog.bat` |
| sportovci, měření, zprávy | databáze počítače (`db.sqlite3`) | **nepřenáší se** |
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

## Katalog

Co nastavíte v **Katalogu** (nový test, MDC, norma, zapnuté pravidlo,
článek), uloží se do databáze toho počítače. Aby to měl i druhý počítač
(a jednou fakultní server):

1. Na počítači, kde jste katalog změnil: **`ulozit-katalog.bat`**.
   Uloží ho do `katalog/katalog.json` a nahraje na GitHub. Poprvé se
   otevře prohlížeč s přihlášením do GitHubu.
2. Na druhém počítači: **`nacist-katalog.bat`**.

Katalog upravujte vždy jen na jednom počítači a hned ho uložte. Načtení
přepíše změny v katalogu, které na tom druhém počítači uložené nebyly.

Na serveru se katalog načte příkazem
`python manage.py import_katalog --organizace <zkratka>`; zkratku
organizace je potřeba zadat, pokud se na serveru jmenuje jinak.
Načítání nic nemaže – co v souboru není, zůstane beze změny.
