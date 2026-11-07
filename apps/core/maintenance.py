"""
Denní údržba pracoviště.

Jednou denně: záloha (jen SQLite – laboratorní počítač, PythonAnywhere;
server zálohuje deploy/backup.sh), úklid starých nedokončených importů,
připomínky dalšího měření a v nastavený den v týdnu e-mail správci se
stavem pracoviště (zálohy, místo na disku, co čeká, chyby, model).

Spouští ji příkaz ``udrzba`` – na laboratorním počítači ho otevírá
spustit.bat ve vlastním okně a běží dokola, na serveru je to plánovaná
úloha s ``--jednou``. Když příkaz neběží, údržbu jako pojistku spustí
první otevření Přehledu v daný den (MAINTENANCE_IN_WEB). Co a kdy
proběhlo, je u pracoviště (maintenance_at, maintenance_log) a vidí to
Nastavení → Provoz a zálohy i krok ve Stavu pracoviště.

E-mail správci nikdy nenese jména ani výsledky sportovců – jen počty.
"""

import logging
import shutil
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.reports.narrative import plural

from . import backup
from .models import Role, User

logger = logging.getLogger(__name__)

DAILY_SUBDIR = "denni"        # denní zálohy zvlášť, ať nevytlačí zálohy před aktualizací
BACKUP_MAX_AGE_DAYS = 2       # starší záloha = varování
DISK_MIN_FREE_GB = 2.0
WEEKDAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


@dataclass
class Outcome:
    log: dict = field(default_factory=dict)   # uloží se k pracovišti (jen JSON)
    reminders: dict | None = None            # výsledek připomínek pro Přehled


def daily_backup_dir() -> Path:
    return backup.default_root() / DAILY_SUBDIR


def ran_today(organization, today=None) -> bool:
    today = today or timezone.localdate()
    return (organization.maintenance_at is not None
            and timezone.localtime(organization.maintenance_at).date() == today)


def weekly_due(organization, today=None) -> bool:
    """Den týdne pro stav správci a od posledního odeslání aspoň 6 dní."""
    today = today or timezone.localdate()
    last = organization.status_mailed_on
    return (today.weekday() == settings.STATUS_MAIL_WEEKDAY
            and (last is None or (today - last).days >= 6))


def daily(organization, *, booking_url: str = "", force: bool = False, today=None) -> Outcome | None:
    """Denní údržba pracoviště; None, když dnes už proběhla (a není ``force``)."""
    from apps.ingest import services as ingest
    from apps.subjects import retest

    today = today or timezone.localdate()
    if organization is None or (not force and ran_today(organization, today)):
        return None
    now = timezone.now()
    out = Outcome(log={"den": today.isoformat()})

    # 1. záloha
    try:
        result = backup.backup_sqlite(root=daily_backup_dir(), keep=settings.BACKUP_KEEP_DAILY,
                                      label="denni")
        out.log["zaloha"] = {"ok": True, "cesta": str(result.path), "mb": round(result.size_mb, 1),
                             "soubory": result.files, "env": result.has_env}
        organization.backup_at = now
        organization.backup_note = result.text
    except backup.BackupError as exc:
        applies = connection.vendor == "sqlite"
        out.log["zaloha"] = {"ok": not applies, "chyba": str(exc)}
        organization.backup_note = str(exc)
        if applies:
            logger.error("Denní záloha selhala: %s", exc)

    # 2. staré nedokončené importy
    try:
        out.log["importy_smazano"] = ingest.expire_stale()
    except Exception:   # úklid nesmí zastavit zbytek údržby
        logger.exception("Úklid starých importů selhal")
        out.log["importy_smazano"] = None

    # 3. připomínky dalšího měření (jednou denně; bez pošty jen poznámka)
    out.reminders = retest.daily_check(organization, booking_url=booking_url)
    out.log["pripominky"] = ({"na_rade": len(out.reminders["due"]),
                              "odeslano": len(out.reminders["sent"])}
                             if out.reminders is not None else "už dnes proběhly")

    # 4. stav správci jednou týdně
    if weekly_due(organization, today):
        sent = send_status(organization, today=today, force=True)
        out.log["stav_spravci"] = ({"odeslano": sent} if sent
                                   else "neodesláno (bez pošty, nebo správce bez e-mailu)")

    organization.maintenance_at = now
    organization.maintenance_log = out.log
    organization.save(update_fields=["maintenance_at", "maintenance_log", "backup_at",
                                     "backup_note", "status_mailed_on", "updated_at"])
    return out


def ensure_today(organization, *, booking_url: str = "") -> Outcome | None:
    """
    Pojistka z Přehledu: když příkaz udrzba neběží, údržba proběhne při
    prvním otevření v daný den. S vypnutou pojistkou jen připomínky jako dřív.
    """
    from apps.subjects import retest

    if organization is None:
        return None
    if not settings.MAINTENANCE_IN_WEB:
        reminders = retest.daily_check(organization, booking_url=booking_url)
        return Outcome(reminders=reminders) if reminders is not None else None
    try:
        return daily(organization, booking_url=booking_url)
    except Exception:   # Přehled se musí otevřít, i když údržba spadne
        logger.exception("Denní údržba z Přehledu selhala")
        return None


# --- stav pracoviště --------------------------------------------------------------

def admins(organization) -> list[str]:
    """Adresy správců pracoviště (a superuživatelů v něm)."""
    users = User.objects.filter(organization=organization, is_active=True).filter(
        role=Role.ADMIN) | User.objects.filter(organization=organization, is_active=True,
                                                is_superuser=True)
    out = []
    for user in users.distinct():
        address = (user.email or "").strip().lower()
        if address and address not in out:
            out.append(address)
    return out


def status(organization, *, today=None) -> dict:
    """Čísla pro stránku Provoz a zálohy i pro týdenní e-mail; bez jmen."""
    from apps.ingest import watch
    from apps.ingest.models import ImportBatch, WatchedFile
    from apps.measurements.models import TestSession
    from apps.reports import llm
    from apps.reports.models import Report
    from apps.subjects import retest
    from apps.subjects.models import Subject

    from .models import Remark

    today = today or timezone.localdate()
    since = today - timedelta(days=7)
    since_dt = timezone.now() - timedelta(days=7)
    org = organization
    warnings = []

    sqlite = connection.vendor == "sqlite"
    backup_age = ((today - timezone.localtime(org.backup_at).date()).days
                  if org.backup_at else None)
    backup_ok = (not sqlite) or (backup_age is not None and backup_age <= BACKUP_MAX_AGE_DAYS)
    if sqlite and backup_age is None:
        warnings.append("Denní záloha ještě neproběhla.")
    elif sqlite and not backup_ok:
        warnings.append(f"Poslední záloha je stará {backup_age} dní.")
    backup_failed = (org.maintenance_log or {}).get("zaloha", {}).get("ok") is False
    if backup_failed:
        warnings.append("Poslední záloha selhala: "
                        f"{(org.maintenance_log or {})['zaloha'].get('chyba', '')}")

    try:
        usage = shutil.disk_usage(settings.BASE_DIR)
        disk = {"free_gb": usage.free / 1e9, "total_gb": usage.total / 1e9,
                "pct_free": 100 * usage.free / usage.total if usage.total else 0}
    except OSError:
        disk = {"free_gb": None, "total_gb": None, "pct_free": None}
    if disk["free_gb"] is not None and disk["free_gb"] < DISK_MIN_FREE_GB:
        warnings.append(f"Na disku zbývá jen {disk['free_gb']:.1f} GB.")

    maintenance_age = ((today - timezone.localtime(org.maintenance_at).date()).days
                       if org.maintenance_at else None)
    if maintenance_age is None:
        warnings.append("Denní údržba ještě neběžela.")
    elif maintenance_age > BACKUP_MAX_AGE_DAYS:
        warnings.append(f"Denní údržba naposledy před {maintenance_age} dny.")

    sessions = TestSession.objects.filter(organization=org, date__gt=since, date__lte=today)
    week = {
        "sessions": sessions.count(),
        "measured": sessions.filter(protocol_runs__trials__measurements__isnull=False)
        .distinct().count(),
        "released": Report.objects.filter(organization=org, status=Report.Status.RELEASED,
                                          released_at__gte=since_dt).count(),
        "subjects": Subject.objects.filter(organization=org, created_at__gte=since_dt).count(),
        "imports": ImportBatch.objects.filter(organization=org, created_at__gte=since_dt,
                                              status=ImportBatch.Status.COMMITTED).count(),
    }
    active = Subject.objects.filter(organization=org, is_active=True)
    waiting = {
        "drafts": Report.objects.filter(organization=org, status=Report.Status.DRAFT).count(),
        "imports": ImportBatch.objects.filter(organization=org,
                                              status=ImportBatch.Status.PARSED).count(),
        "remarks": Remark.objects.filter(organization=org, status=Remark.Status.OPEN).count(),
        "due": sum(1 for p in retest.plans_for(active, today=today) if p.is_due),
    }
    errors = []
    failed_imports = ImportBatch.objects.filter(organization=org, created_at__gte=since_dt,
                                                status=ImportBatch.Status.FAILED).count()
    if failed_imports:
        errors.append(f"{failed_imports}× import se nepodařilo načíst")
    failed_watch = WatchedFile.objects.filter(organization=org, created_at__gte=since_dt,
                                              status=WatchedFile.Status.FAILED).count()
    if failed_watch:
        errors.append(f"{failed_watch}× soubor ze sledované složky nešel načíst")
    if backup_failed:
        errors.append("záloha selhala")

    model = llm.describe()
    model_text = (model["blocked"] if model["blocked"] else
                  f"zapnutý, cloudový ({model['host']})" if model["remote"] and model["enabled"]
                  else f"zapnutý, lokální ({model['model']})" if model["enabled"]
                  else "vypnutý – souhrny píše šablona")
    folder = {"configured": bool(settings.IMPORT_WATCH_DIR), "running": watch.is_running(org)}
    if folder["configured"] and not folder["running"]:
        warnings.append("Sledovaná složka je nastavená, ale hlídač neběží.")

    week_text = (f"{week['sessions']} {plural(week['sessions'], 'testovací den', 'testovací dny', 'testovacích dnů')} "
                 f"({week['measured']} s hodnotami), "
                 f"{week['released']} {plural(week['released'], 'vydaná zpráva', 'vydané zprávy', 'vydaných zpráv')}, "
                 f"{week['subjects']} {plural(week['subjects'], 'nový sportovec', 'noví sportovci', 'nových sportovců')}, "
                 f"{week['imports']} {plural(week['imports'], 'uložený import', 'uložené importy', 'uložených importů')}")
    waiting_text = (f"{waiting['drafts']} {plural(waiting['drafts'], 'koncept zprávy', 'koncepty zpráv', 'konceptů zpráv')}, "
                    f"{waiting['imports']} {plural(waiting['imports'], 'import', 'importy', 'importů')} na kontrolu, "
                    f"{waiting['remarks']} {plural(waiting['remarks'], 'připomínka', 'připomínky', 'připomínek')} kolegů, "
                    f"{waiting['due']} {plural(waiting['due'], 'sportovec', 'sportovci', 'sportovců')} na řadě "
                    "k dalšímu měření")
    return {
        "today": today, "since": since, "sqlite": sqlite,
        "week_text": week_text, "waiting_text": waiting_text,
        "backup_age_text": age_text(backup_age), "maintenance_age_text": age_text(maintenance_age),
        "backup": {"at": org.backup_at, "note": org.backup_note, "age_days": backup_age,
                   "ok": backup_ok, "dir": str(daily_backup_dir()), "failed": backup_failed},
        "disk": disk,
        "maintenance": {"at": org.maintenance_at, "log": org.maintenance_log or {},
                        "age_days": maintenance_age},
        "week": week, "waiting": waiting, "errors": errors,
        "model": model_text, "mail": bool(settings.EMAIL_HOST), "folder": folder,
        "status_mail": {"weekday": WEEKDAYS[settings.STATUS_MAIL_WEEKDAY % 7],
                        "last": org.status_mailed_on, "recipients": admins(org)},
        "warnings": warnings,
    }


def age_text(days) -> str:
    """„dnes“, „včera“, „před 3 dny“; prázdné, když nikdy."""
    if days is None:
        return ""
    if days == 0:
        return "dnes"
    if days == 1:
        return "včera"
    return f"před {days} dny"


def _cz(value, decimals=1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _when(moment) -> str:
    return f"{timezone.localtime(moment):%d.%m.%Y %H:%M}" if moment else "nikdy"


def status_message(organization, info: dict, *, base_url: str = "") -> tuple[str, str]:
    """Předmět a text týdenního e-mailu správci – počty a stav, žádná jména."""
    b, d = info["backup"], info["disk"]
    lines = [f"Stav pracoviště {organization.name} – týden do {info['today']:%d.%m.%Y}", ""]
    lines.append(f"Za posledních 7 dní: {info['week_text']}.")
    lines.append(f"Čeká: {info['waiting_text']}.")
    lines.append("")
    if info["sqlite"]:
        lines.append(f"Záloha: naposledy {_when(b['at'])}"
                     + (f" – {b['note']}" if b["note"] else "") + ".")
    else:
        lines.append("Záloha: databáze běží na serveru, zálohuje ji deploy/backup.sh.")
    if d["free_gb"] is not None:
        lines.append(f"Místo na disku: {_cz(d['free_gb'])} GB volných z {_cz(d['total_gb'], 0)} GB "
                     f"({_cz(d['pct_free'], 0)} %).")
    lines.append("Chyby za týden: " + ("; ".join(info["errors"]) if info["errors"] else "žádné") + ".")
    lines.append(f"Jazykový model: {info['model']}.")
    folder = info["folder"]
    lines.append("Sledovaná složka: " + ("hlídač běží" if folder["running"] else
                                        "nastavená, ale hlídač neběží" if folder["configured"]
                                        else "není nastavená") + ".")
    m = info["maintenance"]
    lines.append(f"Denní údržba: naposledy {_when(m['at'])}.")
    if info["warnings"]:
        lines += ["", "Upozornění:"] + [f"- {text}" for text in info["warnings"]]
    base = (base_url or settings.PUBLIC_BASE_URL or "").rstrip("/")
    lines += ["", "Podrobnosti: " + (base + reverse("operations") if base
                                     else "Nastavení → Provoz a zálohy v aplikaci")]
    lines.append("Tento e-mail neobsahuje jména ani výsledky sportovců.")
    return f"Stav pracoviště {organization.name} – týden do {info['today']:%d.%m.%Y}", "\n".join(lines)


def send_status(organization, *, today=None, force: bool = False, base_url: str = "") -> int:
    """Pošle stav správcům; vrací počet adres (0 = neodešlo). ``force`` obejde den v týdnu."""
    from django.core.mail import send_mail

    today = today or timezone.localdate()
    if organization is None or not settings.EMAIL_HOST:
        return 0
    if not force and not weekly_due(organization, today):
        return 0
    addresses = admins(organization)
    if not addresses:
        return 0
    subject, body = status_message(organization, status(organization, today=today),
                                   base_url=base_url)
    try:
        send_mail(subject, body, None, addresses)
    except Exception:   # poštovní server neodpovídá – stav zůstane v aplikaci
        logger.exception("Stav pracoviště správci neodešel.")
        return 0
    organization.status_mailed_on = today
    organization.save(update_fields=["status_mailed_on"])
    return len(addresses)
