# Provoz a zálohy: denní údržba

Aplikace si jednou denně sama udělá údržbu, aby provoz nestál na tom, že
si někdo vzpomene. Co a kdy naposledy proběhlo, je v **Nastavení →
Provoz a zálohy**; krok *Provoz a zálohy* ve Stavu pracoviště hlásí, co
nesedí (stará nebo chybějící záloha, málo místa, údržba neběží).

## Co údržba dělá

1. **Záloha** databáze, nahraných souborů (`media`: exporty, PDF, souhlasy)
   a souboru `.env` s klíči – jen u databáze SQLite, tedy na laboratorním
   počítači a ve zkušebním provozu na PythonAnywhere. Ukládá do
   `BACKUP_DIR/denni` (bez nastavení `Zalohy-FTVS/denni` ve vašem
   profilu), nechává posledních `BACKUP_KEEP_DAILY` (výchozí 7). Zálohy
   před aktualizací (`pa-update.sh`, `zalohovat.bat`) leží o složku výš
   a mají vlastní limit. Server s PostgreSQL zálohuje `deploy/backup.sh`
   z cronu – tam se tento krok přeskočí.
2. **Úklid starých importů**: nedokončené a zrušené importy starší než
   30 dní se smažou i se souborem (uložené importy nikdy).
3. **Připomínky dalšího měření** (totéž, co dělal Přehled a příkaz
   `pripomenout_mereni`): e‑mail sportovcům, kterým se blíží termín.
4. **Stav správci e‑mailem** jednou týdně (`STATUS_MAIL_WEEKDAY`,
   0 = pondělí): za posledních 7 dní počty testovacích dnů, vydaných
   zpráv, nových sportovců a importů; co čeká (koncepty, importy na
   kontrolu, připomínky kolegů, kdo je na řadě); záloha, místo na disku,
   chyby (importy, které nešly načíst; selhaná záloha), jazykový model,
   hlídač sledované složky. **Bez jmen a výsledků sportovců.** Jde
   správcům pracoviště, kteří mají v účtu e‑mail; bez poštovního serveru
   (`EMAIL_HOST`) neodejde a stav je jen v aplikaci.

## Kde běží

| Prostředí | Jak |
|---|---|
| Laboratorní počítač (Windows) | `spustit.bat` otevře okno *Denni udrzba* (`manage.py udrzba`), které běží dokola a každý den to udělá jednou – hned po startu, když dnes ještě neproběhla. Okno nechte otevřené jako to hlavní. |
| PythonAnywhere | plánovaná úloha (*Tasks* → denní): `~/.virtualenvs/ftvs/bin/python ~/Aplikace_data/manage.py udrzba --jednou` – zálohuje do `~/Zalohy-FTVS/denni`. Nahrazuje dřívější úlohu `pripomenout_mereni`. |
| Server (PostgreSQL) | cron: `manage.py udrzba --jednou` jednou denně (úklid, připomínky, stav); zálohu dělá `deploy/backup.sh`. |
| Pojistka | Když nic z toho neběží, údržbu spustí první otevření Přehledu v daný den (`MAINTENANCE_IN_WEB=True`). Záloha pak proběhne během načtení stránky – u velké databáze to chvíli trvá, proto je lepší mít příkaz. |

Ručně: v *Provoz a zálohy* má správce tlačítka **Zálohovat teď**,
**Spustit údržbu teď** a **Poslat stav správci teď**. Z příkazové řádky
`manage.py udrzba --jednou` (dnes podruhé: `--znovu`; jen e‑mail se stavem:
`--stav`).

Zálohu dál kopírujte **mimo počítač** (šifrovaný disk, síťové úložiště):
obsahuje jména sportovců (databáze + `.env`). Jednou za čtvrt roku obnovu
vyzkoušejte – návrat ze zálohy je v `docs/vice-pocitacu.md`
a `deploy/pythonanywhere.md`.

## Nastavení v `.env`

```
BACKUP_DIR=            # složka záloh; prázdné = Zalohy-FTVS ve vašem profilu
BACKUP_KEEP_DAILY=7    # kolik denních záloh nechat
STATUS_MAIL_WEEKDAY=0  # den pro stav správci: 0 = pondělí … 6 = neděle
MAINTENANCE_IN_WEB=True
```

## Pro programátora

`apps/core/maintenance.py`: `daily(org)` (jednou denně, `force=` podruhé),
`ensure_today(org)` z Přehledu, `status(org)` čísla a varování,
`status_message(org, info)` text e‑mailu, `send_status(org)`. Záloha je
v `apps/core/backup.py` (`backup_sqlite`), kterou používá i příkaz
`zalohovat`. Stav u pracoviště: `maintenance_at`, `maintenance_log`,
`backup_at`, `backup_note`, `status_mailed_on`. Testy: `tests/test_provoz.py`.
