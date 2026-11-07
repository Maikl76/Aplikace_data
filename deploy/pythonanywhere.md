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
`rodic`, `trener`, `metodik`) a restartuje aplikaci. **Data zůstanou** – účty, zprávy,
cokoli jste v ukázce zadali. Pak v prohlížeči **Ctrl+F5**.

`git pull` zvlášť předem je důležitý: skript se při stahování sám mění
a bash by jinak dojel starou verzi.

### Denní údržba (plánovaná úloha)

Na záložce **Tasks** založte denní úlohu (čas podle sebe, třeba 03:00):

```
~/.virtualenvs/ftvs/bin/python ~/Aplikace_data/manage.py udrzba --jednou
```

Jednou denně zazálohuje databázi a nahrané soubory do `~/Zalohy-FTVS/denni`
(posledních 7), smaže staré nedokončené importy, rozešle připomínky měření
a v pondělí pošle správci e‑mail se stavem (jen s nastaveným poštovním
serverem). Bez úlohy to jako pojistka udělá první otevření Přehledu v daný
den. Stav je v aplikaci v *Nastavení → Provoz a zálohy*. Volné účty mají
jednu plánovanou úlohu – tahle nahrazuje dřívější `pripomenout_mereni`.

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

## Jazykový model ve zkušebním provozu (Gemini)

Lokální model na PythonAnywhere neběží. Aby si kolegové mohli vyzkoušet
i souhrny a návrhy doporučení od modelu, jde použít cloudový **Gemini**
s klíčem z Google AI Studia. Souhrny tím opouštějí pracoviště – aplikace
posílá jen kódy a čísla, nikdy jména, a ve zkušebním provozu jsou jen
smyšlená data. Mimo zkušební provoz (na fakultě je `DEMO_MODE` vypnutý)
aplikace cloudový model odmítne; tam zůstává model lokální.

1. V [Google AI Studiu](https://aistudio.google.com/) vytvořte API klíč.
   Placení nezapínejte: bezplatná úroveň stačí, jen má denní a minutový
   limit požadavků. Při jeho překročení aplikace ukáže chybu modelu
   a souhrn zůstane ze šablony. U bezplatné úrovně může Google data
   z požadavků používat ke zlepšování svých služeb – další důvod, proč sem
   patří jen smyšlená data.
2. V konzoli ověřte, že PythonAnywhere adresu pustí ven (bezplatný účet
   pouští jen vyjmenované adresy; `KLIC` nahraďte svým klíčem):

   ```
   curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer KLIC" https://generativelanguage.googleapis.com/v1beta/openai/models
   ```

   `200` = v pořádku. `403` od proxy znamená, že adresa na seznamu není;
   PythonAnywhere ji na požádání doplní (formulář *Request a whitelist
   addition* na stránce nápovědy k přístupu na internet).
3. Do `.env` doplňte řádky ze šablony `deploy/pythonanywhere.env.example`
   (oddíl o jazykovém modelu): `LLM_ENABLED=True`, `LLM_BASE_URL`,
   `LLM_API_KEY`, `LLM_MODEL`, `LLM_BACKGROUND=False`, `LLM_TIMEOUT=90`.
   Klíč do gitu nepatří, `.env` v něm není.
4. Na záložce **Web** aplikaci restartujte (*Reload*). V aplikaci otevřete
   *Zprávy → AI zprávy → Modely*: seznam modelů přijde z Gemini, vyberte
   výchozí (např. `gemini-2.5-flash`). Oranžový pruh *Cloudový model* tam
   připomíná, že souhrny opouštějí pracoviště.
5. Zkouška: v konzoli `~/.virtualenvs/ftvs/bin/python manage.py llm_check`
   pošle modelu dvě čísla a ukáže odpověď.

Zpět na lokální model nebo úplné vypnutí: řádky v `.env` smažte nebo
nastavte `LLM_ENABLED=False` a aplikaci restartujte.

## Ukázková zpráva od AI

Když cloudový model nastavený není, skutečný výstup modelu se sem dostane
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
- **Lokální jazykový model** — LM Studio tu neběží; buď souhrny píše šablona
  a ukázky od modelu se nahrávají z laboratorního PC, nebo se pro zkušební
  provoz nastaví cloudový Gemini (viz výše).

A hlavně: **reálná data sportovců sem nepatří.** Zkušební provoz je pro
smyšlená data. Provoz s reálnými daty patří na fakultní server.
