from datetime import date

from django import forms
from django.utils import timezone

from .models import Consent, Sex, Sport, Subject
from .services import FORM_CONSENTS


class SubjectForm(forms.Form):
    first_name = forms.CharField(label="Jméno", max_length=100)
    last_name = forms.CharField(label="Příjmení", max_length=100)
    birth_date = forms.DateField(label="Datum narození",
                                 widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    sex = forms.ChoiceField(label="Pohlaví", choices=Sex.choices, widget=forms.RadioSelect)
    sport = forms.ModelChoiceField(label="Sport", queryset=Sport.objects.none(), required=False,
                                   empty_label="— vyberte —")
    new_sport = forms.CharField(label="nebo nový sport", max_length=100, required=False)
    category = forms.CharField(label="Kategorie", max_length=60, required=False,
                               help_text="Např. dorost. Podle ní se vybírá baterie testů.")
    level = forms.ChoiceField(label="Úroveň", choices=Subject.Level.choices,
                              initial=Subject.Level.TRAINED)
    dominant_side = forms.ChoiceField(label="Dominantní strana", required=False,
                                      choices=[("", "neuvedeno"), ("L", "levá"), ("R", "pravá")])
    email = forms.EmailField(label="E-mail", required=False)
    phone = forms.CharField(label="Telefon", max_length=40, required=False)
    note = forms.CharField(label="Poznámka", required=False,
                           widget=forms.Textarea(attrs={"rows": 2}),
                           help_text="Provozní poznámka. Nikdy diagnózy ani zdravotní údaje.")
    consents = forms.MultipleChoiceField(
        label="Souhlasy", required=False, widget=forms.CheckboxSelectMultiple,
        choices=[(s.value, s.label) for s in FORM_CONSENTS],
        initial=[Consent.Scope.TESTING, Consent.Scope.LONGITUDINAL])
    confirm_duplicate = forms.BooleanField(required=False)

    def __init__(self, *args, sports=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sport"].queryset = sports if sports is not None else Sport.objects.none()
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.RadioSelect, forms.CheckboxSelectMultiple,
                                             forms.CheckboxInput)):
                field.widget.attrs.setdefault("class", "input mt-1")
        self.fields["first_name"].widget.attrs["autofocus"] = True

    def clean_birth_date(self):
        value = self.cleaned_data["birth_date"]
        if value > timezone.localdate():
            raise forms.ValidationError("Datum narození je v budoucnosti.")
        if value < date(1900, 1, 1):
            raise forms.ValidationError("Zkontrolujte rok narození.")
        return value
