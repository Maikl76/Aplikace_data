# Ukázka na PythonAnywhere

Bezplatný hosting **bez platební karty** na evropském serveru. Slouží
k tomu, aby se kolegové mohli na aplikaci podívat. Běží v ní jen
vygenerovaná data a má zapnutý ukázkový režim (varovný pruh, vypnuté
nahrávání souborů).

Výsledná adresa: `https://JMENO.eu.pythonanywhere.com`

Všude níže nahraďte **JMENO** svým uživatelským jménem na PythonAnywhere.

---

## 1. Účet

Zaregistrujte se na **https://eu.pythonanywhere.com** — pozor na `eu.`,
jen tak budou data v EU. Zvolte bezplatný účet (*Beginner*). Platební
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
mkvirtualenv --python=/usr/bin/python3.11 ftvs
```

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
`admin` heslem z kroku 5. Nahoře musí být oranžový pruh **UKÁZKA**.

---

## Aktualizace po změnách

V Bash konzoli:

```
bash ~/Aplikace_data/deploy/pa-update.sh
```

Stáhne novou verzi, doinstaluje, co je potřeba, a restartuje aplikaci.
Data zůstanou.

## Pravidelné prodloužení

Bezplatná webová aplikace se musí jednou za čas prodloužit — na záložce
**Web** tlačítkem *Run until …*. PythonAnywhere předem pošle upozornění
e-mailem. Když to propásnete, aplikace se jen vypne; data zůstanou
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
| nejde se přihlásit | heslo se bere z `.env` jen při prvním `bootstrap_demo`; změna pak v administraci nebo `python manage.py changepassword admin` |
| *Disk quota exceeded* | instalace bez `--no-cache-dir`; smažte `~/.cache/pip` |

## Co tu nepoběží

- **PDF zpráv** — chybí systémové knihovny pro WeasyPrint. Aplikace zprávu
  ukáže v HTML a řekne to.
- **Nahrávání souborů** — vypnuté záměrně (ukázkový režim).

A hlavně: **reálná data sportovců sem nepatří.** Ukázka je pro
vygenerovaná data. Provoz s reálnými daty patří na fakultní server.
