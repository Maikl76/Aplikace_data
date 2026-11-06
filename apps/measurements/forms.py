"""
Formuláře pro zadávání měření.

Zadávací mřížka se negeneruje z kódu, ale z definice protokolu
(``ProtocolMetric.qualifier_combinations``). Nový protokol založený
v administraci tak dostane obrazovku sám od sebe.
"""

from django import forms

from apps.catalog.models import Protocol
from apps.subjects.models import Subject

from .models import TestSession
from .planning import DERIVED_PROTOCOLS


class TestSessionForm(forms.ModelForm):
    class Meta:
        model = TestSession
        fields = ["subject", "date", "location", "season_phase", "fatigue_rating",
                  "temperature_c", "humidity_pct", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 2}),
            "fatigue_rating": forms.NumberInput(attrs={"min": 1, "max": 10,
                                                       "inputmode": "numeric"}),
            "temperature_c": forms.NumberInput(attrs={"step": "0.1", "inputmode": "decimal"}),
            "humidity_pct": forms.NumberInput(attrs={"step": "1", "min": 0, "max": 100,
                                                     "inputmode": "numeric"}),
        }

    protocols = forms.ModelMultipleChoiceField(
        queryset=Protocol.objects.filter(is_active=True).exclude(code__in=DERIVED_PROTOCOLS),
        required=False, label="Testy", widget=forms.CheckboxSelectMultiple,
        help_text="Předvyplněno podle baterie sportu. Další test jde přidat i později.")

    field_order = ["subject", "date", "protocols", "location", "season_phase",
                   "fatigue_rating", "temperature_c", "humidity_pct", "note"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing = None   # testovací den, který už pro sportovce a datum existuje
        if user is not None:
            subjects = Subject.objects.for_user(user).filter(is_active=True)
            self.fields["subject"].queryset = subjects
            # Jméno (kdo ho smí vidět) je pro výběr srozumitelnější než kód.
            from apps.subjects.search import names_for

            names = names_for(subjects, user)
            self.fields["subject"].label_from_instance = (
                lambda s: f"{names[s.pk]} ({s.code})" if s.pk in names else s.code)
        for name, field in self.fields.items():
            if name == "protocols":
                field.label_from_instance = lambda p: p.name
                continue
            field.widget.attrs["class"] = f"{field.widget.attrs.get('class', '')} input".strip()

    def clean(self):
        cleaned = super().clean()
        subject, day = cleaned.get("subject"), cleaned.get("date")
        if subject is not None and day is not None:
            self.existing = (TestSession.objects.filter(subject=subject, date=day)
                             .exclude(pk=self.instance.pk).first())
            if self.existing is not None:
                self.add_error("date", forms.ValidationError(
                    "Tento sportovec už má v ten den testovací den – testy přidejte do něj.",
                    code="duplicate"))
        return cleaned


class AddProtocolForm(forms.Form):
    protocol = forms.ModelChoiceField(
        # Odvozené ukazatele (DSI, EUR) se neměří, dopočítají se samy.
        queryset=Protocol.objects.filter(is_active=True).exclude(code__in=DERIVED_PROTOCOLS)
        .order_by("name"),
        label="Protokol", empty_label="vyberte test…",
        widget=forms.Select(attrs={"class": "input w-auto flex-1 min-w-[12rem]"}),
    )
    # Tentýž test podruhé v jednom dni (před a po zátěži): nové provedení
    # vedle hlavního, do trendů a pravidel jde dál to hlavní.
    repeat = forms.BooleanField(required=False, label="opakované měření (např. po zátěži)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["protocol"].label_from_instance = lambda p: p.name


def field_name(protocol_metric, combo: dict, trial_number: int) -> str:
    """
    Název vstupního pole. Kvalifikátory jsou v něm zakódované, aby se
    hodnota při uložení dala zařadit bez dalšího dotazu do databáze.
    """
    speed = "" if combo["speed"] is None else f"{combo['speed']:g}"
    return "|".join([
        "v", str(protocol_metric.pk), combo["side"], combo["mode"],
        speed, combo["segment"], str(trial_number),
    ])


def parse_value(raw) -> float | None:
    """
    Číslo z políčka: „12,5“, „12.5“ i čas „1:23,45“ (min:s – převede se
    na sekundy). Nesmyslný vstup vrátí None.
    """
    text = str(raw).strip().replace(",", ".").replace(" ", "")
    if not text:
        return None
    try:
        if ":" in text:
            minutes, seconds = text.split(":", 1)
            if float(seconds) >= 60:
                return None
            sign = -1 if minutes.startswith("-") else 1
            return sign * (abs(int(minutes)) * 60 + float(seconds))
        return float(text)
    except ValueError:
        return None


def parse_field_name(name: str) -> dict | None:
    parts = name.split("|")
    if len(parts) != 7 or parts[0] != "v":
        return None
    _, pm_id, side, mode, speed, segment, trial = parts
    try:
        return {
            "protocol_metric_id": int(pm_id),
            "side": side,
            "mode": mode,
            "speed": float(speed) if speed else None,
            "segment": segment,
            "trial_number": int(trial),
        }
    except ValueError:
        return None


def trial_columns(protocol_run, wanted: int | None = None) -> int:
    """Kolik sloupců pokusů: podle protokolu, víc když jich už je, nebo když si o ně někdo řekl."""
    highest = max(protocol_run.trials.values_list("number", flat=True), default=0)
    return max(protocol_run.protocol.default_trials, highest, min(wanted or 0, 12))


def odd_trial(values: list[tuple[int, float]]) -> tuple[int, float] | None:
    """Pokus, který se nejvíc liší od průměru ostatních: (číslo, odchylka v %)."""
    best = None
    for number, value in values:
        others = [v for n, v in values if n != number]
        mean = sum(others) / len(others) if others else 0
        if not mean:
            continue
        deviation = abs(value - mean) / abs(mean) * 100
        if best is None or deviation > best[1]:
            best = (number, deviation)
    return best


def row_warnings(metric, values: list[tuple[int, float]], out_of_range: list[int]) -> list[str]:
    """
    Kontrola hned při zadávání – stejná slova, jaká pak říká krok Kontrola:
    rozptyl platných pokusů nad mezí metriky a hodnoty mimo věrohodný rozsah.
    """
    from apps.reports.results import trial_cv

    out = []
    if metric.trial_cv_limit is not None and len(values) >= 2:
        cv = trial_cv([v for _, v in values])
        if cv is not None and cv > metric.trial_cv_limit:
            text = f"Pokusy se liší o {cv:.0f} % (mez {metric.trial_cv_limit:g} %)"
            if worst := odd_trial(values):
                text += f": pokus {worst[0]} se liší o {worst[1]:.0f} % od ostatních – změřit znovu?"
            out.append(text + ("" if worst else " – změřit znovu?"))
    if out_of_range:
        unit = f" {metric.unit}" if metric.unit and metric.unit != "-" else ""
        if metric.plausible_min is not None and metric.plausible_max is not None:
            span = f"{metric.plausible_min:g}–{metric.plausible_max:g}{unit}"
        elif metric.plausible_min is not None:
            span = f"od {metric.plausible_min:g}{unit}"
        else:
            span = f"do {metric.plausible_max:g}{unit}"
        out.append(f"{'Pokus' if len(out_of_range) == 1 else 'Pokusy'} "
                   f"{', '.join(str(n) for n in out_of_range)} mimo věrohodný rozsah ({span}) – "
                   "překlep, nebo chyba přístroje?")
    return out


def build_grid(protocol_run, *, columns: int | None = None) -> list[dict]:
    """Řádky zadávací mřížky i s už uloženými hodnotami a kontrolou pokusů."""
    from .models import Measurement

    existing = {
        (m.metric_id, m.side, m.mode, m.speed, m.segment, m.trial.number): m
        for m in Measurement.objects.filter(trial__protocol_run=protocol_run)
        .select_related("trial", "metric")
    }
    invalid = set(protocol_run.trials.filter(is_valid=False).values_list("number", flat=True))

    trials = list(range(1, trial_columns(protocol_run, columns) + 1))
    rows = []
    from apps.analytics.derived import DERIVED_METRICS

    for pm in protocol_run.protocol.protocol_metrics.select_related("metric").all():
        # Vypočtené hodnoty (W/kg z W a hmotnosti) se nezadávají – přepočítají se samy.
        if pm.metric.code in DERIVED_METRICS:
            continue
        for combo in pm.qualifier_combinations():
            cells = []
            for trial_number in trials:
                key = (pm.metric_id, combo["side"], combo["mode"],
                       combo["speed"], combo["segment"], trial_number)
                measurement = existing.get(key)
                cells.append({
                    "name": field_name(pm, combo, trial_number),
                    # Formát podle metriky – síla v newtonech nemá důvod
                    # ukazovat tři desetinná místa.
                    "value": ("" if measurement is None
                              else f"{measurement.value:.{pm.metric.decimals}f}"),
                    "quality": measurement.quality if measurement else "",
                    "invalid": trial_number in invalid,
                })
            valid = [(n, existing[(pm.metric_id, combo["side"], combo["mode"], combo["speed"],
                                   combo["segment"], n)].value)
                     for n in trials if n not in invalid
                     and (pm.metric_id, combo["side"], combo["mode"], combo["speed"],
                          combo["segment"], n) in existing]
            outside = [n for n in trials
                       if (m := existing.get((pm.metric_id, combo["side"], combo["mode"],
                                              combo["speed"], combo["segment"], n)))
                       and m.quality == Measurement.Quality.OUT_OF_RANGE]
            rows.append({
                "protocol_metric": pm,
                "metric": pm.metric,
                # U časů v sekundách se nabízí stopky; delší časy jde psát jako min:s.
                "is_time": pm.metric.unit == "s",
                "long_time": pm.metric.unit == "s" and (pm.metric.plausible_max or 0) > 60,
                "combo": combo,
                "label": _combo_label(combo),
                "cells": cells,
                "warnings": row_warnings(pm.metric, valid, outside),
            })
    return rows


def _combo_label(combo: dict) -> str:
    from .models import Mode, Side

    bits = []
    if combo["segment"]:
        bits.append(combo["segment"])
    if combo["side"] and combo["side"] != Side.BILATERAL:
        bits.append(Side(combo["side"]).label.lower())
    if combo["mode"]:
        bits.append(Mode(combo["mode"]).label.lower())
    if combo["speed"] is not None:
        bits.append(f"{combo['speed']:g}°/s")
    return " · ".join(bits)
