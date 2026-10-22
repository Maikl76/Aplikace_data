"""Stav pokusů (platný / neplatný s důvodem) pro zadávací mřížku."""

from .models import Trial


def trial_states(run) -> list[dict]:
    """Pro každý sloupec mřížky: číslo pokusu, zda je platný a důvod neplatnosti."""
    by_number = {t.number: t for t in run.trials.all()}
    states = []
    for number in range(1, run.protocol.default_trials + 1):
        trial = by_number.get(number)
        states.append({"number": number, "is_valid": trial.is_valid if trial else True,
                       "invalid_reason": trial.invalid_reason if trial else ""})
    return states


def apply_trial_states(run, post) -> list[int]:
    """
    Zapíše z formuláře, které pokusy jsou neplatné (a proč). Vrací čísla
    neplatných pokusů. Neplatný pokus se nemaže – zůstane v datech i s důvodem,
    jen se s ním nepočítá.
    """
    if post.get("pokusy_stav") != "1":        # formulář bez sloupce stavu (import, testy)
        return []
    invalid = []
    for number in range(1, run.protocol.default_trials + 1):
        wanted_invalid = f"neplatny|{number}" in post
        reason = (post.get(f"duvod|{number}") or "").strip()[:255] if wanted_invalid else ""
        trial = run.trials.filter(number=number).first()
        if trial is None:
            if not wanted_invalid:
                continue
            trial = Trial(protocol_run=run, number=number)
        if trial.is_valid != (not wanted_invalid) or trial.invalid_reason != reason:
            trial.is_valid, trial.invalid_reason = not wanted_invalid, reason
            trial.save()
        if wanted_invalid:
            invalid.append(number)
    return invalid
