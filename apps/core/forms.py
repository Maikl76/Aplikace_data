from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .middleware import NOT_READY, NOT_READY_MESSAGE

FIELD_CSS = "input mt-1"


class LoginForm(AuthenticationForm):
    """
    Přihlašovací formulář s viditelnými poli.

    Tailwind odstraní prohlížečům výchozí rámečky vstupních polí, takže
    holé {{ form.as_p }} vykreslilo pole pro heslo jako prázdné místo –
    vypadalo to, že tam žádné není.
    """

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Uživatelské jméno nebo heslo nesedí. Pozor na velká a malá písmena.",
        "inactive": "Účet je vypnutý. Obraťte se na správce.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"class": FIELD_CSS, "autocomplete": "username", "autofocus": True})
        self.fields["password"].widget.attrs.update(
            {"class": FIELD_CSS, "autocomplete": "current-password"})

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        # Trenér: vlastní omezený pohled ještě není, účet by viděl všechno.
        if user.role in NOT_READY and not user.is_superuser:
            raise forms.ValidationError(NOT_READY_MESSAGE, code="role_not_ready")
