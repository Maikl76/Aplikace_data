"""
Doplnění článku podle DOI nebo PMID.

Bibliografické údaje a abstrakt se stáhnou z PubMedu (NCBI E-utilities);
článek, který v PubMedu není, se dohledá v Crossrefu podle DOI. Obě služby
jsou veřejné a zdarma, bez registrace. Na počítači bez internetu (offline
server) dohledání nejde – údaje se vyplní ručně nebo přijdou s katalogem.

Odchází jen DOI nebo PMID článku, nic o sportovcích.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CROSSREF = "https://api.crossref.org/works/"
TIMEOUT = 15
USER_AGENT = "FTVS-funkcni-diagnostika/1.0 (knihovna clanku)"

DOI = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
PMID = re.compile(r"^\d{1,9}$")

# Typ publikace v PubMedu → úroveň evidence v knihovně (jen návrh, kurátor ji ověří).
PUBLICATION_TYPES = [
    ("Meta-Analysis", "meta"),
    ("Systematic Review", "meta"),
    ("Randomized Controlled Trial", "rct"),
    ("Case Reports", "case"),
    ("Consensus Development Conference", "expert"),
    ("Practice Guideline", "expert"),
]


class LookupError_(Exception):
    """Článek se nepodařilo dohledat – uživatel se musí dozvědět proč."""


def parse_identifier(text: str) -> tuple[str, str]:
    """
    Z toho, co uživatel vložil, pozná DOI nebo PMID – i z odkazu
    (doi.org/…, pubmed.ncbi.nlm.nih.gov/12345678/).
    """
    text = urllib.parse.unquote((text or "").strip())
    if not text:
        raise LookupError_("Vložte DOI nebo PMID článku.")
    if match := DOI.search(text):
        return "doi", match.group(0).rstrip(".,;)")
    if match := re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", text):
        return "pmid", match.group(1)
    cleaned = re.sub(r"^(pmid:?\s*)", "", text, flags=re.IGNORECASE)
    if PMID.match(cleaned):
        return "pmid", cleaned
    raise LookupError_("Tohle nevypadá jako DOI (10.xxxx/…) ani PMID (jen číslice).")


def lookup(text: str) -> dict:
    """Údaje článku pro formulář: title, authors, journal, year, doi, pmid, abstract, url…"""
    kind, value = parse_identifier(text)
    if kind == "pmid":
        return fetch_pubmed(value)
    pmid = find_pmid_for_doi(value)
    if pmid:
        data = fetch_pubmed(pmid)
        data["doi"] = data.get("doi") or value
        return data
    return fetch_crossref(value)


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError_("Článek se nenašel – zkontrolujte DOI nebo PMID.") from exc
        raise LookupError_(f"Služba odpověděla chybou {exc.code}. Zkuste to později.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LookupError_(
            "Nepodařilo se spojit s PubMedem ani Crossrefem – počítač asi nemá přístup "
            "k internetu. Vyplňte údaje ručně.") from exc


def find_pmid_for_doi(doi: str) -> str:
    query = urllib.parse.urlencode({"db": "pubmed", "term": f"{doi}[doi]", "retmode": "json"})
    try:
        body = json.loads(_get(f"{EUTILS}esearch.fcgi?{query}"))
    except ValueError:
        return ""
    ids = body.get("esearchresult", {}).get("idlist", [])
    return ids[0] if len(ids) == 1 else ""


def fetch_pubmed(pmid: str) -> dict:
    query = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "xml"})
    data = parse_pubmed_xml(_get(f"{EUTILS}efetch.fcgi?{query}"))
    if not data:
        raise LookupError_(f"PMID {pmid} se v PubMedu nenašel.")
    return data


def _text(element) -> str:
    """Text i s vnořeným formátováním (<i>, <sup>) a bez zalomení."""
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def parse_pubmed_xml(raw: bytes) -> dict:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise LookupError_("PubMed vrátil odpověď, které nerozumím.") from exc
    entry = root.find(".//PubmedArticle")
    if entry is None:
        return {}
    article = entry.find("MedlineCitation/Article")
    pmid = _text(entry.find("MedlineCitation/PMID"))

    authors = []
    for author in article.findall("AuthorList/Author"):
        if collective := _text(author.find("CollectiveName")):
            authors.append(collective)
        elif last := _text(author.find("LastName")):
            authors.append(f"{last} {_text(author.find('Initials'))}".strip())

    parts = []
    for block in article.findall("Abstract/AbstractText"):
        label = block.get("Label")
        text = _text(block)
        if text:
            parts.append(f"{label.capitalize()}: {text}" if label else text)

    year = None
    for path in ("Journal/JournalIssue/PubDate/Year", "Journal/JournalIssue/PubDate/MedlineDate",
                 "ArticleDate/Year"):
        if match := re.search(r"\d{4}", _text(article.find(path))):
            year = int(match.group(0))
            break

    doi = ""
    for node in entry.findall("PubmedData/ArticleIdList/ArticleId"):
        if node.get("IdType") == "doi":
            doi = _text(node)
    if not doi:
        for node in article.findall("ELocationID"):
            if node.get("EIdType") == "doi":
                doi = _text(node)

    types = {_text(t) for t in article.findall("PublicationTypeList/PublicationType")}
    level = next((code for name, code in PUBLICATION_TYPES if name in types), "")

    journal = (_text(article.find("Journal/ISOAbbreviation"))
               or _text(article.find("Journal/Title")))
    return {
        "title": _text(article.find("ArticleTitle")).rstrip("."),
        "authors": ", ".join(authors),
        "journal": journal,
        "year": year,
        "doi": doi,
        "pmid": pmid,
        "abstract": "\n\n".join(parts),
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "evidence_level": level,
        "source": "PubMed",
    }


def fetch_crossref(doi: str) -> dict:
    try:
        body = json.loads(_get(CROSSREF + urllib.parse.quote(doi)))
    except ValueError as exc:
        raise LookupError_("Crossref vrátil odpověď, které nerozumím.") from exc
    return parse_crossref(body)


def parse_crossref(body: dict) -> dict:
    item = body.get("message") or {}
    authors = []
    for author in item.get("author", []):
        family = author.get("family") or author.get("name") or ""
        initials = "".join(part[0] for part in re.split(r"[\s.-]+", author.get("given", ""))
                           if part)
        if family:
            authors.append(f"{family} {initials}".strip())
    year = None
    for key in ("published-print", "published-online", "issued"):
        parts = (item.get(key) or {}).get("date-parts") or [[None]]
        if parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    # JATS: nadpis „Abstract“ pryč, značky pryč, mezery před interpunkcí pryč.
    abstract = re.sub(r"<jats:title>.*?</jats:title>", " ", item.get("abstract", ""),
                      flags=re.DOTALL)
    abstract = " ".join(re.sub(r"<[^>]+>", " ", abstract).split())
    abstract = re.sub(r"\s+([.,;:)])", r"\1", abstract)
    doi = item.get("DOI", "")
    return {
        "title": " ".join((item.get("title") or [""])[0].split()),
        "authors": ", ".join(authors),
        "journal": ((item.get("short-container-title") or item.get("container-title") or [""])
                    [0]),
        "year": year,
        "doi": doi,
        "pmid": "",
        "abstract": abstract,
        "url": f"https://doi.org/{doi}" if doi else "",
        "evidence_level": "",
        "source": "Crossref",
    }
