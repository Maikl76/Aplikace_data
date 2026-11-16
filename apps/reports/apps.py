from django.apps import AppConfig
from django.core.checks import Tags, Warning, register


class ReportsConfig(AppConfig):
    name = "apps.reports"
    verbose_name = "Zprávy"

    def ready(self):
        from django.db.models.signals import post_delete

        from .models import Report

        register(check_remote_model, Tags.security)
        # Číslo smazané zprávy se už nepřidělí – ať se maže odkudkoli
        # (aplikace, administrace, konzole).
        post_delete.connect(_burn_number, sender=Report, dispatch_uid="reports.burn_number")


def _burn_number(sender, instance, **kwargs):
    from . import services

    services.burn_number(instance.organization_id, instance.report_number)


def check_remote_model(app_configs, **kwargs):
    """Cloudový model mimo zkušební provoz: aplikace ho nepoužije a řekne to už při startu."""
    from . import llm

    if reason := llm.blocked_reason():
        return [Warning(reason, hint="Nastavte LLM_BASE_URL na lokální model, nebo pro zkušební "
                                     "provoz zapněte DEMO_MODE.", id="reports.W001")]
    return []
