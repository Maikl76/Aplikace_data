"""
Import studie PRODEF ze sešitu pro spoluautory (xlsx) – viz apps/ingest/prodef.py
a docs/import-prodef.md.

    python manage.py import_prodef cesta/k/sesitu.xlsx              # načíst
    python manage.py import_prodef cesta/k/sesitu.xlsx --nanecisto  # jen ukázat, co by se načetlo
    python manage.py import_prodef --mdc-z-kontroly                 # MDC z kontrolní skupiny
    python manage.py import_prodef --smazat                         # odebrat vše, co import založil

Zaheslovaný sešit: heslo v proměnné prostředí XLSX_HESLO, jinak se příkaz zeptá
(heslo se nevypisuje ani neukládá). Ve veřejném zkušebním provozu (DEMO_MODE)
jen s --souhlas-vedouciho – data studie tam patří jen se souhlasem vedoucího projektu.
"""

import getpass
import os
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import AuditLog, Organization
from apps.ingest import prodef


class Command(BaseCommand):
    help = "Načte studii PRODEF ze sešitu pro spoluautory (nebo ji smaže)."

    def add_arguments(self, parser):
        parser.add_argument("soubor", nargs="?", help="Sešit PRODEF (.xlsx).")
        parser.add_argument("--nanecisto", action="store_true",
                            help="Jen přečíst a ukázat, co by se načetlo; nic nezapsat.")
        parser.add_argument("--zeptat", action="store_true",
                            help="Po přečtení ukázat souhrn a před zápisem se zeptat.")
        parser.add_argument("--pracoviste", help="Zkratka pracoviště (když jich je víc).")
        parser.add_argument("--mdc-z-kontroly", action="store_true",
                            help="Spočítat MDC90 klíčových ukazatelů z kontrolní skupiny "
                                 "a uložit je k ukazatelům (přepíše současné MDC).")
        parser.add_argument("--smazat", action="store_true",
                            help="Odebrat všechny probandy PRODEF i s jejich daty.")
        parser.add_argument("--ano", action="store_true", help="Smazat bez dotazu.")
        parser.add_argument("--souhlas-vedouciho", action="store_true",
                            help="Ve zkušebním provozu: potvrzuji souhlas vedoucího projektu.")

    def handle(self, *args, **options):
        if settings.DEMO_MODE and not options["souhlas_vedouciho"] and not options["smazat"]:
            raise CommandError(
                "Tohle je veřejný zkušební provoz. Data studie PRODEF sem patří jen se souhlasem "
                "vedoucího projektu – pokud ho máte, spusťte příkaz s --souhlas-vedouciho. "
                "Jinak data načtěte na počítači laboratoře.")
        organization = self._organization(options.get("pracoviste"))

        if options["smazat"]:
            return self._delete(organization, confirm=options["ano"])
        if options["soubor"]:
            self._import(options["soubor"], organization, dry_run=options["nanecisto"],
                         ask=options["zeptat"])
        elif not options["mdc_z_kontroly"]:
            raise CommandError("Zadejte cestu k sešitu PRODEF (nebo --smazat, --mdc-z-kontroly).")
        if options["mdc_z_kontroly"] and not options["nanecisto"]:
            self._mdc(organization)

    # ------------------------------------------------------------------------------------

    def _organization(self, short_name):
        if short_name:
            organization = Organization.objects.filter(short_name=short_name).first()
            if organization is None:
                raise CommandError(f"Pracoviště „{short_name}“ neexistuje.")
            return organization
        organizations = list(Organization.objects.filter(is_active=True).order_by("pk"))
        if not organizations:
            raise CommandError("V aplikaci zatím není žádné pracoviště.")
        if len(organizations) > 1:
            names = ", ".join(o.short_name for o in organizations)
            raise CommandError(f"Pracovišť je víc ({names}) – vyberte --pracoviste.")
        return organizations[0]

    def _password(self, path):
        password = os.environ.get("XLSX_HESLO") or ""
        try:
            with open(path, "rb") as handle:
                encrypted = prodef.is_encrypted(handle.read(8))
        except OSError:
            return password
        if encrypted and not password and sys.stdin.isatty():
            password = getpass.getpass("Heslo k sešitu (nezobrazuje se): ")
        return password

    def _import(self, path, organization, *, dry_run, ask=False):
        try:
            workbook = prodef.open_workbook(path, password=self._password(path))
            plan = prodef.read_plan(workbook, organization)
        except prodef.ProdefError as exc:
            raise CommandError(str(exc)) from exc
        finally:
            os.environ.pop("XLSX_HESLO", None)
        summary = plan.summary()
        arms = ", ".join(f"{arm} {n}" for arm, n in sorted(summary["ramena"].items()))
        self.stdout.write(
            f"Sešit: {summary['probandu']} probandů ({arms}), {summary['testovacich_dnu']} "
            f"testovacích dnů, {summary['provedeni']} provedení testů, {summary['pokusu']} "
            f"pokusů, {summary['hodnot']} hodnot, {summary['dotazniku']} ranních dotazníků.")
        if summary["nenastoupili"]:
            self.stdout.write(f"Nenačtou se {summary['nenastoupili']} probandi, kteří nenastoupili.")
        if summary["preskoceno_radku"]:
            self.stdout.write(f"Přeskočeno řádků bez probanda, data nebo hodnot: "
                              f"{summary['preskoceno_radku']}.")
        for note in plan.notes:
            self.stdout.write(self.style.WARNING(note))
        if dry_run:
            self.stdout.write("Nanečisto – nic se nezapsalo.")
            return
        if ask and input(f"Načíst do pracoviště {organization.short_name}? Napište ANO: "
                         ).strip().upper() != "ANO":
            self.stdout.write("Nic se nenačetlo.")
            return
        counts = prodef.apply_plan(plan, organization)
        AuditLog.objects.create(user=None, action=AuditLog.Action.CREATE,
                                object_type="ImportPRODEF", object_id=str(organization.pk),
                                detail={"soubor": os.path.basename(path), **counts})
        self.stdout.write(self.style.SUCCESS(
            f"Načteno do pracoviště {organization.short_name}: nových sportovců "
            f"{counts.get('novych_sportovcu', 0)}, aktualizovaných "
            f"{counts.get('aktualizovanych_sportovcu', 0)}, nových testovacích dnů "
            f"{counts.get('novych_dnu', 0)}, provedení {counts.get('provedeni', 0)}, pokusů "
            f"{counts.get('pokusu', 0)}, hodnot {counts.get('hodnot', 0)}, dotazníků "
            f"{counts.get('dotazniku', 0)}, výchozích měření {counts.get('vychozich_mereni', 0)}."))
        self.stdout.write(
            "Dál: Týmový přehled → PRODEF Stres / PRODEF Kontrola (změna proti výchozímu "
            "měření). MDC z kontrolní skupiny spočítá Nastavení → MDC u ukazatelů → „spočítat "
            "z dat“ (skupina PRODEF Kontrola, odstup 1 den), nebo tento příkaz s --mdc-z-kontroly.")
        self.stdout.write(
            "Pozor: v sešitu je u IMTP nejlepší pokus, v katalogu aplikace průměr pokusů – pro "
            "stejné hodnoty jako MASTER nastavte u Vrcholové síly (IMTP) „nejlepší pokus“.")

    def _mdc(self, organization):
        results = prodef.control_mdc(organization, save=True)
        if not results:
            self.stdout.write(self.style.WARNING(
                "MDC se nespočítala – v kontrolní skupině nejsou opakovaná měření den po dni."))
            return
        for item in results:
            metric, r = item["metric"], item["result"]
            label = f" ({r['label']})" if r["label"] else ""
            self.stdout.write(
                f"{metric.name}{label}: TE {r['te_txt']} {metric.unit}"
                + (f" ({r['te_pct_txt']} %)" if r["te_pct_txt"] else "")
                + f", MDC90 {r['mdc90_txt']} {metric.unit} – {r['n_subjects']} osob, "
                  f"{r['n_pairs']} párů; uloženo.")
        AuditLog.objects.create(user=None, action=AuditLog.Action.UPDATE,
                                object_type="MetricDef", object_id="prodef-mdc",
                                detail={"nastaveni": "mdc_z_kontroly_prodef",
                                        "ukazatele": [i["metric"].code for i in results]})

    def _delete(self, organization, *, confirm):
        count = prodef.imported_subjects(organization).count()
        if not count:
            self.stdout.write("Žádní probandi PRODEF tu nejsou.")
            return
        if not confirm:
            answer = input(f"Smazat {count} probandů PRODEF i se všemi jejich daty a zprávami? "
                           "Napište SMAZAT: ")
            if answer.strip() != "SMAZAT":
                self.stdout.write("Nic se nesmazalo.")
                return
        counts = prodef.delete_imported(organization)
        AuditLog.objects.create(user=None, action=AuditLog.Action.DELETE,
                                object_type="ImportPRODEF", object_id=str(organization.pk),
                                detail=counts)
        self.stdout.write(self.style.SUCCESS(
            f"Smazáno: {counts['sportovcu']} probandů, {counts['testovacich_dnu']} testovacích "
            f"dnů, {counts['zprav']} zpráv."))
