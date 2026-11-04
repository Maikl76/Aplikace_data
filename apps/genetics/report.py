"""
Genetická zpráva: deterministické sestavení ze schválených karet.

Pořadí podle podkladů: cíl klienta a dostupné podklady → přehled genotypů →
výsledky podle oblastí → praktická doporučení a jejich důvody → co doplnit
nebo změřit → omezení interpretace a zdroje.

Co tu platí bez výjimky: text pro genotyp je doslova ze schválené verze
karty; doporučení nese důvod; při rozporu se nic nevybírá – jde to
k odbornému posouzení; žádné genetické skóre; naměřená výkonnost se uvádí
vedle genotypu, nikdy jako jeho potvrzení. Jazykový model smí napsat jen
spojovací souhrn a ten se kontroluje proti nepřípustným výrokům i číslům.
"""

import json
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.measurements import questionnaires
from apps.reports.models import Audience, Report

from . import crypto
from . import services as genetics
from .models import ContextScenario, ForbiddenStatement, Genotype, Recommendation
from .seed import QUESTIONNAIRE_CODE

logger = logging.getLogger(__name__)

TITLE = "Zpráva z genetického vyšetření"
SERIES = "FTG"
AUDIENCES = (Audience.ATHLETE, Audience.CLINICIAN)
DISCLAIMER = (
    "Výsledek genetického vyšetření je dílčí biologická informace. Neurčuje aktuální "
    "výkonnost, vhodný sport, účinek doplňků stravy ani riziko poranění a nenahrazuje měření "
    "ani posouzení zdravotního stavu lékařem. Každé doporučení platí jen v uvedeném kontextu "
    "a s uvedeným důvodem."
)
LIMITATIONS = [
    "Zpráva popisuje jednotlivé varianty zvlášť; genetické skóre neexistuje a varianty se "
    "nesčítají.",
    "Odpovědi v dotazníku jsou zkušenost klienta; genetický účinek nepotvrzují ani nevyvracejí.",
    "Naměřená výkonnost není potvrzením genetické příčiny; měření a genotyp se uvádějí vedle sebe.",
    "Populační asociace z literatury neříkají, jak se varianta projeví u konkrétního člověka.",
]
MEASUREMENT_MONTHS = 12
KIND_ORDER = [k for k, _ in Recommendation.Kind.choices]
MAX_WORDS = 160


class GeneticsReportError(Exception):
    """Zprávu nejde sestavit nebo vydat – uživatel se musí dozvědět proč."""


# --- sestavení obsahu -------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join((text or "").replace("„", "").replace("“", "").replace('"', "")
                    .lower().split()).rstrip(".")


def _value(number, metric) -> str:
    text = f"{number:.{metric.decimals}f}".replace(".", ",")
    unit = metric.unit if metric.unit and metric.unit != "-" else ""
    return f"{text} {unit}".strip()


def _availability(subject, protocol) -> dict | None:
    """Má sportovec z posledního roku výsledek testu? Jen hodnoty, bez výkladu."""
    from apps.analytics import queries
    from apps.measurements.models import ProtocolRun

    since = timezone.localdate() - timedelta(days=30 * MEASUREMENT_MONTHS)
    run = (ProtocolRun.objects.filter(session__subject=subject, protocol=protocol,
                                      is_primary=True, session__date__gte=since)
           .select_related("session").order_by("-session__date", "-pk").first())
    if run is None:
        return None
    primary = set(protocol.protocol_metrics.filter(is_primary=True)
                  .values_list("metric__code", flat=True))
    rows = [f"{entry['metric'].name} {_value(entry['value'], entry['metric'])}"
            for key, entry in queries.session_metric_values(run.session).items()
            if entry["protocol"] == protocol.code and key[0] in primary]
    return {"date": run.session.date.isoformat(),
            "date_txt": run.session.date.strftime("%d.%m.%Y"), "values": rows}


def _goal(answers: dict) -> dict:
    out = {}
    for code, label in (("hlavni_sport", "sport"), ("zamereni", "zamereni"), ("cil", "cil"),
                        ("cil_upresneni", "upresneni")):
        answer = answers.get(code)
        if answer is not None and answer.is_answered and answer.display():
            out[label] = answer.display()
    return out


def _questionnaire(response) -> dict | None:
    if response is None:
        return None
    sections = []
    for section in questionnaires.sections(response.questionnaire, response):
        rows = [{"otazka": item["question"].text, "odpoved": item["answer"].display()}
                for item in section["questions"]
                if item["answer"] is not None and item["answer"].state != "missing"]
        if rows:
            sections.append({"oddil": section["name"], "odpovedi": rows})
    return {"nazev": response.questionnaire.name, "vyplneno": response.created_at.isoformat(),
            "vyplneno_txt": response.created_at.strftime("%d.%m.%Y"),
            "zdroj": response.get_source_display(), "oddily": sections}


def _context_for(card, genotype: str, answers: dict) -> list[dict]:
    """Aktivní scénáře z dotazníku, které spouští odpověď sportovce."""
    out = []
    scenarios = (card.scenarios.filter(is_active=True, kind=ContextScenario.Kind.QUESTIONNAIRE,
                                       question__isnull=False)
                 .select_related("question").prefetch_related("texts"))
    for scenario in scenarios:
        answer = answers.get(scenario.question.code)
        if not scenario.matches(answer):
            continue
        text = next((t.text for t in scenario.texts.all() if t.genotype == genotype), "")
        if text:
            out.append({"otazka": scenario.question.text, "odpoved": answer.display(),
                        "text": text})
    return out


def _recommendation(rec, variant, genotype_label) -> dict:
    return {"druh": rec.get_kind_display(), "druh_kod": rec.kind, "text": rec.text,
            "duvod": rec.get_basis_display(), "duvod_kod": rec.basis,
            "klic": rec.merge_key, "varianta": variant.label, "genotyp": genotype_label,
            "test": rec.protocol.name if rec.protocol_id else "",
            "test_kod": rec.protocol.code if rec.protocol_id else ""}


def _merge(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Sloučení doporučení napříč kartami podle klíče: stejný text = jedno
    doporučení s více důvody; různé texty pod jedním klíčem = rozpor
    k odbornému posouzení. Bez klíče se slučuje jen doslova stejný text.
    """
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = row["klic"] or f"text:{_norm(row['text'])}"
        groups.setdefault(key, []).append(row)
    merged, conflicts = [], []
    for key, items in groups.items():
        texts = {_norm(i["text"]) for i in items}
        if len(texts) == 1:
            first = items[0]
            merged.append({
                "druh": first["druh"], "druh_kod": first["druh_kod"], "text": first["text"],
                "duvody": sorted({f"{i['duvod']} ({i['varianta']} {i['genotyp']})"
                                  for i in items}),
                "varianty": sorted({i["varianta"] for i in items}),
                "slouceno": len(items),
            })
        else:
            conflicts.append({
                "klic": key, "varianty": sorted({i["varianta"] for i in items}),
                "moznosti": [{"varianta": i["varianta"], "genotyp": i["genotyp"],
                              "text": i["text"], "duvod": i["duvod"]} for i in items],
            })
    merged.sort(key=lambda r: (KIND_ORDER.index(r["druh_kod"]), r["text"]))
    return merged, conflicts


def _to_measure(rows: list[dict], subject) -> list[dict]:
    """Co by bylo vhodné změřit – a zda už výsledek v aplikaci je (bez výkladu)."""
    out, seen = [], set()
    for row in rows:
        key = (row["test_kod"], _norm(row["text"]))
        if key in seen:
            continue
        seen.add(key)
        available = None
        if row["test_kod"]:
            from apps.catalog.models import Protocol

            protocol = Protocol.objects.filter(code=row["test_kod"]).order_by("-version").first()
            available = _availability(subject, protocol) if protocol else None
        out.append({"text": row["text"], "test": row["test"], "duvod": row["duvod"],
                    "varianty": [row["varianta"]], "k_dispozici": available})
    return out


def compose(sample, response=None, *, audience=Audience.ATHLETE) -> dict:
    """Obsah zprávy – jediný zdroj pro náhled, PDF, snímek i fakta pro model."""
    if not crypto.configured():
        raise GeneticsReportError(crypto.CHYBI)
    subject = sample.subject
    panel = sample.panel
    clinician = audience == Audience.CLINICIAN
    answers = response.answers_by_code() if response is not None else {}
    genotypes = {g.variant_id: g for g in sample.genotypes.all()}

    by_domain: dict = {}
    overview, not_interpreted, rec_rows, measure_rows, sources, forbidden_hits = [], [], [], [], [], []
    versions: dict[str, int] = {}
    for item in panel.active_items():
        variant = item.variant
        genotype = genotypes.get(variant.pk)
        card = variant.current_card()
        value = genotype.value if genotype is not None else ""
        row = {"varianta": variant.label, "gen": variant.gene, "rsid": variant.rsid,
               "oblast": variant.domain.name, "genotyp": value,
               "genotyp_txt": variant.genotype_label(value) if value else "—",
               "kvalita": genotype.get_quality_display() if genotype else "výsledek chybí",
               "karta": f"v{card.version}" if card else "—"}
        overview.append(row)
        if genotype is None or genotype.quality != Genotype.Quality.OK or not value:
            not_interpreted.append({**row, "duvod": "výsledek chybí nebo není jednoznačný "
                                                    f"({row['kvalita'].lower()})"})
            continue
        if card is None:
            not_interpreted.append({**row, "duvod": "karta varianty zatím není schválená"})
            continue
        text = card.text_for(value)
        if text is None or not text.client_text.strip():
            not_interpreted.append({**row, "duvod": f"schválená karta nemá text pro genotyp "
                                                    f"{row['genotyp_txt']}"})
            continue
        versions[variant.rsid] = card.version
        shown = (text.expert_text.strip() or text.client_text) if clinician else text.client_text
        biology = (card.biology_expert or card.biology_client) if clinician else card.biology_client
        for hit in genetics.forbidden_in(card, shown):
            forbidden_hits.append(f"{variant.label}: „{hit}“")
        recs = [r for r in card.recommendations.select_related("protocol")
                if not r.genotype or r.genotype == value]
        rec_dicts = [_recommendation(r, variant, row["genotyp_txt"]) for r in recs]
        entry = {
            **row, "text": shown, "biologie": biology,
            "ucinek": card.effect if clinician else "",
            "omezeni": card.limitations, "frekvence": text.frequency,
            "kontext": _context_for(card, value, answers),
            "doporuceni": [r for r in rec_dicts if r["duvod_kod"] != Recommendation.Basis.MEASUREMENT],
            "dukazy": [{"kod": e.code, "znak": e.trait, "podklad": e.basis_text,
                        "pouziti": e.usage, "zdroje": e.source_labels}
                       for e in card.evidence.all()] if clinician else [],
        }
        by_domain.setdefault(variant.domain, []).append(entry)
        for r in rec_dicts:
            (measure_rows if r["duvod_kod"] == Recommendation.Basis.MEASUREMENT
             else rec_rows).append(r)
        for src in card.sources.all():
            sources.append({"citace": src.citation.strip(), "odkaz": src.url,
                            "oznaceni": src.label, "varianta": variant.label})

    areas = [{"kod": domain.code, "nazev": domain.name, "popis": domain.description,
              "polozky": items}
             for domain, items in sorted(by_domain.items(), key=lambda d: (d[0].order, d[0].name))]
    merged, conflicts = _merge(rec_rows)
    numbered, seen = [], {}
    for src in sources:
        key = _norm(src["citace"])
        if key in seen:
            if src["varianta"] not in seen[key]["varianty"]:
                seen[key]["varianty"].append(src["varianta"])
            continue
        seen[key] = {"cislo": len(numbered) + 1, "citace": src["citace"], "odkaz": src["odkaz"],
                     "varianty": [src["varianta"]]}
        numbered.append(seen[key])
    limitations = list(LIMITATIONS) + sorted({
        e["omezeni"].strip() for items in by_domain.values() for e in items if e["omezeni"].strip()})
    versions_text = ",".join(f"{rsid}@v{version}" for rsid, version in sorted(versions.items()))
    return {
        "ctenar": audience,
        "panel": {"nazev": panel.name, "verze": panel.version, "laborator": sample.provider
                  or panel.provider},
        "vzorek": {"id": sample.pk, "odber": sample.sampled_on.isoformat() if sample.sampled_on else None,
                   "odber_txt": sample.sampled_on.strftime("%d.%m.%Y") if sample.sampled_on else "",
                   "vysledek": sample.reported_on.isoformat() if sample.reported_on else None,
                   "vysledek_txt": sample.reported_on.strftime("%d.%m.%Y") if sample.reported_on else "",
                   "reference": sample.external_reference,
                   "overil": sample.verified_by.get_username() if sample.verified_by_id else "",
                   "overeno": sample.verified_at.isoformat() if sample.verified_at else None},
        "cil": _goal(answers),
        "dotaznik": _questionnaire(response),
        "genotypy": overview,
        "oblasti": areas,
        "doporuceni": merged,
        "k_posouzeni": conflicts,
        "co_doplnit": _to_measure(measure_rows, subject),
        "neinterpretovano": not_interpreted,
        "omezeni": limitations,
        "zdroje": numbered,
        "nepripustne_vyroky": forbidden_hits,
        "versions": {"karty": versions, "karty_text": versions_text,
                     "panel": f"{panel.code} v{panel.version}", "vzorek": sample.pk,
                     "dotaznik": response.pk if response is not None else None,
                     "sestaveno": timezone.now().isoformat()},
    }


# --- souhrn ---------------------------------------------------------------------------

def template_summary(content: dict) -> str:
    """Spojovací souhrn bez modelu: co zpráva obsahuje, oblast po oblasti."""
    areas = content["oblasti"]
    total = len(content["genotypy"])
    lines = [f"Zpráva shrnuje výsledek genetického vyšetření {total} "
             f"{_plural(total, 'varianty', 'variant', 'variant')} v panelu "
             f"„{content['panel']['nazev']}“. U každé varianty uvádí, co o jejím genotypu říká "
             "schválená genová karta, a doporučení s uvedeným důvodem. Genotyp je dílčí "
             "informace; měření a Vaše zkušenost mají přednost."]
    for area in areas:
        parts = [f"{e['gen']} {e['genotyp_txt']}" for e in area["polozky"]]
        lines.append(f"• {area['nazev']}: {', '.join(parts)}.")
    if content["neinterpretovano"]:
        lines.append(f"• Bez interpretace: {len(content['neinterpretovano'])} "
                     f"{_plural(len(content['neinterpretovano']), 'varianta', 'varianty', 'variant')} "
                     "(důvod je uveden v části Omezení).")
    if content["co_doplnit"]:
        lines.append("• Zpráva navrhuje doplnit měření – viz část Co doplnit nebo změřit.")
    return "\n".join(lines)


def _plural(count: int, one: str, few: str, many: str) -> str:
    return one if count == 1 else few if 2 <= count <= 4 else many


def facts(content: dict) -> dict:
    """Co dostane model: jen schválené texty a sloučená doporučení, nic k výkladu."""
    return {
        "ctenar": Audience(content["ctenar"]).label.lower(),
        "cil_klienta": content["cil"],
        "oblasti": [{
            "oblast": area["nazev"],
            "varianty": [{"varianta": e["varianta"], "genotyp": e["genotyp_txt"],
                          "text_karty": e["text"],
                          "kontext_z_dotazniku": [c["text"] for c in e["kontext"]],
                          "doporuceni": [r["text"] for r in e["doporuceni"]]}
                         for e in area["polozky"]],
        } for area in content["oblasti"]],
        "doporuceni_sloucena": [r["text"] for r in content["doporuceni"]],
        "k_odbornemu_posouzeni": [c["klic"] for c in content["k_posouzeni"]],
        "co_doplnit": [m["text"] for m in content["co_doplnit"]],
        "neinterpretovano": [f"{n['varianta']}: {n['duvod']}" for n in content["neinterpretovano"]],
        "omezeni": content["omezeni"],
    }


FIXED_RULES = """Jsi odborný asistent laboratoře funkční diagnostiky na fakultě tělesné \
výchovy a sportu. Píšeš krátký spojovací souhrn zprávy z genetického vyšetření.

Dostaneš fakta ve formátu JSON. Všechny interpretace genotypů v nich jsou schválené texty \
genových karet. Tvým úkolem je napsat souvislý úvod ke zprávě – ne genotypy vykládat.

Pravidla, která nesmíš porušit:
1. Nepřidávej žádné tvrzení o genech, genotypech, výkonu, riziku, výživě nebo doplňcích, \
které není ve faktech. Nic neodvozuj z kombinace variant.
2. Nikdy nepiš, že měření, výsledek nebo odpověď genotyp „potvrzuje“ nebo „nepotvrzuje“, \
že klient „využívá“ nebo „nevyužívá“ genetický potenciál, že má určitý typ svalových vláken, \
že je „univerzální typ“, že má nebo nemá genetické riziko, ani nedoporučuj sport.
3. Používej jen čísla, která jsou ve faktech, přesně jak tam jsou; nic nepočítej.
4. Neuváděj zdroje ani studie.
5. Vykej. Nepoužívej číslované seznamy; na výčet používej odrážky „•“.
6. Nepiš úvodní ani závěrečné fráze o sobě; nepiš doložku – tu zpráva obsahuje zvlášť.
Struktura: 2–3 věty, k čemu zpráva je a z čeho vychází (panel, dotazník, cíl klienta), pak \
odrážky po oblastech – u každé jen jedna věta, o čem oblast je, bez výkladu genotypu. \
Rozsah nejvýš 150 slov."""


def _allowed_numbers(content_facts: dict) -> set:
    from apps.reports.narrative import ALWAYS_ALLOWED, _numbers_in

    allowed: set = set(ALWAYS_ALLOWED)
    _numbers_in(content_facts, allowed)
    return allowed


def verify_summary(text: str, content: dict) -> list[str]:
    """Co v souhrnu nesmí být: nepřípustné výroky a čísla bez opory ve faktech."""
    from apps.reports.narrative import NUMBER

    problems = []
    haystack = _norm(text)
    statements = ForbiddenStatement.objects.filter(card__isnull=True) | ForbiddenStatement.objects.filter(
        card__status="approved")
    for statement in statements:
        if _norm(statement.text) and _norm(statement.text) in haystack:
            problems.append(f"nepřípustný výrok „{statement.text}“")
    allowed = _allowed_numbers(facts(content))
    for raw in NUMBER.findall(text):
        number = round(abs(float(raw.replace("−", "-").replace(",", "."))), 4)
        if number not in allowed:
            problems.append(f"číslo {raw}")
    return problems


def compose_summary(report, *, model=None):
    """Souhrn zprávy: modelem, když je zapnutý a text projde kontrolou; jinak šablonou."""
    from apps.reports import llm
    from apps.reports.narrative import Composition

    content = _content(report)
    fallback = template_summary(content)
    data = facts(content)
    if not llm.is_enabled():
        return Composition(text=fallback, source="šablona", facts=data)
    messages = [{"role": "system", "content": FIXED_RULES},
                {"role": "user", "content": "Fakta ze zprávy:\n\n"
                                            + json.dumps(data, ensure_ascii=False, indent=2)}]
    try:
        reply = llm.chat(messages, model=model)
        problems = verify_summary(reply.text, content)
        if problems:
            messages += [{"role": "assistant", "content": reply.text},
                         {"role": "user", "content": "Text porušuje pravidla: "
                                                     + "; ".join(problems)
                                                     + ". Napiš ho znovu bez těchto míst."}]
            reply = llm.chat(messages, model=model)
            problems = verify_summary(reply.text, content)
    except llm.LLMError as exc:
        logger.warning("Model se pro genetickou zprávu %s nepoužil: %s", report.pk, exc)
        return Composition(text=fallback, source="šablona", facts=data,
                           note=f"Jazykový model se nepoužil: {exc}")
    if problems:
        return Composition(text=fallback, source="šablona", facts=data,
                           note=f"Text od modelu {reply.model} byl odmítnut: "
                                f"{'; '.join(problems[:4])}. Použita šablona.")
    words = len(reply.text.split())
    note = f"Souhrn napsal model {reply.model} za {reply.seconds:.0f} s."
    if words > MAX_WORDS:
        note += f" Je delší, než má být ({words} slov) – zkraťte ho."
    return Composition(text=reply.text.strip(), source=reply.model, facts=data, note=note)


# --- zpráva ---------------------------------------------------------------------------

def _content(report) -> dict:
    if report.snapshot and "genetika" in report.snapshot:
        return report.snapshot["genetika"]
    if report.genetic_sample is None:
        raise GeneticsReportError("Zpráva nemá genetický vzorek.")
    return compose(report.genetic_sample, report.questionnaire_response, audience=report.audience)


def context(report) -> dict:
    """Podklad pro náhled, PDF i stránku zprávy; vydaná zpráva jde ze snímku."""
    from apps.reports.services import subject_name

    return {
        "report": report, "session": None, "subject": report.subject,
        "display_name": subject_name(report), "age": report.subject.age,
        "content": _content(report), "generated_at": timezone.now(),
        "findings": [], "suppressed": [], "recommendations": [], "citations": [],
        "population_warnings": [], "results": [], "trends": [], "asymmetries": [],
        "asymmetry_threshold": 0,
    }


def text_problems(report) -> list[str]:
    """Nepřípustné výroky v textu, který napsal nebo upravil člověk."""
    problems = []
    for text in (report.summary, report.custom_note):
        haystack = _norm(text)
        if not haystack:
            continue
        statements = (ForbiddenStatement.objects.filter(card__isnull=True)
                      | ForbiddenStatement.objects.filter(card__status="approved"))
        problems += [s.text for s in statements if _norm(s.text) and _norm(s.text) in haystack]
    return sorted(set(problems))


def check_release(report) -> None:
    """Co musí platit, aby šla genetická zpráva vydat."""
    from apps.reports.services import ReportError

    sample = report.genetic_sample
    if sample is None or not sample.is_usable:
        raise ReportError("Genetickou zprávu lze vydat jen z ověřeného vzorku.")
    if not genetics.consent_state(report.subject).valid:
        raise ReportError("Sportovec nemá platný souhlas s genetickými daty – zpráva se nevydá.")
    if problems := text_problems(report):
        raise ReportError("Text zprávy obsahuje nepřípustný výrok: „"
                          + "“, „".join(problems) + "“. Upravte souhrn nebo komentář.")
    content = _content(report)
    if content["nepripustne_vyroky"]:
        raise ReportError("Schválená karta obsahuje nepřípustný výrok: "
                          + "; ".join(content["nepripustne_vyroky"]))


@transaction.atomic
def build_draft(sample, *, user, audience, supersedes=None, model=None) -> Report:
    """Koncept genetické zprávy z ověřeného vzorku a nejnovějšího dotazníku."""
    from django.conf import settings

    from apps.reports import llm
    from apps.reports import services as report_services

    if audience not in AUDIENCES:
        raise GeneticsReportError("Genetická zpráva je jen pro sportovce nebo pro lékaře; "
                                  "trenér genetiku nedostává.")
    if not sample.is_usable:
        raise GeneticsReportError("Zprávu lze sestavit jen z ověřeného vzorku (ověřte "
                                  "příslušnost výsledku).")
    state = genetics.consent_state(sample.subject)
    if not state.valid:
        raise GeneticsReportError("Sportovec nemá platný souhlas s genetickými daty.")
    if state.blocked_reason:
        raise GeneticsReportError(state.blocked_reason)
    organization = sample.subject.organization
    type(organization).objects.select_for_update().get(pk=organization.pk)
    response = questionnaires.latest(sample.subject, QUESTIONNAIRE_CODE)
    content = compose(sample, response, audience=audience)
    if content["nepripustne_vyroky"]:
        raise GeneticsReportError("Schválená karta obsahuje nepřípustný výrok: "
                                  + "; ".join(content["nepripustne_vyroky"]))
    report = Report(
        organization=organization, subject=sample.subject, session=None,
        kind=Report.Kind.GENETICS, genetic_sample=sample, questionnaire_response=response,
        report_number=report_services.next_report_number(organization, SERIES),
        version=(supersedes.version + 1) if supersedes else 1, supersedes=supersedes,
        audience=audience, show_name=supersedes.show_name if supersedes else False,
        title=TITLE, disclaimer=DISCLAIMER, rules_version=content["versions"]["karty_text"],
        literature=[],
    )
    report.input_fingerprint = report.compute_fingerprint({
        "vzorek": sample.pk, "dotaznik": response.pk if response else None,
        "karty": content["versions"]["karty"], "ctenar": audience,
        "genotypy": [(g["rsid"], g["genotyp"]) for g in content["genotypy"]],
    })
    background = llm.is_enabled() and settings.LLM_BACKGROUND
    if background:
        text = template_summary(content)
        report.summary = report.summary_generated = text
        report.llm_model = "šablona"
        report_services._mark_writing(report, model)
        report.save()
        report_services._start_writing(report, model, rewrite=False)
        return report
    report.save()
    composition = compose_summary(report, model=model)
    report.summary = report.summary_generated = composition.text
    report.llm_model = composition.source
    report.generation_note = composition.note
    report.save(update_fields=["summary", "summary_generated", "llm_model", "generation_note"])
    return report


def machine_readable(report, context: dict) -> dict:
    content = context["content"]
    return {
        "cislo_zpravy": report.report_number,
        "verze": report.version,
        "druh": "geneticke_vysetreni",
        "vydano": report.released_at.isoformat() if report.released_at else None,
        "sportovec": {"kod": report.subject.code, "sport": str(report.subject.sport or "")},
        "panel": content["panel"],
        "genotypy": [{"gen": g["gen"], "rsid": g["rsid"], "genotyp": g["genotyp"],
                      "kvalita": g["kvalita"], "karta": g["karta"]} for g in content["genotypy"]],
        "oblasti": [{"oblast": a["nazev"],
                     "varianty": [{"varianta": e["varianta"], "genotyp": e["genotyp_txt"],
                                   "text": e["text"], "kontext": e["kontext"],
                                   "doporuceni": e["doporuceni"]} for e in a["polozky"]]}
                    for a in content["oblasti"]],
        "doporuceni": content["doporuceni"],
        "k_odbornemu_posouzeni": content["k_posouzeni"],
        "co_doplnit": content["co_doplnit"],
        "neinterpretovano": content["neinterpretovano"],
        "omezeni": content["omezeni"],
        "zdroje": content["zdroje"],
        "verze_karet": content["versions"]["karty"],
        "dolozka": report.disclaimer,
    }
