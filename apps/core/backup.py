"""
Záloha SQLite: databáze, nahrané soubory a .env s klíči.

Dokumentace dřív tvrdila, že na počítačích jsou jen vymyšlená data;
v praxi se na laboratorním PC importují skutečné exporty. Bez zálohy
by výpadek disku vzal roky měření. A bez .env (šifrovací klíč) jsou
uložená jména nečitelná i ze zálohy databáze – proto se bere i on.

Databáze se kopíruje zálohovacím rozhraním SQLite, takže je kopie
konzistentní, i když aplikace zrovna běží (režim WAL). Volá to příkaz
zalohovat (zalohovat.bat, deploy/pa-update.sh) i denní údržba
(apps/core/maintenance.py).
"""

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django.utils.text import slugify

PREFIX = "ftvs-zaloha-"


class BackupError(Exception):
    """Záloha se nepovedla nebo tu nedává smysl (databáze není SQLite v souboru)."""


@dataclass
class BackupResult:
    path: Path
    size_mb: float
    files: int
    has_env: bool
    removed: int

    @property
    def text(self) -> str:
        return (f"{self.path} (databáze {self.size_mb:.1f} MB, nahraných souborů {self.files}, "
                f".env {'ano' if self.has_env else 'NE'})")


def default_root() -> Path:
    """Kam se zálohuje bez udání složky: BACKUP_DIR z .env, jinak ~/Zalohy-FTVS."""
    return Path(settings.BACKUP_DIR) if settings.BACKUP_DIR else Path.home() / "Zalohy-FTVS"


def database_file(database=None) -> Path:
    """Soubor databáze SQLite; BackupError, když databáze není SQLite v souboru."""
    if connection.vendor != "sqlite":
        raise BackupError("Tahle záloha je pro SQLite (laboratorní počítač, notebook). "
                          "Server zálohuje deploy/backup.sh.")
    source = str(database or connection.settings_dict["NAME"])
    if source.startswith("file:") or source == ":memory:":
        raise BackupError("Databáze není v souboru – není co zálohovat.")
    path = Path(source)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    if not path.exists():
        raise BackupError(f"Soubor databáze {path} neexistuje.")
    return path


def backup_sqlite(*, root=None, keep: int = 10, label: str = "", database=None) -> BackupResult:
    """
    Udělá zálohu do nové podsložky ``root`` (ftvs-zaloha-DATUM[-popis]) a starší
    zálohy nad ``keep`` smaže. Vrací, co a kam se uložilo.
    """
    source_path = database_file(database)
    root = Path(root) if root else default_root()
    stamp = f"{PREFIX}{timezone.localtime():%Y-%m-%d-%H%M%S}"
    if popis := slugify(label):
        stamp += f"-{popis}"
    target, n = root / stamp, 2
    while target.exists():                  # dvě zálohy v téže sekundě
        target, n = root / f"{stamp}-{n}", n + 1
    try:
        target.mkdir(parents=True)
    except OSError as exc:
        raise BackupError(f"Složku pro zálohu {target} nejde vytvořit: {exc}") from exc

    # Vlastní spojení: zálohovací rozhraní si databázi přečte konzistentně,
    # i když v ní aplikace zrovna zapisuje (WAL).
    try:
        src, copy = sqlite3.connect(source_path), sqlite3.connect(target / "db.sqlite3")
        try:
            src.backup(copy)
        finally:
            copy.close()
            src.close()
    except (sqlite3.Error, OSError) as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise BackupError(f"Kopie databáze se nepovedla: {exc}") from exc
    size_mb = (target / "db.sqlite3").stat().st_size / 1_000_000

    env_file = Path(settings.BASE_DIR) / ".env"
    has_env = env_file.exists()
    if has_env:
        shutil.copy2(env_file, target / ".env")

    media = Path(settings.MEDIA_ROOT)
    files = 0
    if media.is_dir():
        shutil.copytree(media, target / "media")
        files = sum(1 for p in (target / "media").rglob("*") if p.is_file())

    keep = max(keep, 1)
    old = sorted(p for p in root.glob(f"{PREFIX}*") if p.is_dir())[:-keep]
    for folder in old:
        shutil.rmtree(folder)
    return BackupResult(target, size_mb, files, has_env, len(old))


def latest(root=None) -> Path | None:
    """Poslední záloha ve složce (podle názvu = podle času)."""
    root = Path(root) if root else default_root()
    if not root.is_dir():
        return None
    folders = sorted(p for p in root.glob(f"{PREFIX}*") if p.is_dir())
    return folders[-1] if folders else None
