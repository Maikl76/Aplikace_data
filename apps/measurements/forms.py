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
        fields = ["subject", "date", "location", "season_phase", "fatigue_rating", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 2}),
            "fatigue_rating": forms.NumberInput(attrs={"min": 1, "max": 10,
                                                       "inputmode": "numeric"}),
        }

    protocols = forms.ModelMultipleChoiceField(
        queryset=Protocol.objects.filter(is_active=True).exclude(code__in=DERIVED_PROTOCOLS),
        required=False, label="Testy", widget=forms.CheckboxSelectMultiple,
        help_text="Předvyplněno podle baterie sportu. Další test jde přidat i později.")

    field_order = ["subject", "date", "protocols", "location", "season_phase",
                   "fatigue_rating", "note"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
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


class AddProtocolForm(forms.Form):
    protocol = forms.ModelChoiceField(
        # Odvozené ukazatele (DSI, EUR) se neměří, dopočítají se samy.
        queryset=Protocol.objects.filter(is_active=True).exclude(code__in=DERIVED_PROTOCOLS)
        .order_by("name"),
        label="Protokol", empty_label="vyberte test…",
        widget=forms.Select(attrs={"class": "input w-auto flex-1 min-w-[12rem]"}),
    )

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


def build_grid(protocol_run) -> list[dict]:
    """Řádky zadávací mřížky i s už uloženými hodnotami."""
    from .models import Measurement

    existing = {
        (m.metric_id, m.side, m.mode, m.speed, m.segment, m.trial.number): m
        for m in Measurement.objects.filter(trial__protocol_run=protocol_run)
        .select_related("trial", "metric")
    }

    trials = list(range(1, protocol_run.protocol.default_trials + 1))
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
                })
            rows.append({
                "protocol_metric": pm,
                "metric": pm.metric,
                "combo": combo,
                "label": _combo_label(combo),
                "cells": cells,
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
