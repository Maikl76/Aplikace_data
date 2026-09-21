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

```bash
cp .env.example .env          # doplňte DJANGO_SECRET_KEY
make build
make migrate
make seed                     # fiktivní data pro vývoj
make up                       # http://localhost:8000
```

Přihlášení po `make seed`: `admin` / `demo-heslo-1234` (jen pro vývoj).

Bez Dockeru:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt
# Postgres musí běžet, viz DATABASE_URL v .env
python manage.py migrate && python manage.py seed_demo
python manage.py runserver
```

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

## Stav

Hotová je kostra: datový model, administrace katalogu, analytická vrstva
(MDC/SWC, asymetrie), přehled a karta sportovce, Docker pro vývoj i provoz.

Další kroky:

1. **Inventář metrik** – projít reálné exporty z přístrojů a doplnit katalog
   včetně MDC/SWC z literatury
2. **Importní adaptéry** – `apps/ingest/adapters/`, začít izokinetikou
   a složením těla (existují reálná data)
3. **Obrazovka testovacího dne** – zadávání na tabletu u přístroje
4. **Migrace historických dat** z `legacy/` Excelů
5. **Pravidla, evidence a generování zpráv**

## Vývoj

```bash
make test     # pytest
make lint     # ruff
make logs
```

## Nasazení

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
