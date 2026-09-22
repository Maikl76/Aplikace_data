"""
Založí skupiny oprávnění pro role v administraci.

    python manage.py seed_roles

Proč jen tři role a ne pět: **administrace Djanga umí oprávnění na úrovni
modelu, ne řádku.** Trenér by v ní viděl všechny týmy, ne jen svůj.
Trenéři a sportovci proto do administrace nepatří — pracují v samotné
aplikaci, která hlídá, na čí data vidí.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

# skupina -> {app_label: [akce]}, akce jsou add/change/delete/view
GROUPS = {
    "Správce": {
        "core": ["add", "change", "delete", "view"],
        "subjects": ["add", "change", "delete", "view"],
        "catalog": ["add", "change", "delete", "view"],
        "measurements": ["add", "change", "delete", "view"],
        "ingest": ["add", "change", "delete", "view"],
        "evidence": ["add", "change", "delete", "view"],
        "rules": ["add", "change", "delete", "view"],
        "reports": ["add", "change", "delete", "view"],
        "external": ["add", "change", "delete", "view"],
    },
    "Diagnostik": {
        # Zadává a opravuje měření, nesmí ale mazat – smazané měření
        # se nedá vrátit a v longitudinálních datech chybí navždy.
        "subjects": ["add", "change", "view"],
        "measurements": ["add", "change", "view"],
        "ingest": ["add", "change", "view"],
        "reports": ["add", "change", "view"],
        "external": ["add", "change", "view"],
        "catalog": ["view"],
        "evidence": ["view"],
        "rules": ["view"],
    },
    "Výzkumník": {
        # Jen čte. Identitu sportovců nevidí – ta je vyhrazená
        # superuživateli (viz SubjectIdentityAdmin).
        "subjects": ["view"],
        "measurements": ["view"],
        "catalog": ["view"],
        "evidence": ["view"],
        "rules": ["view"],
    },
}


class Command(BaseCommand):
    help = "Založí nebo srovná skupiny oprávnění pro role."

    @transaction.atomic
    def handle(self, *args, **options):
        for name, apps in GROUPS.items():
            group, created = Group.objects.get_or_create(name=name)
            permissions = []
            for app_label, actions in apps.items():
                for action in actions:
                    permissions.extend(
                        Permission.objects.filter(
                            content_type__app_label=app_label,
                            codename__startswith=f"{action}_",
                        )
                    )
            group.permissions.set(permissions)
            stav = "vytvořena" if created else "aktualizována"
            self.stdout.write(f"  {name:<12} {stav}, {len(permissions)} oprávnění")

        self.stdout.write(self.style.SUCCESS("\nSkupiny připravené."))
        self.stdout.write(
            "Uživateli stačí v administraci nastavit roli – skupina se k němu "
            "přiřadí sama. Do administrace se dostane jen ten, kdo má zaškrtnuté "
            "„Stav týmu“ (is_staff)."
        )
