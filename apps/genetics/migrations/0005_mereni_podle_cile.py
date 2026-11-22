"""
Návrhy karet z katalog/karty po kontrole proti podkladům v02: texty budoucího
měření podle cíle klienta a jedno znění stejných obecných doporučení pod
jedním klíčem pro slučování (viz apps/genetics/draft_updates.py).

Jen neschválené karty (návrh, v revizi) a jen doporučení, jejichž text nikdo
neupravil – shoda se zněním ze souborů karet. Schválené karty se nemění.
"""

from django.db import migrations

DRAFT = ["draft", "review"]


def forwards(apps, schema_editor):
    from apps.genetics.draft_updates import GENERAL, MEASUREMENT, SPLIT

    Recommendation = apps.get_model("genetics", "Recommendation")

    def matching(rsid, version, text, **extra):
        return Recommendation.objects.filter(card__variant__rsid=rsid, card__version=version,
                                             card__status__in=DRAFT, text=text, **extra)

    for (rsid, version, old), (new, goals) in MEASUREMENT.items():
        matching(rsid, version, old, basis="measurement").update(text=new, goals=goals)
    for (rsid, version, old), fields in SPLIT.items():
        for rec in matching(rsid, version, old):
            if not rec.card.recommendations.filter(text=fields["text"]).exists():
                Recommendation.objects.create(card=rec.card, genotype=rec.genotype,
                                              order=rec.order, **fields)
    for (rsid, version, old), new in GENERAL.items():
        matching(rsid, version, old).update(text=new)


class Migration(migrations.Migration):
    dependencies = [("genetics", "0004_interakce_revize_cile")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
