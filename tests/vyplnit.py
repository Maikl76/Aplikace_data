"""Pomocník testů: vyplní všechny ukazatele zadávací mřížky provedení (= hotový test)."""

from apps.analytics.derived import DERIVED_METRICS
from apps.measurements.models import Measurement, Trial


def vyplnit_vse(run, value=30.0, number=1):
    """Uloží hodnotu do každého řádku mřížky – s kvalifikátory jako zadávací formulář."""
    trial, _ = Trial.objects.get_or_create(protocol_run=run, number=number)
    for pm in run.protocol.protocol_metrics.select_related("metric"):
        if pm.metric.code in DERIVED_METRICS:
            continue
        for combo in pm.qualifier_combinations():
            Measurement.objects.get_or_create(trial=trial, metric=pm.metric, **combo,
                                              defaults={"value": value})
    return trial
