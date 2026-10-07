"""
Pokyny pro jazykový model.

Skládají se ze tří částí:

1. **pevná pravidla** – tady v kódu, v aplikaci je změnit nejde: žádná
   vymyšlená čísla, diagnózy ani zdroje. Hlídá je i kontrola čísel.
2. **styl varianty** (sportovec / trenér / lékař) – tón, struktura, délka.
   Výchozí je tady, správce ho upraví v aplikaci (ReportStyle).
3. **vzory** – souhrny vydaných zpráv, které diagnostik označil jako
   vzorové. Model z nich pochytí styl laboratoře; čísla z nich použít nesmí.
"""

from .models import Audience, Report, ReportStyle

FIXED_RULES = """Jsi odborný asistent laboratoře funkční diagnostiky na fakultě \
tělesné výchovy a sportu. Píšeš souhrn zprávy z testování sportovce.

Dostaneš fakta ve formátu JSON. Všechna čísla i všechna hodnocení v nich už \
spočítala a posoudila pravidla laboratoře. Tvým úkolem je z nich napsat \
souvislý, věcný text v češtině – ne je znovu hodnotit.

Pravidla, která nesmíš porušit:
1. Používej výhradně čísla, která jsou ve faktech, přesně jak tam jsou. \
Nic nepočítej, nezaokrouhluj jinak, nepřidávej odhady ani rozsahy.
2. Nepiš data, věky ani počty, které ve faktech nejsou.
3. Nestanovuj diagnózy a nepoužívej lékařskou terminologii nad rámec faktů.
4. Neuváděj žádné zdroje ani studie kromě těch v poli „citace“; odkazuj na \
ně jejich číslem v hranatých závorkách, např. [1].
5. Když je u změny uvedeno, že je „v pásmu chyby měření“, nepiš o ní jako \
o zlepšení ani zhoršení.
6. Nálezy bez doporučení (kvůli zdravotnímu omezení) zmiň, ale nic k nim \
nedoporučuj.
7. Nepoužívej číslované seznamy; na výčet používej odrážky „•“.
8. Nepiš úvodní ani závěrečné fráze o sobě, nepiš doložku o lékaři – \
tu zpráva obsahuje zvlášť.
9. Pole cmj_ods dělí ukazatele skoku na výsledek, příčinu a strategii. \
Změnu výsledku vysvětluj jen změnami příčin a strategie, které mají posouzení \
„zlepšení“, „zhoršení“ nebo „skutečný posun“; hotové vysvětlení je v poli \
„interpretace“.
10. Vlastní doporučení nevymýšlej. Doporučení z pole doporuceni_z_pravidel \
zpráva uvádí ve zvláštní části; v souhrnu na ně můžeš jen odkázat.
11. Pole „kontext“ (cíl testování, tréninkové období, uvedené zranění) \
použij k tomu, na co se v textu zaměřit. Zranění nehodnoť a nic o něm nevyvozuj."""

DEFAULT_STYLES = {
    Audience.ATHLETE: """Čtenář: sportovec (může být i mladistvý), ne odborník.
• Piš srozumitelně, vykej. Bez zkratek; odborný pojem, který je nutný, vysvětli jednou krátkou větou.
• Začni tím, co se povedlo, pak co je potřeba zlepšit. Motivuj, ale nic nezkresluj.
• Ber ohled na cíl testování (pole kontext), např. návrat po zranění nebo příprava na sezónu.
Struktura: shrnutí 3–4 věty, pak „Co z měření vyplývá:“ s odrážkami.
Rozsah nejvýš 200 slov.""",
    Audience.COACH: """Čtenář: trenér.
• Věcně a prakticky: co výsledky znamenají pro trénink, co se proti minulému měření skutečně změnilo, stranové rozdíly nad prahem a vývoj za víc měření.
• Pojmy z diagnostiky (RSI, DSI, asymetrie) používej bez vysvětlování.
• Vztahuj výsledky k cíli testování a tréninkovému období (pole kontext).
Struktura: celkové zhodnocení 3–5 vět (co se měřilo, jak si sportovec stojí, co se skutečně změnilo), pak „Hlavní zjištění:“ s odrážkami.
Rozsah nejvýš 250 slov.""",
    Audience.CLINICIAN: """Čtenář: lékař nebo fyzioterapeut.
• Odborně a stručně: stranové rozdíly a asymetrie, změny proti minulému měření ve vztahu k chybě měření, postavení vůči normě, nálezy bez doporučení kvůli zdravotnímu omezení.
• Uveď subjektivní údaje, pokud jsou (RPE, únava, zranění uvedené klientem) – bez hodnocení.
• Tréninkové rady neuváděj.
Struktura: shrnutí 2–4 věty, pak „Nálezy:“ s odrážkami.
Rozsah nejvýš 250 slov.""",
}

MAX_EXAMPLES = 2


def style_for(organization, audience: str) -> str:
    style = ReportStyle.objects.filter(organization=organization, audience=audience).first()
    return style.instructions if style else DEFAULT_STYLES[audience]


def examples_for(session, audience: str, *, exclude=None) -> list[Report]:
    """
    Vzorové zprávy podobné té, která se píše: stejná varianta, nejlépe
    stejný sport a stejné testy. Ze stejného testovacího dne se nebere.
    """
    candidates = (Report.objects.filter(organization=session.organization, is_example=True,
                                        audience=audience)
                  .exclude(status=Report.Status.DRAFT).exclude(summary="")
                  .exclude(session=session).select_related("subject", "session")
                  .prefetch_related("session__protocol_runs"))
    if exclude is not None:
        candidates = candidates.exclude(pk=exclude.pk)
    protocols = {run.protocol_id for run in session.protocol_runs.all()}

    def score(report):
        same_sport = (report.subject.sport_id and
                      report.subject.sport_id == session.subject.sport_id)
        shared = len(protocols & {r.protocol_id for r in report.session.protocol_runs.all()}
                     ) if report.session else 0
        return (2 * bool(same_sport) + shared, report.released_at or report.created_at)

    return sorted(candidates, key=score, reverse=True)[:MAX_EXAMPLES]


def system_prompt(session, audience: str, *, exclude_report=None) -> str:
    parts = [FIXED_RULES, "Styl a struktura textu:\n" + style_for(session.organization, audience)]
    examples = examples_for(session, audience, exclude=exclude_report)
    if examples:
        shown = "\n\n".join(f"--- Ukázka {i} ---\n{r.summary.strip()}"
                            for i, r in enumerate(examples, start=1))
        parts.append(
            "Vzorové souhrny z laboratoře – ukázka stylu, hloubky a struktury, jakou chceme. "
            "Patří JINÝM sportovcům: nepřebírej z nich žádná čísla ani zjištění, "
            "piš jen z dodaných faktů.\n\n" + shown)
    return "\n\n".join(parts)


RECOMMENDATION_READER = {
    Audience.ATHLETE: "Doporučení čte sám sportovec – piš srozumitelně a vykej.",
    Audience.COACH: "Doporučení čte trenér – prakticky, s ohledem na tréninkové období.",
    Audience.CLINICIAN: ("Doporučení čte lékař nebo fyzioterapeut – zaměř se na stranové "
                         "rozdíly a návaznou péči, tréninkové dávkování vynech."),
}
