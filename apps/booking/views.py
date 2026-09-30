"""Objednávky v aplikaci: vyřizování žádostí, nabídka a volné termíny."""

from datetime import date, datetime, time, timedelta
from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.catalog.models import Protocol
from apps.core.audit import record
from apps.core.models import AuditLog
from apps.measurements.planning import DERIVED_PROTOCOLS

from . import services
from .models import BookingRequest, Offer, Slot


def lab_only(view):
    """Objednávky obsahují jména a zdravotní údaje – jen pro role, které vidí identitu."""
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.sees_identity:
            raise PermissionDenied("Objednávky vyřizuje laboratoř.")
        return view(request, *args, **kwargs)
    return wrapper


def _org(request):
    return request.user.organization


# --- žádosti -----------------------------------------------------------------

TABS = [(BookingRequest.Status.NEW, "Nové"), (BookingRequest.Status.VERIFY, "Čekají na e-mail"),
        (BookingRequest.Status.APPROVED, "Schválené"), (BookingRequest.Status.REJECTED, "Zamítnuté")]


@lab_only
def request_list(request):
    status = request.GET.get("stav", BookingRequest.Status.NEW)
    base = BookingRequest.objects.for_user(request.user)
    counts = dict(base.values_list("status").annotate(n=Count("pk")))
    bookings = list(base.filter(status=status).select_related("slot")
                    .annotate(osob=Count("participants", distinct=True))
                    .prefetch_related("offers")[:200])
    return render(request, "booking/list.html", {
        "bookings": bookings, "status": status,
        "tabs": [(value, label, counts.get(value, 0)) for value, label in TABS],
        "public_url": request.build_absolute_uri("/objednavka/"),
    })


@lab_only
def request_detail(request, pk):
    booking = get_object_or_404(BookingRequest.objects.for_user(request.user)
                                .select_related("slot", "decided_by"), pk=pk)
    participants = list(booking.participants.select_related("subject", "session"))
    day = timezone.localtime(booking.slot.start).date()
    for p in participants:
        p.vek = p.age_on(day)
        if p.subject is None and booking.status == BookingRequest.Status.NEW:
            p.shoda, p.shoda_jak = services.match(p, booking.organization)
    record(request, AuditLog.Action.VIEW, booking)

    slots = []
    if booking.status == BookingRequest.Status.NEW:
        slots = [s for s in Slot.available(booking.organization)
                 if s.pk != booking.slot_id and s.volno >= len(participants)]
    return render(request, "booking/detail.html", {
        "booking": booking, "participants": participants, "slots": slots,
        "protocols": booking.protocols(),
    })


@lab_only
def request_decide(request, pk):
    booking = get_object_or_404(BookingRequest.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("booking_detail", pk=pk)
    note = request.POST.get("zprava", "").strip()
    try:
        if request.POST.get("akce") == "schvalit":
            if (new_slot := request.POST.get("termin")) and new_slot != str(booking.slot_id):
                slot = get_object_or_404(Slot, pk=new_slot, organization=booking.organization)
                if slot.free() < booking.participants.count():
                    raise services.BookingError("Na vybraný termín se účastníci nevejdou.")
                booking.slot = slot
                booking.save(update_fields=["slot"])
            participants = services.approve(booking, request.user, note=note)
            record(request, AuditLog.Action.UPDATE, booking, akce="schváleno")
            created = sum(1 for p in participants if p.subject.note.endswith(booking.number))
            messages.success(request, f"Objednávka schválena: {len(participants)} testovacích dnů"
                                      f" založeno ({created} nových sportovců).")
            event = "schvalena"
        else:
            services.reject(booking, request.user, note=note)
            record(request, AuditLog.Action.UPDATE, booking, akce="zamítnuto")
            messages.success(request, "Objednávka zamítnuta.")
            event = "zamitnuta"
    except services.BookingError as exc:
        messages.error(request, str(exc))
        return redirect("booking_detail", pk=pk)

    if not services.notify(request, booking, event):
        messages.warning(request, "E-mail klientovi se nepodařilo odeslat – dejte mu vědět jinak.")
    return redirect("booking_detail", pk=pk)


# --- nabídka ----------------------------------------------------------------

class OfferForm(forms.ModelForm):
    class Meta:
        model = Offer
        fields = ["kind", "name", "description", "price", "duration_min", "protocols",
                  "order", "is_active"]
        widgets = {"protocols": forms.CheckboxSelectMultiple,
                   "description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["protocols"].queryset = (Protocol.objects.filter(is_active=True)
                                             .exclude(code__in=DERIVED_PROTOCOLS).order_by("name"))
        self.fields["protocols"].label_from_instance = lambda p: p.name
        for name, field in self.fields.items():
            if name not in ("protocols", "is_active"):
                field.widget.attrs["class"] = "input mt-1"


@lab_only
def offer_list(request):
    offers = (Offer.objects.for_user(request.user).prefetch_related("protocols")
              .annotate(objednavek=Count("requests")))
    return render(request, "booking/offers.html", {"offers": offers})


@lab_only
def offer_edit(request, pk=None):
    offer = (get_object_or_404(Offer.objects.for_user(request.user), pk=pk) if pk
             else Offer(organization=_org(request)))
    form = OfferForm(request.POST or None, instance=offer)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Uloženo: {offer.name}.")
        return redirect("booking_offers")
    return render(request, "booking/offer_form.html", {"form": form, "offer": offer})


# --- volné termíny -----------------------------------------------------------

class SlotSeriesForm(forms.Form):
    """Vypsání termínů najednou: dny × časy po zadaném kroku."""

    WEEKDAYS = [(0, "po"), (1, "út"), (2, "st"), (3, "čt"), (4, "pá"), (5, "so"), (6, "ne")]

    date_from = forms.DateField(label="Od", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    date_to = forms.DateField(label="Do", required=False,
                              widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                              help_text="Prázdné = jen jeden den.")
    weekdays = forms.TypedMultipleChoiceField(label="Dny v týdnu", choices=WEEKDAYS, coerce=int,
                                              initial=[0, 1, 2, 3, 4], required=False,
                                              widget=forms.CheckboxSelectMultiple)
    time_from = forms.TimeField(label="První termín", initial=time(8, 0),
                                widget=forms.TimeInput(attrs={"type": "time"}))
    time_to = forms.TimeField(label="Poslední začíná nejpozději", initial=time(14, 0),
                              widget=forms.TimeInput(attrs={"type": "time"}))
    step_min = forms.IntegerField(label="Po kolika minutách", initial=60, min_value=10,
                                  max_value=600)
    duration_min = forms.IntegerField(label="Délka (min)", initial=60, min_value=10,
                                      max_value=600)
    capacity = forms.IntegerField(label="Kapacita (osob)", initial=1, min_value=1, max_value=60)
    location = forms.CharField(label="Laboratoř / místo", required=False, max_length=120)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "weekdays":
                field.widget.attrs["class"] = "input mt-1"

    def clean(self):
        data = super().clean()
        start, end = data.get("date_from"), data.get("date_to") or data.get("date_from")
        if start and end and end < start:
            self.add_error("date_to", "Konec je před začátkem.")
        if start and end and (end - start).days > 120:
            self.add_error("date_to", "Najednou nejvýš 4 měsíce.")
        if data.get("time_from") and data.get("time_to") and data["time_to"] < data["time_from"]:
            self.add_error("time_to", "Poslední termín je před prvním.")
        return data

    def starts(self) -> list[datetime]:
        data = self.cleaned_data
        day, end = data["date_from"], data.get("date_to") or data["date_from"]
        weekdays = set(data["weekdays"]) if data.get("date_to") else {day.weekday()}
        tz = timezone.get_current_timezone()
        out = []
        while day <= end:
            if day.weekday() in weekdays:
                moment = datetime.combine(day, data["time_from"], tzinfo=tz)
                last = datetime.combine(day, data["time_to"], tzinfo=tz)
                while moment <= last:
                    out.append(moment)
                    moment += timedelta(minutes=data["step_min"])
            day += timedelta(days=1)
        return out


@lab_only
def slot_list(request):
    org = _org(request)
    form = SlotSeriesForm(request.POST or None, initial={"date_from": date.today()})
    if request.method == "POST" and request.POST.get("akce") == "smazat":
        slot = get_object_or_404(Slot.objects.for_user(request.user), pk=request.POST.get("slot"))
        if slot.requests.exists():
            slot.is_active = False
            slot.save(update_fields=["is_active"])
            messages.info(request, "Termín má objednávky – jen se přestal nabízet.")
        else:
            slot.delete()
            messages.success(request, "Termín smazán.")
        return redirect("booking_slots")
    if request.method == "POST" and form.is_valid():
        existing = set(Slot.objects.filter(organization=org, location=form.cleaned_data["location"])
                       .values_list("start", flat=True))
        new = [Slot(organization=org, start=moment, location=form.cleaned_data["location"],
                    duration_min=form.cleaned_data["duration_min"],
                    capacity=form.cleaned_data["capacity"])
               for moment in form.starts() if moment not in existing and moment > timezone.now()]
        Slot.objects.bulk_create(new)
        messages.success(request, f"Vypsáno {len(new)} termínů.")
        return redirect("booking_slots")

    slots = list(Slot.objects.for_user(request.user).filter(start__gte=timezone.now() - timedelta(hours=12))
                 .annotate(pocet_objednavek=Count("requests")))
    by_day: dict = {}
    for slot in slots:
        slot.obsazeno = slot.booked()
        by_day.setdefault(timezone.localtime(slot.start).date(), []).append(slot)
    return render(request, "booking/slots.html", {"form": form, "by_day": by_day})
