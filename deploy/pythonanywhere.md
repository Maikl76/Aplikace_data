# Zkušební provoz na PythonAnywhere

Bezplatný hosting **bez platební karty** na evropském serveru. Slouží
k tomu, aby si kolegové mohli aplikaci vyzkoušet celou a spolupracovat na
ní: každý s vlastním účtem, včetně nahrávání souborů, genetiky a přístrojů.
Běží v ní jen smyšlená data a má zapnutý režim `DEMO_MODE` (varovný pruh,
ukázková data, reset na jeden příkaz); jinak funguje stejně jako program
v laboratoři.

Výsledná adresa: `https://JMENO.eu.pythonanywhere.com`

Všude níže nahraďte **JMENO** svým uživatelským jménem na PythonAnywhere.
**Pozor na velká písmena:** v cestách (`/home/JMENO/...`) piště jméno
přesně, jak je (např. `Maikl76`); v adrese (`JMENO.eu.pythonanywhere.com`)
je vždycky malými (`maikl76`).

---

## 1. Účet

Zaregistrujte se na **https://eu.pythonanywhere.com** — pozor na `eu.`,
jen tak budou data v EU.

> Jestli účet skončil na hlavním serveru, poznáte to na záložce **Web**:
> adresa je `JMENO.pythonanywhere.com` (bez `.eu`). Pro ukázku
> s vygenerovanými daty to nevadí, jen v `.env` a v prohlížeči pak
> používejte adresu bez `.eu`. Zvolte bezplatný účet (*Beginner*). Platební
kartu nezadávejte, není potřeba.

Uživatelské jméno se objeví v adrese ukázky, zvolte ho s rozmyslem.

## 2. Konzole

Nahoře **Consoles** → **Bash**. Otevře se příkazová řádka v prohlížeči.
Všechny příkazy v krocích 3–6 se píšou sem, **po jednom řádku**.

## 3. Stažení kódu

```
git clone -b claude/redesign-testing-recommendations-app-o29wru https://github.com/Maikl76/Aplikace_data.git
```

```
cd Aplikace_data
```

## 4. Prostředí a knihovny

```
mkvirtualenv --python=$(which python3.11) ftvs
```

> Cestu k Pythonu nepište napevno. Na PythonAnywhere je víc instalací
> a při neshodě spadne instalace knihoven na
> `No module named '_posixsubprocess'`. `$(which python3.11)` vezme tu,
> kterou systém opravdu používá.

Na začátku řádku se objeví `(ftvs)`.

```
echo 'export DJANGO_SETTINGS_MODULE=config.settings.prod' >> ~/.virtualenvs/ftvs/bin/postactivate
```

```
export DJANGO_SETTINGS_MODULE=config.settings.prod
```

```
pip install --no-cache-dir -r requirements/demo.txt
```

Trvá několik minut. `--no-cache-dir` je důležité: bez něj by si pip
uložil stažené balíčky a bezplatných 512 MB by nestačilo.

## 5. Nastavení

Vygenerujte tajný klíč a zkopírujte si ho:

```
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Vytvořte soubor s nastavením ze šablony:

```
cp deploy/pythonanywhere.env.example .env
```

Otevřete ho: nahoře **Files** → složka `Aplikace_data` → soubor `.env`.
(Soubory začínající tečkou může být potřeba zobrazit.) Nahraďte:

- `VLOZTE_VYGENEROVANY_KLIC` → klíč z předchozího kroku
- `JMENO` → vaše uživatelské jméno (na třech místech)
- `ZVOLTE_DLOUHE_HESLO` → heslo, kterým se budete přihlašovat jako `admin`

Uložte (**Save**) a vraťte se do konzole.

## 6. Databáze a data

```
python manage.py migrate
```

```
python manage.py collectstatic --noinput
```

```
python manage.py bootstrap_demo
```

Poslední příkaz musí skončit `Ukázková instance je připravená.`

## 7. Webová aplikace

Nahoře **Web** → **Add a new web app**:

1. Doménu nechte, jak ji nabídne.
2. **Manual configuration** — ne „Django“! Průvodce pro Django by založil
   nový prázdný projekt.
3. **Python 3.11**.

Na stránce webové aplikace pak nastavte:

**Code**

- *Source code:* `/home/JMENO/Aplikace_data`
- *Working directory:* `/home/JMENO/Aplikace_data`
- *WSGI configuration file:* klikněte na odkaz, **smažte celý obsah**
  a vložte obsah souboru `deploy/pythonanywhere_wsgi.py` (opět s JMENO).
  Uložte.

**Virtualenv**

- `/home/JMENO/.virtualenvs/ftvs`

**Security**

- *Force HTTPS:* **Enabled**

Nahoře zelené tlačítko **Reload**.

## 8. Hotovo

Otevřete `https://JMENO.eu.pythonanywhere.com`, přihlašte se jako
`admin` heslem z kroku 5. Nahoře musí být oranžový pruh **ZKUŠEBNÍ PROVOZ**.

## Účty pro kolegy

Každý kolega má vlastní účet s rolí, žádné sdílené heslo. V menu
**Kolegové** (vidí jen správce) vyplňte jméno, příjmení a roli a klikněte
*Založit a vytvořit odkaz*. Aplikace ukáže jednorázový odkaz: pošlete ho
kolegovi zprávou nebo e‑mailem (tlačítko *Kopírovat*). Odkaz platí 7 dní,
kolega si jím nastaví heslo a je přihlášený; pak odkaz přestane fungovat.
Poštovní server k tomu není potřeba.

Zapomenuté heslo: u účtu klikněte *Odkaz na heslo* a pošlete nový odkaz.
Odchod z týmu: *Vypnout* – účet se nepřihlásí, data zůstanou.

Role: *správce* (vše, účty, katalog), *diagnostik* (měření, zprávy, revize
genových karet), *výzkumník* (jen čtení, bez jmen), *trenér* (vlastní
portál). Sportovci účet nezakládejte tady – vzniká z pozvánky na jeho kartě.

## Připomínky kolegů

Každý má dole v menu tlačítko **Připomínka** a u každého postupu odkaz
*Připomínka*: napíše, co mu nesedí, a připomínka se uloží i s tím, na které
stránce a u kterého kroku vznikla. Správce je má v menu **Připomínky**
(s počtem nových), vyřídí je s odpovědí a vyřízené zůstanou k nahlédnutí.
Tohle je hlavní kanál pro zkušební provoz: podle připomínek se aplikace mění.

**Stav pracoviště** v menu ukazuje nastavení všech částí na jednom místě
(kolegové, sporty a baterie, testy a klíčové ukazatele, MDC, přístroje,
normy a pravidla, objednávky, genetika, klíče a model); **Přehled** vede
dnem: kdo přijde, hodnoty, kontrola, zprávy, předání.

---

## Aktualizace po změnách

Nahoře **Consoles** → **Bash** a po jednom řádku:

```
cd ~/Aplikace_data
```

```
git pull
```

```
bash deploy/pa-update.sh
```

Stáhne novou verzi, **zazálohuje databázi a nahrané soubory** do složky
`~/Zalohy-FTVS` (posledních 10 záloh), upraví databázi, doplní do katalogu
nové testy a do ukázky chybějící ukázkové účty portálu (`sportovec`,
`rodic`, `trener`) a restartuje aplikaci. **Data zůstanou** – účty, zprávy,
cokoli jste v ukázce zadali. Pak v prohlížeči **Ctrl+F5**.

`git pull` zvlášť předem je důležitý: skript se při stahování sám mění
a bash by jinak dojel starou verzi.

Pozor na **šipku nahoru** v konzoli: vrátí poslední příkaz i s přepínačem
(třeba `--nova-data`).

### Návrat ze zálohy

```
bash deploy/pa-update.sh --obnovit
```

Vrátí ukázku do stavu před poslední aktualizací – databázi i nahrané
soubory. Skript chce opsat `OBNOVIT` a současný stav předtím zazálohuje.
Starší zálohu obnovíte uvedením její složky (seznam: `ls ~/Zalohy-FTVS`):
`bash deploy/pa-update.sh --obnovit ~/Zalohy-FTVS/ftvs-zaloha-…`.

### Úplně nová ukázková data – smaže všechno

```
bash deploy/pa-update.sh --nova-data
```

**Smaže všechna data ukázky** – účty, zprávy, sportovce, měření, články,
objednávky – a vygeneruje nová (sportovce, měření, baterie, ukázkové
účty). Jen když chcete začít načisto. Skript se zeptá, chce opsat
`SMAZAT` a před smazáním udělá zálohu. Přihlášení `admin` zůstane s heslem
z `.env`. Jde to jen v ukázkovém režimu.

Kvůli novým funkcím se data mazat nemusí – běžná aktualizace doplní, co
je potřeba (katalog, ukázkové účty).

### Databáze na síťovém disku

Disk na PythonAnywhere je síťový. Režim WAL databáze SQLite přes síťový
disk nefunguje a může ztratit data, proto je v `.env` `SQLITE_WAL=False`
(aktualizace ho doplní sama). Databázi, kterou předchozí verze do WAL
přepnula, aktualizace vrátí do klasického režimu – vypíše
„Režim databáze: delete“.

## Ukázková zpráva od AI

Na PythonAnywhere jazykový model neběží. Skutečný výstup modelu se sem dostane
takto: na laboratorním PC (se zapnutým LM Studiem) vytvořte u **ukázkového**
sportovce (FTVS-00xx, bez jména) zprávu, vydejte ji a spusťte
`ulozit-ukazku-zpravy.bat`. Po aktualizaci ukázky (`git pull`, `pa-update.sh`)
se objeví mezi zprávami jako `AI-…`. Zprávu sportovce se jménem příkaz odmítne.

## Pravidelné prodloužení

Bezplatná webová aplikace se musí **jednou měsíčně** prodloužit — na
záložce **Web** tlačítkem *Run until 1 month from today*. Týden předem
přijde upozornění e-mailem. Když to propásnete, aplikace se jen vypne; data zůstanou
a po prodloužení poběží dál.

## Když něco nejde

Záložka **Web** → dole odkazy na **Error log** a **Server log**. Poslední
řádky chybového logu obvykle řeknou přesně, co je špatně.

Nejčastější příčiny:

| Příznak | Příčina |
|---|---|
| *Something went wrong* | chyba v `.env` nebo ve WSGI souboru — viz Error log |
| *DisallowedHost* | v `.env` nesedí `DJANGO_ALLOWED_HOSTS` s adresou |
| stránka bez stylů | neproběhl `collectstatic` (krok 6) |
| nejde se přihlásit | heslo `admin` se bere z `.env` jen při prvním `bootstrap_demo`; změna pak `python manage.py changepassword admin`. Kolegovi pošle správce nový odkaz na stránce *Kolegové* |
| *Disk quota exceeded* | instalace bez `--no-cache-dir`; smažte `~/.cache/pip`; zálohy v `~/Zalohy-FTVS` (nechává se jich 10) |
| po aktualizaci chybí data | `bash deploy/pa-update.sh --obnovit` vrátí stav před poslední aktualizací |
| aplikace je prázdná a přidání sportu či sportovce skončí chybou | účet nemá vyplněnou organizaci; aktualizace ji doplní sama, jinak v administraci u uživatele vyberte organizaci |
| *Administrace genetiky* (nebo jiná nová část administrace) hlásí „nenalezeno“ | skupiny oprávnění rolí jsou ze starší verze; aktualizace je srovná sama, jinak `python manage.py seed_roles` (superuživatele se netýká) |

## Co tu nepoběží

- **PDF zpráv** — chybí systémové knihovny pro WeasyPrint. Aplikace zprávu
  ukáže v HTML a řekne to.
- **Jazykový model** — LM Studio tu neběží; souhrny zpráv píše šablona,
  ukázky od modelu se nahrávají z laboratorního PC (viz výše).

A hlavně: **reálná data sportovců sem nepatří.** Zkušební provoz je pro
smyšlená data. Provoz s reálnými daty patří na fakultní server.
