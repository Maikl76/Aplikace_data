# Dotazník může patřit sportovci i bez testovacího dne; odpověď má stav
# (nevím / netýká se), text a zvolené možnosti.

from django.db import migrations, models
import django.db.models.deletion


def doplnit_sportovce(apps, schema_editor):
    QuestionnaireResponse = apps.get_model("measurements", "QuestionnaireResponse")
    for response in QuestionnaireResponse.objects.select_related("session").all():
        if response.session_id and response.subject_id is None:
            response.subject_id = response.session.subject_id
            response.save(update_fields=["subject"])


class Migration(migrations.Migration):

    dependencies = [
        ("subjects", "0007_ucty_a_sdileni"),
        ("measurements", "0004_jeden_den_na_sportovce"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionnaireresponse",
            name="subject",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name="questionnaire_responses",
                                    to="subjects.subject", verbose_name="sportovec"),
        ),
        migrations.RunPython(doplnit_sportovce, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="questionnaireresponse",
            name="subject",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                    related_name="questionnaire_responses",
                                    to="subjects.subject", verbose_name="sportovec"),
        ),
        migrations.AlterField(
            model_name="questionnaireresponse",
            name="session",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.CASCADE,
                                    related_name="responses", to="measurements.testsession",
                                    verbose_name="testovací den"),
        ),
        migrations.AddField(
            model_name="answer",
            name="choices",
            field=models.JSONField(blank=True, default=list, verbose_name="zvolené možnosti"),
        ),
        migrations.AddField(
            model_name="answer",
            name="state",
            field=models.CharField(choices=[("answered", "Odpovězeno"), ("unknown", "Nevím"),
                                            ("na", "Netýká se"), ("missing", "Bez odpovědi")],
                                   default="answered", max_length=8, verbose_name="stav"),
        ),
        migrations.AddField(
            model_name="answer",
            name="text",
            field=models.TextField(blank=True, verbose_name="text"),
        ),
    ]
