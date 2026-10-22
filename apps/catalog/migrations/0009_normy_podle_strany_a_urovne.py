"""
Úroveň, strana a režim normy jsou výběr z kódů, ne volný text.

Výběr normy je porovnává s kódy sportovce a měření; volný text („elite“,
„Levá“) nikdy neseděl, a norma se tak používala i tam, kam nepatřila.
Stávající hodnoty se převedou na kódy; co převést nejde, zůstane prázdné
(norma platí obecně) a původní text se uloží do poznámky.
"""

from django.db import migrations, models

from apps.catalog.norms import normalize_fields


def normalize_norms(apps, schema_editor):
    Norm = apps.get_model("catalog", "Norm")
    for norm in Norm.objects.all():
        data = {"level": norm.level, "side": norm.side, "mode": norm.mode}
        lost = normalize_fields(data)
        if data == {"level": norm.level, "side": norm.side, "mode": norm.mode}:
            continue
        norm.level, norm.side, norm.mode = data["level"], data["side"], data["mode"]
        if lost:
            note = "Při převodu nešlo poznat: " + "; ".join(lost) + "."
            norm.note = f"{norm.note}\n{note}".strip()
        norm.save(update_fields=["level", "side", "mode", "note"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0008_vlastni_pristroje"),
        ("subjects", "0006_datum_narozeni"),
    ]

    operations = [
        migrations.RunPython(normalize_norms, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="norm",
            name="level",
            field=models.CharField(
                blank=True,
                choices=[("rec", "Rekreační"), ("trained", "Trénovaný"),
                         ("national", "Národní úroveň"), ("intl", "Mezinárodní úroveň")],
                help_text="Prázdné = všechny úrovně. Vyplněná norma platí jen pro sportovce "
                          "s touž úrovní.",
                max_length=20, verbose_name="úroveň"),
        ),
        migrations.AlterField(
            model_name="norm",
            name="side",
            field=models.CharField(
                blank=True,
                choices=[("L", "Levá"), ("R", "Pravá"), ("B", "Oboustranně"),
                         ("D", "Dominantní"), ("N", "Nedominantní")],
                help_text="Prázdné = bez ohledu na stranu. Oboustranná hodnota sedí na normu "
                          "„Oboustranně“.",
                max_length=10, verbose_name="strana"),
        ),
        migrations.AlterField(
            model_name="norm",
            name="mode",
            field=models.CharField(
                blank=True,
                choices=[("con", "Koncentricky"), ("ecc", "Excentricky"),
                         ("iso", "Izometricky")],
                help_text="Prázdné = všechny režimy.", max_length=20, verbose_name="režim"),
        ),
    ]
