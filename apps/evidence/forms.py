from django import forms
from django.db.models import Q

from apps.catalog.models import MetricDef, Protocol
from apps.rules.models import Rule

from .models import Article


class ArticleForm(forms.ModelForm):
    rules = forms.ModelMultipleChoiceField(
        Rule.objects.none(), required=False, label="pravidla",
        widget=forms.CheckboxSelectMultiple,
        help_text="Když pravidlo u měření najde nález, článek se ve zprávě cituje vždy.")

    class Meta:
        model = Article
        fields = ["title", "authors", "journal", "year", "doi", "pmid", "url", "abstract",
                  "status", "evidence_level", "key_finding", "limitations", "curator_note",
                  "sports", "population_sport", "population_sex", "population_age_min",
                  "population_age_max", "population_level", "sample_size",
                  "metrics", "protocols"]
        widgets = {
            "title": forms.Textarea(attrs={"rows": 2}),
            "authors": forms.TextInput(),
            "abstract": forms.Textarea(attrs={"rows": 6}),
            "key_finding": forms.Textarea(attrs={"rows": 3}),
            "limitations": forms.Textarea(attrs={"rows": 2}),
            "curator_note": forms.Textarea(attrs={"rows": 2}),
            "metrics": forms.CheckboxSelectMultiple,
            "sports": forms.CheckboxSelectMultiple,
            "protocols": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        mine = Q(organization=organization) | Q(organization__isnull=True)
        self.fields["metrics"].queryset = (MetricDef.objects.filter(mine, is_active=True)
                                           .order_by("family", "name"))
        self.fields["protocols"].queryset = (Protocol.objects.filter(mine, is_active=True)
                                             .order_by("name"))
        from apps.subjects.models import Sport

        self.fields["sports"].queryset = Sport.objects.filter(mine).order_by("name")
        self.fields["rules"].queryset = Rule.objects.filter(mine).order_by("name", "-version")
        if self.instance.pk:
            self.fields["rules"].initial = list(
                self.instance.rule_articles.values_list("rule_id", flat=True))
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs.setdefault("class", "input mt-1")

    def clean_doi(self):
        doi = self.cleaned_data["doi"].strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix):]
        return doi.strip()

    def clean(self):
        data = super().clean()
        low, high = data.get("population_age_min"), data.get("population_age_max")
        if low and high and low > high:
            self.add_error("population_age_max", "Věk do je menší než věk od.")
        for key in ("doi", "pmid"):
            value = data.get(key)
            if value and (Article.objects.filter(**{f"{key}__iexact": value})
                          .exclude(pk=self.instance.pk).exists()):
                self.add_error(key, "Článek s tímto údajem už v knihovně je.")
        return data

    def save(self, commit=True):
        from apps.rules.models import RuleArticle

        article = super().save(commit=commit)
        if commit:
            chosen = set(self.cleaned_data.get("rules") or [])
            article.rule_articles.exclude(rule__in=chosen).delete()
            for rule in chosen:
                RuleArticle.objects.get_or_create(rule=rule, article=article)
        return article
