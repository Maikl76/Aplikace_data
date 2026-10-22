"""Ukázková data musí dávat smysl – kolegové je uvidí jako první."""

from django.core.management import call_command

from apps.measurements.models import Measurement, TestSession
from apps.subjects.models import Subject


def _values(session, code, protocol=None):
    qs = Measurement.objects.filter(trial__protocol_run__session=session, metric__code=code)
    if protocol:
        qs = qs.filter(trial__protocol_run__protocol__code=protocol)
    return list(qs.values_list("value", flat=True))


def test_telo_drzi_pohromade(db):
    call_command("seed_demo", subjects=6, sessions=3, seed=7, verbosity=0)
    checked = 0
    for subject in Subject.objects.all():
        sessions = list(TestSession.objects.filter(subject=subject).order_by("date"))
        heights = {v for s in sessions for v in _values(s, "height")}
        if not heights:
            continue
        assert len(heights) == 1                       # výška se mezi měřeními nemění
        for session in sessions:
            mass = _values(session, "body_mass", "bodycomp")
            if not mass:
                continue
            mass = mass[0]
            # Plošina při CMJ váží totéž tělo – liší se o deka, ne o kila.
            for plate in _values(session, "body_mass", "cmj"):
                assert abs(plate - mass) <= 0.25
            fat = _values(session, "body_fat_pct")[0]
            lean = _values(session, "lean_mass")[0]
            assert abs(lean - mass * (1 - fat / 100)) <= 0.15
            segments = Measurement.objects.filter(trial__protocol_run__session=session,
                                                  metric__code="segment_mass")
            total = sum(m.value for m in segments)
            assert 0 < total < mass                     # bez hlavy a krku
            by_seg = {}
            for m in segments:
                by_seg.setdefault(m.segment, {})[m.side] = m.value
                lean_seg = Measurement.objects.get(
                    trial=m.trial, metric__code="segment_lean_mass", side=m.side,
                    segment=m.segment).value
                assert 0 < lean_seg < m.value
            for sides in by_seg.values():
                assert abs(sides["L"] - sides["R"]) / max(sides.values()) < 0.08
            checked += 1
    assert checked >= 3
