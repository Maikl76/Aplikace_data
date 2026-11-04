"""
Čtení odstavců a tabulek z .docx bez dalších knihoven (zipfile + XML).

Word dokument je zip s XML; pro převod podkladů stačí znát styl odstavce
(nadpis 1/2/3), jeho text a zda je tučný, a u tabulek text buněk.
"""

import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Paragraph:
    text: str
    style: str = ""
    bold: bool = False
    kind: str = "p"

    @property
    def level(self) -> int:
        """Úroveň nadpisu (1–9), 0 = běžný odstavec. Zná anglické i české styly."""
        style = self.style.lower()
        for prefix in ("heading", "nadpis"):
            if style.startswith(prefix) and style[len(prefix):].isdigit():
                return int(style[len(prefix):])
        return 0


@dataclass
class Table:
    rows: list[list[str]] = field(default_factory=list)
    kind: str = "table"


def read_blocks(path) -> list[Paragraph | Table]:
    """Odstavce a tabulky v pořadí dokumentu. Odstavce v tabulkách jsou jen v tabulce."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    body = ET.fromstring(xml).find(W + "body")
    if body is None:
        return []
    blocks: list[Paragraph | Table] = []
    for child in body:
        if child.tag == W + "p":
            blocks.append(_paragraph(child))
        elif child.tag == W + "tbl":
            blocks.append(_table(child))
    return blocks


def _text(element) -> str:
    parts = []
    for node in element.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "br":
            parts.append("\n")
        elif node.tag == W + "tab":
            parts.append("\t")
    return "".join(parts).strip()


def _paragraph(p) -> Paragraph:
    style_node = p.find(f"{W}pPr/{W}pStyle")
    style = style_node.get(W + "val", "") if style_node is not None else ""
    runs = [r for r in p.iter(W + "r") if _text(r)]
    bold = bool(runs) and all(_is_bold(r) for r in runs)
    return Paragraph(text=_text(p), style=style, bold=bold)


def _is_bold(run) -> bool:
    b = run.find(f"{W}rPr/{W}b")
    return b is not None and b.get(W + "val", "true").lower() not in ("0", "false")


def _table(tbl) -> Table:
    rows = []
    for tr in tbl.findall(W + "tr"):
        rows.append([_cell(tc) for tc in tr.findall(W + "tc")])
    return Table(rows=rows)


def _cell(tc) -> str:
    return "\n".join(_text(p) for p in tc.findall(W + "p") if _text(p))
