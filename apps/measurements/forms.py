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


class TestSessionForm(forms.ModelForm):
    class Meta:
        model = TestSession
        fields = ["subject", "date", "location", "season_phase", "fatigue_rating", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
            "fatigue_rating": forms.NumberInput(attrs={"min": 1, "max": 10,
                                                       "inputmode": "numeric"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["subject"].queryset = (
                Subject.objects.for_user(user).filter(is_active=True)
            )
        for field in self.fields.values():
            css = "w-full border border-slate-300 rounded px-3 py-2"
            field.widget.attrs["class"] = f"{field.widget.attrs.get('class', '')} {css}".strip()


class AddProtocolForm(forms.Form):
    protocol = forms.ModelChoiceField(
        queryset=Protocol.objects.filter(is_active=True),
        label="Protokol",
        widget=forms.Select(attrs={"class": "border border-slate-300 rounded px-3 py-2"}),
    )


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
    for pm in protocol_run.protocol.protocol_metrics.select_related("metric").all():
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
