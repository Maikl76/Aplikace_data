"""
Jeden testovací den na sportovce a datum.

Dřív mohly vzniknout dva dny téhož sportovce se stejným datem (ručně
založený a druhý z importu). Měření se pak dělila do dvou zpráv a hromadné
zakládání dne ze skupiny padalo. Před zavedením omezení se duplicitní dny
slijí do nejstaršího: provedení testů, dotazníky, nálezy, zprávy i účast
z objednávky se přesunou, zbylé prázdné dny se smažou.
"""

from django.db import migrations, models
from django.db.models import Count


def merge_duplicate_days(apps, schema_editor):
    TestSession = apps.get_model("measurements", "TestSession")
    ProtocolRun = apps.get_model("measurements", "ProtocolRun")
    QuestionnaireResponse = apps.get_model("measurements", "QuestionnaireResponse")
    Finding = apps.get_model("rules", "Finding")
    Report = apps.get_model("reports", "Report")
    Participant = apps.get_model("booking", "Participant")

    duplicates = (TestSession.objects.values("subject_id", "date")
                  .annotate(n=Count("id")).filter(n__gt=1))
    for group in duplicates:
        sessions = list(TestSession.objects
                        .filter(subject_id=group["subject_id"], date=group["date"])
                        .order_by("id"))
        keep, others = sessions[0], sessions[1:]
        for session in others:
            # Hlavní měření dne zůstane to z nejstaršího dne; stejný test
            # z pozdějšího dne se stane opakovaným měřením.
            primary = set(ProtocolRun.objects.filter(session=keep, is_primary=True)
                          .values_list("protocol_id", flat=True))
            for run in ProtocolRun.objects.filter(session=session).order_by("id"):
                run.session = keep
                if run.protocol_id in primary:
                    run.is_primary = False
                else:
                    primary.add(run.protocol_id)
                run.save(update_fields=["session", "is_primary"])
            QuestionnaireResponse.objects.filter(session=session).update(session=keep)
            Finding.objects.filter(session=session).update(session=keep)
            Report.objects.filter(session=session).update(session=keep)
            Participant.objects.filter(session=session).update(session=keep)
            changed = []
            for field in ("location", "season_phase", "note"):
                if not getattr(keep, field) and getattr(session, field):
                    setattr(keep, field, getattr(session, field))
                    changed.append(field)
            for field in ("operator_id", "fatigue_rating", "temperature_c", "humidity_pct"):
                if getattr(keep, field) is None and getattr(session, field) is not None:
                    setattr(keep, field, getattr(session, field))
                    changed.append(field)
            if changed:
                keep.save(update_fields=changed)
            session.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("measurements", "0003_prostredi_a_dotazniky"),
        ("rules", "0001_initial"),
        ("reports", "0007_pokyny_doporuceni_a_literatura"),
        ("booking", "0001_objednavky"),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_days, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="testsession",
            constraint=models.UniqueConstraint(
                fields=("subject", "date"), name="uniq_session_per_day",
                violation_error_message="Tento sportovec už má v ten den testovací den – "
                                        "testy přidejte do něj."),
        ),
    ]
