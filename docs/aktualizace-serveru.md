# Úpravy a aktualizace aplikace na serveru

Jak bude aplikace žít, až poběží na fakultním serveru: kde se vyvíjí, jak se
nová verze vyzkouší a jak se nahraje na server, aby o data nikdo nepřišel.

## Tři místa, tři role

| Kde | K čemu | Data |
|---|---|---|
| **Vývoj** – laboratorní PC / notebook | nové funkce, opravy, zkoušení | vymyšlená ukázková data |
| **Ukázka** – PythonAnywhere | vyzkoušet a předvést novou verzi kolegům, než jde do provozu | vymyšlená data |
| **Provoz** – fakultní server | skutečná práce laboratoří | **skutečná data – jen tady** |

Data se nikdy nepřenášejí z vývoje na server ani zpět. Na server se nahrává
jen **nová verze aplikace** (kód). Katalog (MDC, pravidla, baterie, nabídka)
se po spuštění provozu upravuje **přímo na serveru** v aplikaci.

## Verze = větve na GitHubu

- **Pracovní větev** (teď `claude/redesign-testing-recommendations-app-o29wru`):
  sem přibývají úpravy. Z ní se aktualizuje vývoj i ukázka.
- **`main`**: jen vyzkoušené verze. **Server běží vždy z `main`.**
- Vydaná verze dostane označení (tag), např. `v1.0`, `v1.1` – kdykoli se
  na ni jde vrátit.

## Cesta jedné úpravy

1. **Úprava** – v pracovní větvi (se mnou nebo s kýmkoli dalším).
2. **Vyzkoušení** – lokálně (`spustit.bat`) a na ukázce (PythonAnywhere,
   `pa-update.sh`). Automatické testy běží při každé změně.
3. **Vydání** – pracovní větev se na GitHubu sloučí do `main` (pull request,
   schválíte ho vy) a označí se verzí, např. `v1.1`.
4. **Nasazení** – na serveru jeden příkaz (níže). Laboratořím dát vědět,
   že aplikace bude asi minutu nedostupná.

## Nasazení na server

Přihlásit se na server (SSH, dá IT) a ve složce aplikace:

```
bash deploy/server-update.sh
```

Skript sám:

1. **zálohuje databázi** (`deploy/backup.sh`),
2. stáhne verzi z `main` (nebo zadanou: `bash deploy/server-update.sh v1.1`),
3. sestaví aplikaci,
4. **upraví databázi** na novou verzi (migrace – data zůstávají) a doplní do
   katalogu nové testy, aniž by přepsal úpravy z administrace,
5. restartuje,
6. **ověří, že aplikace odpovídá** – když ne, řekne to a nabídne návrat.

## Návrat

```
bash deploy/server-update.sh --zpet
```

vrátí předchozí verzi aplikace. Pokud nová verze stihla změnit databázi
(a laboratoře mezitím nic nezadaly), obnoví se i záloha z kroku 1:

```
docker compose exec -T db pg_restore -U ftvs -d ftvs --clean < /var/backups/ftvs/ftvs-DATUM.dump
```

Když už laboratoře mezitím pracovaly, zálohu **neobnovovat** (přišly by
o nová data) – chybu raději opravit novou verzí.

## Pravidla, která drží data v bezpečí

- **Změny databáze jsou jen „přidávací“.** Nový sloupec nebo tabulka se
  přidá, stará data zůstanou. Každá úprava databáze má test.
- **Před každou aktualizací záloha**, denní zálohy běží zvlášť (cron).
- **Na serveru se nic neprogramuje** – jen se nasazuje vyzkoušená verze.
- **Šifrovací klíč** (`IDENTITY_ENCRYPTION_KEY` v `.env` na serveru) se nikdy
  nemění a zálohuje se zvlášť od databáze. Bez něj nejdou přečíst jména.

## Kdo co dělá

| Úkol | Kdo |
|---|---|
| server, HTTPS, zálohy mimo budovu, SSH přístup | IT fakulty |
| schválení nové verze (sloučení do `main`) | vedoucí laboratoře / vy |
| spuštění `server-update.sh` | kdo má přístup na server (vy nebo IT) |
| katalog, nabídka, termíny, uživatelé | správce v aplikaci |
