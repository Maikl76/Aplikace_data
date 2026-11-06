"""
Sledovaná složka s exporty z přístroje.

Místo ručního nahrávání: hlídač (příkaz ``hlidat_slozku``, spouští ho
spustit.bat) projde složku, nový export založí do importu a když sportovce
jednoznačně pozná a den má naplánovaný, rovnou ho uloží. Nejasné shody,
neznámé ukazatele nebo hodnoty bez data nechá čekat na kontrolu – přesně
jako po ručním nahrání. Složka se nastavuje v .env (IMPORT_WATCH_DIR);
soubory se nikam nepřesouvají, složka patří přístroji.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.core.models import AuditLog, Organization, Role, User
from apps.measurements.models import TestSession

from . import services
from .models import ImportBatch, WatchedFile

logger = logging.getLogger(__name__)

EXTENSIONS = (".xlsx", ".xls", ".csv")
SYSTEM_USERNAME = "sledovana-slozka"
SETTLE_SECONDS = 5      # soubor mladší než tohle může přístroj ještě zapisovat
FRESH_MINUTES = 10      # kontrola starší než tohle = hlídač neběží


class WatchError(Exception):
    pass


@dataclass
class Outcome:
    name: str
    status: str
    message: str
    batch: ImportBatch | None = None

    @property
    def label(self) -> str:
        return WatchedFile.Status(self.status).label


class _Upload:
    """Soubor ze složky v podobě, jakou čeká stage_file (jméno a read())."""

    def __init__(self, name: str, data: bytes):
        self.name, self._data = name, data

    def read(self) -> bytes:
        return self._data


def folder() -> Path | None:
    raw = (settings.IMPORT_WATCH_DIR or "").strip()
    return Path(raw).expanduser() if raw else None


def system_user(organization):
    """Účet, pod kterým hlídač importuje. Nepřihlašuje se (není aktivní)."""
    user, _ = User.objects.get_or_create(
        username=SYSTEM_USERNAME,
        defaults={"organization": organization, "role": Role.LAB, "is_active": False,
                  "first_name": "Sledovaná", "last_name": "složka"})
    return user


def is_running(organization, now=None) -> bool:
    checked = organization.import_checked_at
    now = now or timezone.now()
    return checked is not None and (now - checked).total_seconds() < FRESH_MINUTES * 60


def _latest(organization) -> dict[str, WatchedFile]:
    out = {}
    for w in WatchedFile.objects.filter(organization=organization).order_by("created_at"):
        out[w.name] = w     # poslední záznam k názvu vyhraje
    return out


def scan(organization, *, user=None, directory=None, settle: float = SETTLE_SECONDS) -> list[Outcome]:
    """Jeden průchod složkou: nové nebo změněné soubory zpracuje, ostatní přeskočí."""
    directory = Path(directory) if directory else folder()
    if directory is None:
        raise WatchError("Sledovaná složka není nastavená (IMPORT_WATCH_DIR v .env).")
    if not directory.is_dir():
        raise WatchError(f"Sledovaná složka {directory} neexistuje nebo není dostupná.")
    user = user or system_user(organization)
    known = _latest(organization)
    outcomes = []
    for path in sorted(directory.iterdir()):
        if (not path.is_file() or path.suffix.lower() not in EXTENSIONS
                or path.name.startswith(("~$", "."))):
            continue
        stat = path.stat()
        if time.time() - stat.st_mtime < settle:
            continue
        modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        seen = known.get(path.name)
        if (seen and seen.size == stat.st_size
                and abs((seen.modified_at - modified).total_seconds()) < 1):
            continue
        outcomes.append(_process(organization, user, path, stat.st_size, modified))
    Organization.objects.filter(pk=organization.pk).update(import_checked_at=timezone.now())
    return outcomes


def auto_commit_blocker(batch, user) -> str | None:
    """Proč import nejde uložit bez člověka; None = jde."""
    summary = services.summarize(batch)
    if summary["nezname_metriky"]:
        return "neznámé ukazatele: " + ", ".join(summary["nezname_metriky"][:5])
    if summary["novych_hodnot_bez_data"]:
        return f"{summary['novych_hodnot_bez_data']} hodnot bez data měření"
    rows = services.assignment_choices(batch, user)
    unmatched = [r for r in rows if r["selected"] is None]
    if unmatched:
        return f"{len(unmatched)} sportovců ze souboru aplikace nepozná jednoznačně"
    services.apply_assignments(batch, {r["key"]: r["selected"] for r in rows}, user)
    pairs = set(batch.staged.filter(subject__isnull=False, session_date__isnull=False)
                .values_list("subject_id", "session_date").distinct())
    planned = set(TestSession.objects.filter(
        subject_id__in={s for s, _ in pairs}, date__in={d for _, d in pairs})
        .values_list("subject_id", "date"))
    if missing := pairs - planned:
        return (f"{len(missing)} testovacích dnů není naplánovaných – založte je v Dnešním "
                "testování, nebo import uložte ručně")
    return None


def _result_text(result: dict, out_of_range: int) -> str:
    text = f"Uloženo {result['hodnoty']} hodnot, {result.get('testy', 0)} testů"
    if out_of_range:
        text += f"; {out_of_range} hodnot mimo rozsah označených"
    if result.get("koncepty"):
        text += "; koncepty zpráv: " + ", ".join(result["koncepty"])
    return text + "."


def _process(organization, user, path, size, modified) -> Outcome:
    data = path.read_bytes()
    record = WatchedFile(organization=organization, name=path.name, size=size,
                         modified_at=modified, content_hash=services._hash_content(data))
    try:
        batch = services.stage_file(uploaded_file=_Upload(path.name, data), user=user,
                                    organization=organization)
    except services.ImportError_ as exc:
        text = str(exc)
        record.status = (WatchedFile.Status.SKIPPED if "už byl importován" in text
                         else WatchedFile.Status.FAILED)
        record.message = text[:255]
        record.save()
        return Outcome(path.name, record.status, record.message)

    record.batch = batch
    if batch.status == ImportBatch.Status.FAILED:
        record.status = WatchedFile.Status.FAILED
        record.message = (batch.error or "soubor se nepodařilo zpracovat")[:255]
    elif batch.status != ImportBatch.Status.PARSED:
        record.status = WatchedFile.Status.SKIPPED
        record.message = f"import je ve stavu {batch.get_status_display().lower()}"
    elif batch.uploaded_by_id != user.pk:
        record.status = WatchedFile.Status.WAITING
        record.message = "soubor už někdo nahrál ručně – čeká na jeho kontrolu"
    elif reason := auto_commit_blocker(batch, user):
        record.status = WatchedFile.Status.WAITING
        record.message = reason[:255]
    else:
        out_of_range = services.summarize(batch)["mimo_rozsah"]
        result = services.commit_batch(batch, user=user)
        AuditLog.objects.create(user=user, action=AuditLog.Action.CREATE, object_type="ImportBatch",
                                object_id=str(batch.pk),
                                detail={**result, "sledovana_slozka": path.name})
        record.status = WatchedFile.Status.COMMITTED
        record.message = _result_text(result, out_of_range)[:255]
    record.save()
    logger.info("Sledovaná složka: %s – %s (%s)", path.name, record.get_status_display(),
                record.message)
    return Outcome(path.name, record.status, record.message, batch)
