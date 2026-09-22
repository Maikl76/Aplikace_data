# Nasazení ukázky na Fly.io

Veřejná instance, na kterou se podívají kolegové. **Běží v ní jen
vygenerovaná data**, má zapnutý `DEMO_MODE` a nahrávání souborů odmítá.
Ostrý provoz s reálnými daty patří na fakultní server, ne sem.

## Jednou: příprava

Nainstalujte `flyctl` a přihlaste se:

```bash
# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex
# macOS / Linux
curl -L https://fly.io/install.sh | sh

fly auth signup     # nebo fly auth login
```

## 1. Založení aplikace

V `fly.toml` změňte `app` na svůj název (musí být globálně unikátní,
např. `ftvs-testovani-vagner`), pak:

```bash
fly launch --no-deploy --copy-config
```

Region nechte `fra` (Frankfurt) — je v EU a nejblíž.

## 2. Databáze

```bash
fly postgres create --name ftvs-testovani-db --region fra
fly postgres attach ftvs-testovani-db
```

Druhý příkaz nastaví `DATABASE_URL` sám. Pokud vám `flyctl` nabídne jiný
postup (nabídka služeb se mění), řiďte se jím — podstatné je, aby
aplikace měla v proměnné `DATABASE_URL` spojení na PostgreSQL v EU.

## 3. Tajemství

```bash
fly secrets set \
  DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  DJANGO_ALLOWED_HOSTS="ftvs-testovani.fly.dev" \
  DJANGO_CSRF_TRUSTED_ORIGINS="https://ftvs-testovani.fly.dev" \
  DEMO_ADMIN_PASSWORD="<zvolte dlouhé heslo>"
```

Název domény nahraďte tím svým. `DEMO_ADMIN_PASSWORD` je heslo správce
v ukázce — **bez něj se účet nezaloží**, což je záměr: instance na veřejné
adrese nesmí mít účet se známým heslem.

## 4. Disk na soubory

```bash
fly volumes create ftvs_media --region fra --size 1
```

Drží vygenerovaná PDF mezi nasazeními. Pro ostrý provoz sem patří
objektové úložiště (`USE_S3`), ne disk vázaný na jeden stroj.

## 5. Nasazení

```bash
fly deploy
```

Migrace se pustí automaticky před spuštěním (`release_command`).

## 6. Naplnění ukázkovými daty

```bash
fly ssh console -C "python manage.py seed_catalog"
fly ssh console -C "python manage.py seed_roles"
fly ssh console -C "python manage.py seed_demo --subjects 30 --sessions 4"
```

Hotovo — adresa je `https://<název>.fly.dev`, přihlášení `admin`
a heslo, které jste nastavil v kroku 3.

## Provoz

```bash
fly logs                  # co se děje
fly status                # stav strojů
fly ssh console           # shell uvnitř
fly deploy                # nasazení po změnách
```

Aplikace je nastavená tak, aby se při nečinnosti uspala
(`auto_stop_machines`). První načtení po pauze proto chvíli trvá; za
provoz se pak neplatí.

## Na co si dát pozor

- **Nikdy sem nevkládejte reálná data sportovců.** Nahrávání je vypnuté,
  ale zadat měření ručně v aplikaci jde. Je to ukázka, ne evidence.
- Databáze tu **nemá zálohy nastavené vámi**. Je to ukázka; o data v ní
  nemá jít.
- Než sem pustíte kohokoli mimo tým, projděte s pověřencem, co se tam
  bude dít — i vygenerovaná data mohou dostat reálné jméno, když je tam
  někdo zadá.
