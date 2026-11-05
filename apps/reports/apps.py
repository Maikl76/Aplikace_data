from django.apps import AppConfig
from django.core.checks import Tags, Warning, register


class ReportsConfig(AppConfig):
    name = "apps.reports"
    verbose_name = "Zprávy"

    def ready(self):
        register(check_remote_model, Tags.security)


def check_remote_model(app_configs, **kwargs):
    """Cloudový model mimo zkušební provoz: aplikace ho nepoužije a řekne to už při startu."""
    from . import llm

    if reason := llm.blocked_reason():
        return [Warning(reason, hint="Nastavte LLM_BASE_URL na lokální model, nebo pro zkušební "
                                     "provoz zapněte DEMO_MODE.", id="reports.W001")]
    return []
