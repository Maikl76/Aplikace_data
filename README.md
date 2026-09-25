# Platforma pro funkční testování – FTVS UK

Sběr dat z přístrojů (force plate, dynamometrie, spiroergometrie, složení
těla), opakované měření sportovců v čase, srovnání s normami a vydávání
zprávy s doporučeními podloženými literaturou.

Zpráva se předává poskytovateli zdravotních služeb (AKESO) jako podklad.
**Data tečou jedním směrem ven** – platforma nikdy nedrží zdravotnickou
dokumentaci.

Nahrazuje původní Streamlit aplikaci, která zůstává v `legacy/`, dokud
nová platforma nepokryje všechno, co uměla.

## Rychlý start

### S Dockerem (doporučeno)

Takhle běží aplikace stejně jako na serveru — PostgreSQL, fronta úloh
i generování PDF.

```bash
cp .env.example .env          # doplňte DJANGO_SECRET_KEY
make build
make migrate
make seed                     # katalog + fiktivní data pro vývoj
make up                       # http://localhost:8000
```

Přihlášení po `make seed`: `admin` / `demo-heslo-1234` (jen pro vývoj).

Bez `make` jsou to tytéž příkazy přes
`docker compose run --rm web python manage.py <příkaz>`.

### Bez Dockeru, jen na prohlédnutí

Když se chcete na aplikaci jen podívat a nechcete instalovat Docker.
Data jdou do souboru SQLite místo PostgreSQL.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt

export DJANGO_SECRET_KEY=jen-na-prohlednuti      # Windows: set ...
export DATABASE_URL=sqlite:///db.sqlite3

python manage.py migrate
python manage.py seed_demo
python manage.py runserver         # http://localhost:8000
```

**Tohle je jen na prohlédnutí, ne na provoz.** SQLite se v typech chová
jinak než PostgreSQL a neumí pgvector, takže na něm nelze ověřit, že
aplikace poběží i v ostrém nasazení. Reálná data sem nepatří.

### Windows na dvojklik

| Soubor | Kdy |
|---|---|
| `zalozit.bat` | jednou na novém počítači: prostředí, knihovny, `.env`, databáze, ukázková data |
| `spustit.bat` | pokaždé: stáhne novou verzi (`git pull`), upraví databázi a spustí aplikaci |
| `ulozit-katalog.bat` | po změně katalogu v administraci: uloží ho do repozitáře a nahraje |
| `nacist-katalog.bat` | na druhém počítači: načte uložený katalog |

Postup pro práci na víc počítačích je v [docs/vice-pocitacu.md](docs/vice-pocitacu.md),
import z VALD v [docs/import-vald.md](docs/import-vald.md).

Generování PDF (`requirements/pdf.txt`) je záměrně bokem — WeasyPrint
potřebuje systémové knihovny, které se instalují nepříjemně. Bez něj
aplikace funguje a zprávu ukáže v HTML; PDF nevyrobí a řekne to.

## Zásady, které tvarují kód

**Vyvíjí se na syntetických datech.** Reálná data sportovců nepatří na
notebook – poprvé se objeví až na fakultním serveru. `seed_demo` vygeneruje
fiktivní sportovce; pro testování na reálných tvarech dat stávající Excely
nejdřív anonymizujte.

**Metrika je záznam v databázi, ne konstanta v kódu.** Nový test se zakládá
v administraci (`catalog`), ne editací slovníků a nasazením nové verze.

**Kvalifikátory nepatří do názvu metriky.** Strana, režim, rychlost a segment
jsou pole na `Measurement`. Díky tomu platí jedno pravidlo pro asymetrii
napříč všemi testy.

**Ukládají se pokusy, ne průměry.** Tři výskoky nesou jinou informaci než
jejich průměr. Raw export z přístroje se archivuje a nikdy nepřepisuje.

**Bez MDC se netvrdí zlepšení.** Změna, která nepřesáhne nejmenší
detekovatelnou změnu, je šum měření – a zpráva to takhle řekne.

**V provozních tabulkách není jméno.** Sportovec vystupuje pod pseudonymem;
identita žije šifrovaně v odděleném trezoru s vlastním oprávněním.

## Struktura

| Modul | Obsah |
|---|---|
| `apps/core` | organizace, uživatelé, role, audit, scoping |
| `apps/subjects` | sportovci, oddělená identita, souhlasy |
| `apps/catalog` | protokoly, metriky, normy – hlavní obyvatel administrace |
| `apps/measurements` | testovací dny, pokusy, měření, zdrojové soubory |
| `apps/ingest` | adaptéry na formáty přístrojů, staging, validace |
| `apps/analytics` | z-skóry, trendy, MDC/SWC, asymetrie |
| `apps/evidence` | knihovna vědeckých článků |
| `apps/rules` | pravidla jako data + nálezy |
| `apps/reports` | generování a předávání zpráv |
| `apps/external` | šev pro AKESO (jen omezení zátěže, žádné nálezy) |

Technologie: Django 5 + PostgreSQL + HTMX + Plotly, Celery/Redis na dlouhé
úlohy, S3/MinIO na zdrojové soubory, WeasyPrint na PDF.

Knihovny pro prohlížeč jsou v `static/vendor/`, ne z CDN — fakultní server
může být za firewallem bez přístupu do internetu a aplikace načítající
skripty z CDN by se tam nespustila. Podrobnosti a postup aktualizace jsou
v `static/vendor/README.md`.

## Migrace dat z původní aplikace

Excel ze Streamlit aplikace se importuje buď přes webové rozhraní
(**Import** v menu), nebo z příkazové řádky:

```bash
python manage.py import_legacy data/historical_data.xlsx            # jen náhled
python manage.py import_legacy data/historical_data.xlsx --commit   # uložení
```

Obojí jde stejnou pipeline: soubor → staging → kontrola → uložení. Do
provozních tabulek se nic nezapíše, dokud náhled nepotvrdíte.

Co se při tom děje:

- **Sloupce se rozloží na kvalifikátory.** Osm sloupců typu
  `Vnitrni rotace koncentricka (210°/s)` jsou ve skutečnosti dvě metriky ×
  dva režimy × dvě rychlosti. Mapování je v `apps/catalog/seed_data.py`
  (`LEGACY_COLUMN_MAP`).
- **Jména se neukládají.** Sportovec dostane pseudonymní kód `FTVS-nnnn`
  a hash identifikace, díky kterému se příští import téže osoby spáruje.
  Staging drží jméno jen pro náhled a po uložení se maže.
- **Nezmapované sloupce se ohlásí.** Tiše zahozený sloupec je při migraci
  to nejhorší, co se může stát.
- **Hodnoty mimo věrohodný rozsah se uloží označené**, ne zahozené — chyba
  přístroje je taky informace. Volitelně je lze přeskočit.
- **Stejný soubor podruhé neprojde** (otisk obsahu). Nedokončený náhled se
  ale znovu otevře, místo aby blokoval.

Jedno omezení, které nejde obejít: **původní formát nerozlišoval stranu.**
Historická data se proto importují bez strany a asymetrii z nich spočítat
nelze. Nová měření už stranu nesou.

## Administrace

`http://localhost:8000/admin/` — správa všeho, co se nedělá v běžném provozu.

Po prvním nasazení spusťte jednou:

```bash
python manage.py seed_roles     # skupiny oprávnění pro role
```

### Nový test

1. **Katalog → Metriky** — založit metriky, které test produkuje (kód,
   jednotka, žádoucí směr, MDC/SWC, věrohodný rozsah).
2. **Katalog → Protokoly** — založit protokol a dole v tabulce k němu
   přidat metriky i s kvalifikátory: `sides` `["L","R"]`, `modes`
   `["con","ecc"]`, `speeds` `[210, 300]`, `segments`.

Zadávací obrazovka pro ten test vznikne sama — nic se neprogramuje.

### Lidé a přístup

**Uživatelé → Přidat.** Role se nastavuje rovnou při zakládání a skupina
oprávnění se přiřadí sama:

| Role | Co smí |
|---|---|
| **Správce** | vše včetně uživatelů |
| **Diagnostik** | zadávat a opravovat měření, importovat, vydávat zprávy; **nesmí mazat** |
| **Výzkumník** | jen číst; identitu sportovců nevidí |

Do administrace se dostane jen uživatel s příznakem **„Stav týmu"**
(`is_staff`).

**Trenéři a sportovci sem nepatří.** Administrace Djanga umí oprávnění na
úrovni modelu, ne řádku — trenér by v ní viděl všechny týmy. Pracují proto
v samotné aplikaci, která hlídá, na čí data vidí.

### Mazání sportovce

Sportovce s naměřenými daty databáze smazat nedovolí a je to záměr:
v longitudinálních datech by chyběl navždy. Místo toho **Deaktivovat** —
zmizí ze seznamů, data zůstanou.

Pro **výmaz podle GDPR** smažte jeho záznam v *Identity sportovců*. Měření
pak zůstanou, ale už je nelze spojit s konkrétní osobou — což je u
výzkumných dat obvykle to, co se po výmazu požaduje.

## Zadávání u přístroje

**Měření → Nový testovací den → přidat protokol → zadat hodnoty.**

Zadávací mřížka se **generuje z definice protokolu**, ne z kódu. Protokol
v katalogu říká, jaké kombinace se u něj měří:

```
ProtocolMetric(metric=shoulder_ir_torque,
               sides=["L","R"], modes=["con","ecc"], speeds=[210,300])
```

Z toho vznikne 8 řádků × počet pokusů. Nový protokol založený v administraci
tedy dostane obrazovku sám, bez psaní formuláře.

Obrazovka počítá s tabletem u přístroje: velká pole, číselná klávesnice
(`inputmode="decimal"`), čárka i tečka jako oddělovač, tlačítko pro uložení
drží dole. Hodnota mimo věrohodný rozsah se uloží **označená**, stejně jako
při importu.

## Grafy

Karta sportovce ukazuje vývoj klíčových metrik a asymetrii z posledního
měření. Figury se skládají v Pythonu (`apps/analytics/charts.py`) a do
prohlížeče jdou jako JSON, kde je vykreslí plotly.js.

Tři rozhodnutí, která stojí za vysvětlení:

- **Osa pokrývá aspoň trojnásobek MDC.** Useknutá osa je nejsnazší způsob,
  jak z grafu udělat lež — kolísání v řádu chyby měření by jinak vypadalo
  jako dramatický vývoj.
- **Asymetrie se vynáší v procentech, ne v absolutních hodnotách.** Newtony
  z IMTP a bezrozměrný poměr IR/ER na jedné ose znamenají, že je vidět jen
  ta největší veličina a zbytek splyne s nulou.
- **Směr nese poloha, ne barva.** Červená u pravé strany by znamenala „pravá
  je špatně“, což není pravda. Barvou se hlásí jen překročený práh a je to
  navíc napsané v tabulce pod grafem.

Paleta prošla kontrolou na odlišitelnost při barvosleposti a na kontrast
vůči podkladu v obou režimech.

## Doporučení a zprávy

Doporučení vzniká ve třech vrstvách a v tomhle pořadí:

1. **Pravidla** (`apps/rules`) — deterministická, jediné místo, kde vznikají
   čísla. Podmínka je JSON v databázi, ne kód:

   ```json
   {"metric": "ir_er_ratio", "op": "<", "value": 1.0, "where": {"speed": 210}}
   {"asymmetry": "*", "op": ">", "value": 10}
   {"change": "cmj_height", "op": "<", "value": 0, "require_mdc": true}
   {"z": "vo2max", "op": "<", "value": -1.0}
   ```

2. **Evidence** (`apps/rules/evidence.py`) — citace visí na pravidle, ne na
   volném textu, takže je u každého tvrzení dohledatelné, odkud se vzalo.
   Neschválený článek se do zprávy nedostane a neshoda populace se hlásí.

3. **Text** (`apps/reports/narrative.py`) — lokální jazykový model (Ollama)
   z hotových faktů napíše souvislý český souhrn. Nic nepočítá ani
   nehodnotí; `verify_numbers()` po generování zkontroluje, že každé číslo
   v textu pochází z dat, a jinak použije šablonu. Bez modelu se text
   skládá ze šablon. Návod v [`docs/lokalni-ai.md`](docs/lokalni-ai.md).

**Kontraindikace.** Pravidlo může mít `{"load_restriction": true}` — pokud má
sportovec platné omezení zátěže z `external.ExternalExam`, doporučení se
nevydá. Nález se ale nezahazuje: uloží se s důvodem, aby bylo doložitelné,
že pravidlo sedělo a proč se nic nedoporučilo.

**Vydání je nevratné.** Koncept → vydání (vědomý krok) → předání. Vydanou
zprávu nelze upravit; oprava se řeší novou verzí, která tu starou nahrazuje.
Bez platného souhlasu (`Consent.Scope.REPORT_HANDOVER`) se zpráva nepředá.
Ke každé se ukládá otisk vstupů a verze pravidel, takže jde zpětně
zrekonstruovat, proč říká to, co říká.

Vedle PDF vzniká **strojově čitelná příloha** (JSON) s nálezy, hodnotami
a citacemi. Když ji přijímající systém neumí, nic se neděje; až umět bude,
načte si hodnoty rovnou.

Ukázková pravidla se zakládají **neaktivní**. Prahy v nich jsou ilustrativní
a nemají citace — zapnout je smí až člověk, který za ně ručí.

## Stav

Hotové:

- datový model, administrace katalogu, scoping podle organizace
- analytická vrstva (MDC/SWC, asymetrie, výběr normy)
- import z původního Excelu: adaptér, staging s kontrolou, web i příkaz
- zadávání měření generované z definice protokolu, uzpůsobené tabletu
- grafy na kartě sportovce
- pravidla, evidence, generování a vydávání zpráv
- Docker pro vývoj i provoz, 71 testů

Další kroky:

1. **Inventář metrik** — projít reálné exporty z přístrojů, doplnit katalog
   a hlavně MDC/SWC z literatury (`seed_catalog` je schválně nechává prázdné)
2. **Normy a pravidla** — naplnit `catalog.Norm` a ověřit prahy v pravidlech,
   připojit k nim literaturu; teprve pak je zapnout
3. **Adaptéry na přístroje** — `apps/ingest/adapters/`, kostra i registr jsou
   hotové; přidat ForceDecks, Biodex/HUMAC, Cosmed
4. **Generování textu na pozadí** — s modelem na CPU trvá souhrn desítky
   sekund; pro provoz přesunout do Celery

## Vývoj

```bash
make test     # pytest
make lint     # ruff
make logs
```

## Nasazení

**Ukázka pro kolegy** — jen vygenerovaná data, zapnutý `DEMO_MODE`
(varovný pruh na každé stránce, vypnuté nahrávání souborů):

- **PythonAnywhere** — zdarma, bez platební karty, server v EU. Postup
  v [`deploy/pythonanywhere.md`](deploy/pythonanywhere.md).
- **Fly.io** — placené podle využití (jednotky dolarů měsíčně), plný
  Docker včetně PDF. Postup v [`deploy/fly.md`](deploy/fly.md).

**Vlastní server:**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Před nasazením na fakultní server ověřte s IT:

- virtuální server se **správou OS a zálohováním** (ne fyzický stroj ve vaší režii)
- zálohu **mimo budovu** – `deploy/backup.sh` je jen dump, PITR vyžaduje archivaci WAL
- přístup zvenčí: VPN, nebo publikovaná služba s TLS
- zda je povinné **univerzitní přihlašování** (CAS/Shibboleth) – ovlivní autentizaci
- zda je Docker povolený

Zálohy obsahují tatáž citlivá data jako databáze – šifrujte je.
Jednou za čtvrt roku obnovu vyzkoušejte.

## Ochrana osobních údajů

Zpracovávají se údaje o zdraví (zvláštní kategorie podle čl. 9 GDPR).
Před nasazením s reálnými daty je potřeba vyřešit s pověřencem FTVS:
posouzení vlivu (DPIA), členěné souhlasy, retenční politika, role
a auditní přístupy. Model je na to připravený (`Consent`, `AuditLog`,
oddělená identita), ale technika nenahrazuje rozhodnutí.
