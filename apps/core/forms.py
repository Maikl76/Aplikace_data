from django.contrib.auth.forms import AuthenticationForm

FIELD_CSS = "input mt-1"


class LoginForm(AuthenticationForm):
    """
    Přihlašovací formulář s viditelnými poli.

    Tailwind odstraní prohlížečům výchozí rámečky vstupních polí, takže
    holé {{ form.as_p }} vykreslilo pole pro heslo jako prázdné místo –
    vypadalo to, že tam žádné není.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"class": FIELD_CSS, "autocomplete": "username", "autofocus": True})
        self.fields["password"].widget.attrs.update(
            {"class": FIELD_CSS, "autocomplete": "current-password"})
