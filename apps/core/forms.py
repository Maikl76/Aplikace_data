from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from .middleware import NOT_READY, NOT_READY_MESSAGE
from .models import Role
from .roles import COLLEAGUE_ROLES

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


class ColleagueForm(forms.Form):
    """Nový účet kolegy; heslo si nastaví sám z odkazu."""

    first_name = forms.CharField(label="Jméno", max_length=150,
                                 widget=forms.TextInput(attrs={"class": FIELD_CSS}))
    last_name = forms.CharField(label="Příjmení", max_length=150,
                                widget=forms.TextInput(attrs={"class": FIELD_CSS}))
    role = forms.ChoiceField(label="Role", choices=[(r, Role(r).label) for r in COLLEAGUE_ROLES],
                             initial=Role.LAB, widget=forms.Select(attrs={"class": FIELD_CSS}))
    username = forms.CharField(label="Přihlašovací jméno", max_length=150, required=False,
                               help_text="Prázdné = jmeno.prijmeni bez diakritiky.",
                               widget=forms.TextInput(attrs={"class": FIELD_CSS,
                                                             "autocomplete": "off"}))
    email = forms.EmailField(label="E‑mail (nepovinný)", required=False,
                             widget=forms.EmailInput(attrs={"class": FIELD_CSS}))


class PasswordSetForm(forms.Form):
    """Nastavení hesla z jednorázového odkazu."""

    password1 = forms.CharField(label="Heslo", widget=forms.PasswordInput(
        attrs={"class": FIELD_CSS, "autocomplete": "new-password", "autofocus": True}))
    password2 = forms.CharField(label="Heslo znovu", widget=forms.PasswordInput(
        attrs={"class": FIELD_CSS, "autocomplete": "new-password"}))

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Hesla se neshodují.")
        elif p1:
            try:
                password_validation.validate_password(p1, self.user)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned
