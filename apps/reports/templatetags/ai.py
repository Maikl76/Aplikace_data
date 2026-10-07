from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()


@register.simple_tag
def ai_model_select():
    """Výběr modelu u „Vytvořit zprávu“ – jen když je z čeho vybírat."""
    from apps.reports import ai_models, llm

    if not llm.is_enabled():
        return ""
    choices = ai_models.choices()
    if len(choices) < 2:
        return ""
    options = format_html_join("", '<option value="{}">{}</option>', choices)
    return format_html('<select name="model" class="input w-auto" '
                       'title="Který model napíše souhrn zprávy">{}</select>', options)
