from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0010_druhy_otazek")]

    operations = [
        migrations.AddField(
            model_name="metricdef",
            name="mdc_source",
            field=models.CharField(
                blank=True,
                help_text="Odkud hodnota je: citace, nebo vlastní reliability studie (kdy, kolik osob).",
                max_length=300, verbose_name="zdroj MDC"),
        ),
    ]
