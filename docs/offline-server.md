# Server bez internetu – instalace a aktualizace z flash disku

Když fakultní server nesmí na internet, nová verze se na něj nenahrává
přes `git pull`, ale přenese se **jeden soubor na flash disku**. Balíček
obsahuje všechno, co server potřebuje: aplikaci, databázi PostgreSQL,
HTTPS bránu a instalační skript. Server nic nestahuje.

```
GitHub (vydání v1.1) ──stáhnout──▶ flash disk ──▶ server: jeden příkaz
```

## Co musí mít server (jednou zařídí IT)

- Linux (Ubuntu / Debian / RHEL) s **Dockerem a Docker Compose**. Docker
  se na server bez internetu instaluje z balíčků – to je běžná práce IT.
- Místo na disku: ~5 GB pro aplikaci a zálohy, s jazykovým modelem ~10 GB.
- **Adresu v síti fakulty** (např. `diagnostika.ftvs.cuni.cz`), kterou budou
  laboratoře psát do prohlížeče, a otevřené porty 80 a 443 z laboratoří.
- **Certifikát pro HTTPS** od IT (dva soubory: certifikát a klíč). Bez něj
  si server vyrobí vlastní a prohlížeče v laboratořích jednou ukážou
  varování – viz [HTTPS](#https).
- Přístup přes SSH pro toho, kdo bude instalovat (vy nebo IT).

## 1. Stáhnout balíček

**Z vydání (doporučeno):** Na GitHubu → *Releases* → vybrat verzi (např.
`v1.1`) → stáhnout `ftvs-v1.1.tar.gz` (stovky MB).

Vydání vznikne samo, jakmile se verze v `main` označí – na GitHubu
*Releases → Draft a new release → Choose a tag → napsat `v1.1` → Publish*.
Asi za 10 minut se k vydání přiloží balíček (průběh: záložka *Actions*).

**Na zkoušku z libovolné větve:** *Actions → Balíček pro server bez
internetu → Run workflow*, vybrat větev, zadat označení. Hotový balíček je
dole na stránce běhu v části *Artifacts* (zabalený v .zip – rozbalit).

**Bez GitHubu:** na počítači s Dockerem a internetem
`bash deploy/offline/sestavit-balicek.sh v1.1` → `dist/ftvs-v1.1.tar.gz`.

## 2. Flash disk

Zkopírovat `ftvs-v1.1.tar.gz` na flash disk. Disk ve formátu **exFAT**
(FAT32 neunese soubory nad 4 GB – u jazykového modelu by to vadilo).
Balíček obsahuje kontrolní součty; poškozený soubor instalace pozná a odmítne.

## 3. První instalace

Na serveru (flash disk bývá připojený v `/media/…`):

```
tar -xzf /media/usb/ftvs-v1.1.tar.gz --wildcards '*/nainstalovat-vydani.sh' --strip-components=1
```

```
sudo bash nainstalovat-vydani.sh /media/usb/ftvs-v1.1.tar.gz
```

Skript se zeptá na **adresu serveru**, vytvoří `/opt/ftvs/.env` a sám v něm
vygeneruje hesla a klíč k šifrovaným jménům. Pak založí databázi, katalog
testů a role a aplikaci spustí. Nakonec vypíše příkaz pro založení účtu
správce – spustit ho a zadat jméno a heslo.

> **Hned potom zazálohujte `/opt/ftvs/.env`** (jinam než na server – např.
> na šifrovaný disk v trezoru). Je v něm klíč k jménům sportovců: bez něj
> nejdou jména přečíst ani ze zálohy databáze.

Pak v prohlížeči v laboratoři otevřít `https://<adresa serveru>`, přihlásit
se správcem a v aplikaci založit organizaci, laboratoře a uživatele.

## 4. Aktualizace na novou verzi

Nový balíček na flash disk a na serveru:

```
sudo bash /opt/ftvs/aktualni/nainstalovat-vydani.sh /media/usb/ftvs-v1.2.tar.gz
```

Skript sám:

1. zkontroluje balíček a načte programy do Dockeru,
2. **zálohuje databázi** (`/opt/ftvs/zalohy/`),
3. přepne na novou verzi, **upraví databázi** (data zůstávají) a doplní do
   katalogu nové testy – úpravy z administrace nepřepíše,
4. spustí aplikaci a **ověří, že odpovídá**.

Aplikace je asi minutu nedostupná – dát laboratořím vědět. Na serveru
zůstávají tři poslední verze, starší se smažou.

## 5. Když se něco pokazí – návrat

```
sudo bash /opt/ftvs/aktualni/nainstalovat-vydani.sh --zpet
```

vrátí předchozí verzi aplikace. Pokud nová verze stihla změnit databázi
**a laboratoře mezitím nic nezadaly**, obnovit i zálohu z kroku 2:

```
sudo bash /opt/ftvs/aktualni/nainstalovat-vydani.sh --obnovit /opt/ftvs/zalohy/ftvs-DATUM-pred-v1.2.dump
```

Když už laboratoře pracovaly, zálohu **neobnovovat** (přišly by o nová
data) – chybu raději opravit další verzí.

## Zálohy

Před každou aktualizací se záloha dělá sama. Denní zálohu nastaví IT
(soubor `/etc/cron.d/ftvs`, jeden řádek):

```
30 2 * * * root bash /opt/ftvs/aktualni/nainstalovat-vydani.sh --zaloha
```

Denní zálohy starší než 30 dní se mažou samy. Složku `/opt/ftvs/zalohy`
má IT kopírovat **mimo server** (jiná budova, páska) – záloha na stejném
disku neochrání před jeho poruchou.

## Stav

```
sudo bash /opt/ftvs/aktualni/nainstalovat-vydani.sh --stav
```

ukáže běžící verzi, stav částí aplikace a počet záloh.

## Jazykový model (AI zprávy) – jednou

Model má několik GB a přenáší se **jen jednou**; aktualizace aplikace ho
nemění.

1. Na GitHubu: *Actions → Balíček pro server bez internetu → Run workflow*,
   do pole *jazykový model* napsat `gemma3:4b`. Za 20–40 minut vznikne
   vydání **„Jazykový model gemma3:4b“** se soubory `…part-00`, `…part-01`
   (GitHub dovolí nejvýš 2 GB na soubor, proto části).
   Bez GitHubu: `bash deploy/offline/pripravit-ai-balicek.sh gemma3:4b`.
2. **Všechny části** na flash disk do jedné složky.
3. Na serveru (stačí zadat první část, ostatní si skript najde):

   ```
   sudo bash /opt/ftvs/aktualni/nainstalovat-vydani.sh --ai /media/usb/ftvs-ai-gemma3-4b.tar.gz.part-00
   ```

Skript model nainstaluje, zapne ho v `.env` a spustí. Na serveru bez
grafické karty píše model zprávu i několik minut – aplikace na něj počká
nejvýš 5 minut a ostatní laboratoře mezitím normálně pracují. Grafickou kartu v Dockeru zprovozní IT (NVIDIA
Container Toolkit).

## HTTPS

- **S certifikátem od IT** (doporučeno): soubory uložit jako
  `/opt/ftvs/certs/cert.pem` a `/opt/ftvs/certs/key.pem`, v `/opt/ftvs/.env`
  odkomentovat řádek `FTVS_TLS=/certs/cert.pem /certs/key.pem` a spustit
  aktualizaci znovu se stejným balíčkem (nebo `--zpet` a znovu).
- **Bez certifikátu** si server vyrobí vlastní. Prohlížeče mu nevěří,
  dokud se na počítače v laboratořích nenainstaluje jeho kořenový
  certifikát (IT ho najde ve svazku Dockeru `ftvs_caddydata`,
  `caddy/pki/authorities/local/root.crt`, a rozdá přes doménu).

## Kde co je

| Cesta | Obsah |
|---|---|
| `/opt/ftvs/.env` | nastavení, hesla, **klíč k jménům** – zálohovat zvlášť |
| `/opt/ftvs/aktualni` | běžící verze (odkaz do `verze/`) |
| `/opt/ftvs/verze/` | poslední tři verze |
| `/opt/ftvs/zalohy/` | zálohy databáze |
| `/opt/ftvs/certs/` | certifikát od IT |
| `/opt/ftvs/ai/` | jazykový model |
| svazky Dockeru `ftvs_pgdata`, `ftvs_media` | **databáze a nahrané soubory** |

Svazky Dockeru přechod na jinou verzi nemění. Smazat by je šlo jen ručně
(`docker volume rm`) – to nikdy nedělat bez zálohy.

## Když server přece jen smí na internet

Stačí mu přístup na GitHub (jen odchozí, nic se na server zvenku neotevírá).
Pak se aktualizuje bez flash disku jedním příkazem – viz
[aktualizace-serveru.md](aktualizace-serveru.md). Zeptejte se IT, jestli to
jde; flash disk je pak zbytečný.
