from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.measurements.models import Measurement, TestSession
from apps.reports.models import Report
from apps.subjects.models import Subject


@login_required
def dashboard(request):
    """Přehled laboratoře: co je nového a co čeká na mě."""
    from datetime import timedelta

    from django.shortcuts import redirect

    from apps.core.models import Role

    if not request.user.is_superuser:
        if request.user.role == Role.ATHLETE:
            return redirect("portal_home")
        if request.user.role == Role.COACH:
            return redirect("coach_home")

    from apps.ingest.models import ImportBatch
    from apps.subjects.search import names_for

    today = timezone.localdate()
    sessions = TestSession.objects.for_user(request.user)
    recent = list(sessions.select_related("subject", "subject__sport")
                  .prefetch_related("protocol_runs__protocol").order_by("-date", "-pk")[:8])
    names = names_for([s.subject for s in recent], request.user)
    for s in recent:
        s.jmeno = names.get(s.subject_id) or s.subject.code
        s.protokoly = sorted({run.protocol.name for run in s.protocol_runs.all()})

    drafts = (Report.objects.for_user(request.user).filter(status=Report.Status.DRAFT)
              .select_related("subject").order_by("-created_at"))
    draft_names = names_for([r.subject for r in drafts[:6]], request.user)
    draft_list = list(drafts[:6])
    for r in draft_list:
        r.jmeno = draft_names.get(r.subject_id) or r.subject.code

    from apps.core import access

    objednavky = []
    if access.can(request.user, "bookings"):
        from apps.booking.models import BookingRequest

        objednavky = list(BookingRequest.objects.for_user(request.user)
                          .filter(status=BookingRequest.Status.NEW)
                          .select_related("slot").order_by("slot__start")[:5])

    from apps.core.daily import daily_steps
    from apps.core.middleware import READ_ONLY
    from apps.subjects import retest

    pripominky = None
    if access.can(request.user, "measure"):
        # Jednou denně (pojistka za příkaz udrzba): záloha, úklid, připomínky, stav správci.
        from apps.core import maintenance

        udrzba = maintenance.ensure_today(
            request.user.organization,
            booking_url=retest.booking_link(request.build_absolute_uri("/")))
        pripominky = udrzba.reminders if udrzba is not None else None
    na_rade = retest.due_plans(request.user)
    na_rade_names = names_for([p.subject for p in na_rade[:8]], request.user)
    for p in na_rade[:8]:
        p.jmeno = na_rade_names.get(p.subject.pk) or p.subject.code

    nastaveni_ceka = 0
    if _is_admin(request.user):
        from apps.core.workplace import pending_count

        nastaveni_ceka = pending_count(request.user)
    context = {
        "dnes": daily_steps(request.user),
        "may_act": request.user.is_superuser or request.user.role not in READ_ONLY,
        "nastaveni_ceka": nastaveni_ceka,
        "objednavky": objednavky,
        "tiles": [
            ("Aktivní sportovci", Subject.objects.for_user(request.user)
             .filter(is_active=True).count(), "users"),
            ("Testovací dny za 30 dní", sessions.filter(
                date__gte=today - timedelta(days=30)).count(), "calendar"),
            ("Zprávy v konceptu", drafts.count(), "file"),
            ("Importy ke kontrole", ImportBatch.objects.for_user(request.user)
             .filter(status=ImportBatch.Status.PARSED).count(), "upload"),
        ],
        "pocet_mereni": Measurement.objects.filter(
            trial__protocol_run__session__in=sessions).count(),
        "posledni_session": recent,
        "koncepty": draft_list,
        "dnes_datum": today,
        "na_rade": na_rade[:8], "na_rade_celkem": len(na_rade), "pripominky_dnes": pripominky,
        "email_enabled": bool(settings.EMAIL_HOST),
    }
    return render(request, "core/dashboard.html", context)


@login_required
def about(request):
    """O aplikaci: co umí, role a návody k ovládání."""
    from django.conf import settings

    from apps.core.models import Role
    from apps.reports import llm

    return render(request, "core/about.html", {
        "roles": Role,
        "llm_enabled": llm.is_enabled(),
        "llm_model": getattr(settings, "LLM_MODEL", ""),
        "llm_info": llm.describe(),
    })


def health(request):
    """
    Kontrola běhu pro hosting. Nekontroluje jen to, že aplikace odpovídá,
    ale i že se dostane k databázi – bez ní je nastartovaná k ničemu.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"stav": "ok", "databaze": "ok"})
    except Exception as exc:
        return JsonResponse(
            {"stav": "chyba", "databaze": f"{type(exc).__name__}"}, status=503,
        )


# --- kolegové --------------------------------------------------------------------

def _is_admin(user) -> bool:
    from apps.core.models import Role

    return user.is_superuser or user.role == Role.ADMIN


@login_required
def colleagues(request):
    """
    Účty kolegů: správce založí účet s rolí a dostane jednorázový odkaz,
    kterým si kolega nastaví heslo. Stejný odkaz slouží jako „zapomenuté
    heslo“; vypnutý účet se nepřihlásí, data zůstanou.
    """
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    from apps.core import colleagues as service
    from apps.core.audit import record
    from apps.core.forms import ColleagueForm
    from apps.core.models import AuditLog, Role, User, default_organization
    from apps.core.roles import COLLEAGUE_ROLES

    if not _is_admin(request.user):
        return render(request, "core/odepreno.html", {"duvod": "Účty kolegů spravuje správce."},
                      status=403)
    org = request.user.organization or default_organization()
    people = User.objects.filter(organization=org, role__in=COLLEAGUE_ROLES)
    form = ColleagueForm(request.POST if request.POST.get("akce") == "novy" else None)
    if request.method == "POST":
        action = request.POST.get("akce")
        if action == "novy":
            if form.is_valid():
                try:
                    new = service.create_colleague(org, **form.cleaned_data)
                except service.ColleagueError as exc:
                    form.add_error(None, str(exc))
                else:
                    record(request, AuditLog.Action.CREATE, new, kolega=new.get_username(),
                           role=new.role)
                    request.session["odkaz_pro"] = new.pk
                    messages.success(request, f"Účet {new.get_username()} je založený. Předejte "
                                              "kolegovi odkaz níže.")
                    return redirect("colleagues")
        else:
            target = get_object_or_404(people, pk=request.POST.get("ucet"))
            if target.pk == request.user.pk:
                messages.error(request, "Vlastní účet si nevypnete ani neresetujete tady.")
            elif action == "odkaz":
                request.session["odkaz_pro"] = target.pk
                record(request, AuditLog.Action.UPDATE, target, kolega=target.get_username(),
                       akce="odkaz na heslo")
            elif action in ("vypnout", "zapnout"):
                target.is_active = action == "zapnout"
                target.save(update_fields=["is_active"])
                record(request, AuditLog.Action.UPDATE, target, kolega=target.get_username(),
                       akce=action)
                messages.info(request, f"Účet {target.get_username()} je "
                                       f"{'zapnutý' if target.is_active else 'vypnutý'}.")
            else:
                messages.error(request, "Neznámá akce.")
            return redirect("colleagues")
    link = link_for = None
    if pk := request.session.pop("odkaz_pro", None):
        link_for = people.filter(pk=pk, is_active=True).first()
        if link_for is not None:
            link = request.build_absolute_uri(
                reverse("password_setup", args=[service.password_link_token(link_for)]))
    from apps.core import access

    rows = list(people.select_related("access")
                .order_by("-is_active", "last_name", "first_name", "username"))
    for person in rows:
        person.pristup = access.summary(person) if person.role != Role.COACH else "portál trenéra"
        person.pristup_potvrzen = (person.role in (Role.ADMIN, Role.COACH) or person.is_superuser
                                   or getattr(getattr(person, "access", None), "configured", False))
    return render(request, "core/colleagues.html", {
        "people": rows, "form": form, "link": link, "link_for": link_for,
        "link_days": service.LINK_DAYS, "link_new": link_for is not None and not link_for.pristup_potvrzen
        if link_for is not None and hasattr(link_for, "pristup_potvrzen") else False,
    })


@login_required
def colleague_access(request, pk):
    """
    Přístup účtu kolegy (správce): role jako šablona, rozsah dat (sporty,
    týmy, metodiky) a oprávnění po položkách. Uložení přístup potvrdí.
    """
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    from apps.catalog.models import TestFamily
    from apps.core import access
    from apps.core.audit import record
    from apps.core.models import AuditLog, Role, User, default_organization
    from apps.core.roles import COLLEAGUE_ROLES, STAFF_ROLES, sync_groups
    from apps.subjects.models import Sport, Team

    if not _is_admin(request.user):
        return render(request, "core/odepreno.html", {"duvod": "Přístupy nastavuje správce."},
                      status=403)
    org = request.user.organization or default_organization()
    target = get_object_or_404(User.objects.filter(organization=org, role__in=COLLEAGUE_ROLES),
                               pk=pk)
    if target.role == Role.COACH:
        messages.info(request, "Trenér má vlastní portál; na koho vidí, určuje sdílení potvrzené "
                               "sportovcem.")
        return redirect("colleagues")
    profile = access.profile(target)
    sports = list(Sport.objects.filter(organization=org).order_by("name"))
    teams = list(Team.objects.filter(organization=org).select_related("sport")
                 .order_by("sport__name", "name"))
    lab_roles = [(r, Role(r).label) for r in (Role.ADMIN, Role.LAB, Role.METHODOLOGIST,
                                              Role.RESEARCHER)]
    is_self = target.pk == request.user.pk

    if request.method == "POST":
        post = request.POST
        changes = {}
        role = post.get("role", target.role)
        if role != target.role and role in dict(lab_roles):
            if is_self:
                messages.error(request, "Vlastní roli si tady nezměníte – požádejte jiného správce.")
                return redirect("colleague_access", pk=pk)
            changes["role"] = f"{target.role} → {role}"
            target.role = role
            target.is_staff = role in STAFF_ROLES
            target.save(update_fields=["role", "is_staff"])
            sync_groups(target)
            access.apply_preset(profile, role)
        if post.get("akce") == "podle_role":
            access.apply_preset(profile, target.role)
            profile.updated_by = request.user
            profile.save()
            access.forget(target)
            record(request, AuditLog.Action.UPDATE, target, kolega=target.get_username(),
                   nastaveni="pristup", akce="podle role", **changes)
            messages.info(request, f"Oprávnění účtu {target.get_username()} jsou podle šablony role "
                                   f"{target.get_role_display()}. Rozsah sportů zůstal.")
            return redirect("colleague_access", pk=pk)

        before = {key: getattr(profile, key) for key in access.FLAGS}
        before.update(all_sports=profile.all_sports, all_families=profile.all_families)
        profile.all_sports = post.get("rozsah", "vse") == "vse"
        chosen_sports = [s for s in sports if str(s.pk) in post.getlist("sporty")]
        sport_ids = {s.pk for s in chosen_sports}
        chosen_teams = [t for t in teams if str(t.pk) in post.getlist("tymy")
                        and (profile.all_sports or t.sport_id in sport_ids)]
        profile.all_families = post.get("metodiky", "vse") == "vse"
        wanted = set(post.getlist("rodiny"))
        profile.families = [code for code, _ in TestFamily.choices if code in wanted]
        for key in access.FLAGS:
            setattr(profile, key, bool(post.get(key)))
        profile.configured = True
        profile.updated_by = request.user
        profile.save()
        profile.sports.set(chosen_sports)
        profile.teams.set(chosen_teams)
        access.forget(target)
        after = {key: getattr(profile, key) for key in access.FLAGS}
        after.update(all_sports=profile.all_sports, all_families=profile.all_families)
        changes.update({key: after[key] for key in after if after[key] != before.get(key)})
        record(request, AuditLog.Action.UPDATE, target, kolega=target.get_username(),
               nastaveni="pristup", sporty=[s.name for s in chosen_sports],
               tymy=[t.name for t in chosen_teams], **changes)
        if not profile.all_sports and not chosen_sports and target.role != Role.ADMIN:
            messages.warning(request, "Účet nemá žádný sport – kolega neuvidí žádného sportovce. "
                                      "Vyberte sporty, nebo všechny sporty.")
        messages.success(request, f"Přístup účtu {target.get_username()} je uložený.")
        return redirect("colleagues")

    chosen_sports = set(profile.sports.values_list("pk", flat=True))
    chosen_teams = set(profile.teams.values_list("pk", flat=True))
    groups = [(title, [(key, label, help_text, getattr(profile, key))
                       for key, label, help_text in items]) for title, items in access.GROUPS]
    return render(request, "core/colleague_access.html", {
        "target": target, "profile": profile, "sports": sports, "teams": teams,
        "chosen_sports": chosen_sports, "chosen_teams": chosen_teams,
        "families": TestFamily.choices, "chosen_families": set(profile.families or []),
        "groups": groups, "roles": lab_roles, "is_self": is_self,
        "is_admin_target": target.role == Role.ADMIN or target.is_superuser,
        "summary": access.summary(target), "preset": access.preset(target.role),
    })


def password_setup(request, token):
    """Nastavení hesla z jednorázového odkazu od správce (účty kolegů)."""
    from django.contrib import messages
    from django.contrib.auth import login, logout
    from django.shortcuts import redirect

    from apps.core import colleagues as service
    from apps.core.audit import record
    from apps.core.forms import PasswordSetForm
    from apps.core.models import AuditLog

    account = service.user_from_password_link(token)
    if account is None:
        return render(request, "registration/nastavit_heslo.html", {"invalid": True}, status=410)
    if request.user.is_authenticated and request.user.pk != account.pk:
        logout(request)
    form = PasswordSetForm(account, request.POST or None)
    if request.method == "POST" and form.is_valid():
        service.set_password(account, form.cleaned_data["password1"])
        login(request, account, backend="django.contrib.auth.backends.ModelBackend")
        record(request, AuditLog.Action.UPDATE, account, kolega=account.get_username(),
               akce="heslo nastaveno odkazem")
        messages.success(request, "Heslo je nastavené. Vítejte.")
        return redirect("dashboard")
    return render(request, "registration/nastavit_heslo.html", {"form": form, "account": account})


# --- stav pracoviště a připomínky ------------------------------------------------

@login_required
def workplace(request):
    """Nastavení: kroky všech částí na jednom místě a kategorie nastavení; tlačítka podle role."""
    from apps.core.middleware import READ_ONLY
    from apps.core.workplace import settings_sections, workplace_steps

    user = request.user
    return render(request, "core/workplace.html", {
        "steps": workplace_steps(user), "sections": settings_sections(user),
        "may_act": user.is_superuser or user.role not in READ_ONLY,
        "is_admin": _is_admin(user),
    })


@login_required
def organization_settings(request):
    """Pracoviště: název a týmy (název, sport). Zkratka se nemění – podle ní se párují přenosy."""
    from django.contrib import messages
    from django.db import transaction
    from django.db.models import Count
    from django.shortcuts import redirect

    from apps.subjects.models import Sport, Team

    from .audit import record
    from .models import AuditLog

    user = request.user
    if not _is_admin(user):
        return render(request, "core/odepreno.html", {"duvod": "Pracoviště a týmy nastavuje správce."},
                      status=403)
    org = user.organization
    if org is None:
        messages.error(request, "Účet nemá pracoviště – přiřadí ho superuživatel v administraci.")
        return redirect("workplace")
    sports = list(Sport.objects.for_user(user).order_by("name"))
    teams = list(Team.objects.filter(organization=org).select_related("sport")
                 .annotate(sportovcu=Count("subjects")).order_by("name"))
    if request.method == "POST":
        post = request.POST
        problems = []
        with transaction.atomic():
            name = post.get("nazev", "").strip()[:200]
            if name and name != org.name:
                org.name = name
                org.save(update_fields=["name", "updated_at"])
            auto_draft = bool(post.get("auto_draft"))
            if auto_draft != org.auto_draft:
                org.auto_draft = auto_draft
                org.save(update_fields=["auto_draft", "updated_at"])
            sport_by_pk = {str(s.pk): s for s in sports}
            for team in teams:
                if f"t{team.pk}_delete" in post:
                    team.delete()  # sportovci zůstanou, jen bez týmu
                    continue
                team_name = post.get(f"t{team.pk}_name", team.name).strip()[:120]
                sport = sport_by_pk.get(post.get(f"t{team.pk}_sport", ""))
                if not team_name or sport is None:
                    problems.append(f"Tým „{team.name}“: název i sport jsou povinné – neuloženo.")
                    continue
                team.name, team.sport = team_name, sport
                team.save()
            new_name = post.get("nt_name", "").strip()[:120]
            new_sport = sport_by_pk.get(post.get("nt_sport", ""))
            if new_name or new_sport is not None:
                if not new_name or new_sport is None:
                    problems.append("Nový tým: napište název a vyberte sport.")
                else:
                    Team.objects.create(organization=org, name=new_name, sport=new_sport)
        record(request, AuditLog.Action.UPDATE, org, nastaveni="pracoviste")
        for problem in problems:
            messages.warning(request, problem)
        messages.success(request, "Pracoviště a týmy jsou uložené.")
        return redirect("workplace_org")
    return render(request, "core/organization.html", {"org": org, "sports": sports, "teams": teams})


@login_required
def operations(request):
    """Provoz a zálohy: stav údržby, záloh a disku; správce může zálohovat nebo poslat stav hned."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from apps.core import backup, maintenance
    from apps.core.audit import record
    from apps.core.models import AuditLog
    from apps.subjects import retest

    user = request.user
    org = user.organization
    if org is None:
        messages.error(request, "Účet nemá pracoviště – přiřadí ho superuživatel v administraci.")
        return redirect("workplace")
    if request.method == "POST":
        if not _is_admin(user):
            return render(request, "core/odepreno.html", {"duvod": "Provoz a zálohy řídí správce."},
                          status=403)
        action = request.POST.get("akce", "")
        if action == "zaloha":
            try:
                result = backup.backup_sqlite(root=maintenance.daily_backup_dir(),
                                              keep=settings.BACKUP_KEEP_DAILY, label="rucni")
            except backup.BackupError as exc:
                messages.error(request, f"Záloha se nepovedla: {exc}")
            else:
                org.backup_at = timezone.now()
                org.backup_note = result.text
                org.save(update_fields=["backup_at", "backup_note", "updated_at"])
                messages.success(request, f"Záloha hotová: {result.text}. Složku uložte i mimo "
                                          "tento počítač.")
        elif action == "udrzba":
            out = maintenance.daily(org, force=True,
                                    booking_url=retest.booking_link(request.build_absolute_uri("/")))
            z = (out.log.get("zaloha") or {}) if out else {}
            messages.success(request, "Denní údržba proběhla: záloha "
                             + ("ok" if z.get("ok") else f"neproběhla ({z.get('chyba', '')})")
                             + f", starých importů smazáno {out.log.get('importy_smazano') or 0}.")
        elif action == "stav":
            sent = maintenance.send_status(org, force=True, base_url=request.build_absolute_uri("/"))
            if sent:
                messages.success(request, f"Stav pracoviště odešel správci ({sent} adres).")
            else:
                messages.warning(request, "Stav neodešel: poštovní server není nastavený, nebo "
                                          "žádný správce nemá e-mail.")
        record(request, AuditLog.Action.UPDATE, org, nastaveni="provoz", akce=action)
        return redirect("operations")
    info = maintenance.status(org)
    subject, body = maintenance.status_message(org, info, base_url=request.build_absolute_uri("/"))
    return render(request, "core/operations.html", {
        "org": org, "info": info, "mail_subject": subject, "mail_body": body,
        "is_admin": _is_admin(user), "keep": settings.BACKUP_KEEP_DAILY,
        "in_web": settings.MAINTENANCE_IN_WEB,
    })


@login_required
def remark_new(request):
    """Připomínka k postupu – vzniká tam, kde ji kolega napadne."""
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.utils.http import url_has_allowed_host_and_scheme

    from apps.core.models import Remark

    source = request.POST if request.method == "POST" else request.GET
    page = (source.get("stranka") or "").strip()[:300]
    if not url_has_allowed_host_and_scheme(page, allowed_hosts={request.get_host()}) \
            or not page.startswith("/"):
        page = ""
    context_text = (source.get("oddil") or "").strip()
    if krok := (source.get("krok") or "").strip():
        context_text = f"{context_text} · {krok}" if context_text else krok
    context_text = context_text[:200]
    if request.method == "POST":
        text = (request.POST.get("text") or "").strip()
        if not text:
            messages.error(request, "Napište, co vám nesedí – prázdná připomínka se neuloží.")
        else:
            Remark.objects.create(organization=request.user.organization, user=request.user,
                                  page=page, context=context_text, text=text[:4000])
            messages.success(request, "Díky, připomínka je uložená. Správce ji uvidí "
                                      "v Připomínkách.")
            return redirect(page or "dashboard")
    return render(request, "core/remark_form.html", {"page": page, "context_text": context_text})


@login_required
def remarks(request):
    """Seznam připomínek pro správce: vyřídit s odpovědí, nebo znovu otevřít."""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    from apps.core.audit import record
    from apps.core.models import AuditLog, Remark, default_organization

    if not _is_admin(request.user):
        return render(request, "core/odepreno.html", {"duvod": "Připomínky vyřizuje správce."},
                      status=403)
    org = request.user.organization or default_organization()
    rows = Remark.objects.filter(organization=org).select_related("user", "resolved_by")
    if request.method == "POST":
        remark = get_object_or_404(rows, pk=request.POST.get("pripominka"))
        action = request.POST.get("akce")
        remark.answer = (request.POST.get("odpoved") or "").strip()[:4000]
        if action == "vyridit":
            remark.status = Remark.Status.DONE
            remark.resolved_by, remark.resolved_at = request.user, timezone.now()
            messages.success(request, "Připomínka je vyřízená.")
        elif action == "otevrit":
            remark.status = Remark.Status.OPEN
            remark.resolved_by = remark.resolved_at = None
        remark.save()
        record(request, AuditLog.Action.UPDATE, remark, pripominka=remark.pk, akce=action)
        return redirect(f"{reverse('remarks')}?stav={request.POST.get('stav', 'open')}")
    show = request.GET.get("stav", "open")
    if show in ("open", "done"):
        rows = rows.filter(status=show)
    return render(request, "core/remarks.html", {
        "rows": rows.order_by("-created_at"), "show": show,
        "open_count": Remark.objects.filter(organization=org, status=Remark.Status.OPEN).count(),
    })
