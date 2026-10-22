from django import forms
from django.contrib.auth import password_validation

CSS = "input mt-1"


class RegistrationForm(forms.Form):
    email = forms.EmailField(label="E‑mail (přihlašovací jméno)",
                             widget=forms.EmailInput(attrs={"class": CSS, "autocomplete": "email"}))
    password1 = forms.CharField(label="Heslo", widget=forms.PasswordInput(
        attrs={"class": CSS, "autocomplete": "new-password"}))
    password2 = forms.CharField(label="Heslo znovu", widget=forms.PasswordInput(
        attrs={"class": CSS, "autocomplete": "new-password"}))

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Hesla se neshodují.")
        elif p1:
            try:
                password_validation.validate_password(p1)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned
