"""
Účty bez pracoviště dostanou jediné pracoviště instance.

Účet bez organizace v aplikaci neviděl nic (prázdný seznam sportovců)
a založení sportu nebo sportovce skončilo chybou. Pole bylo v administraci
nepovinné a snadno se přehlédlo. Když je organizace jediná, patří k ní
každý účet; při víc organizacích se nic nemění (musí se vybrat ručně).
"""

from django.db import migrations


def assign_single_organization(apps, schema_editor):
    Organization = apps.get_model("core", "Organization")
    User = apps.get_model("core", "User")
    organizations = list(Organization.objects.order_by("pk")[:2])
    if len(organizations) == 1:
        User.objects.filter(organization__isnull=True).update(organization=organizations[0])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_role_sportovec_zastupce"),
    ]

    operations = [
        migrations.RunPython(assign_single_organization, migrations.RunPython.noop),
    ]
