# app.py
# ─────────────────────────────────────────────────────────────────────────────
# Streamlit aplikace s funkčním stažením podkladu (TXT) v záložce
# "Reporty a podklady". Ošetřeno: bytes, unikátní key, UTF-8, bezpečné importy.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import io
from pathlib import Path
from typing import Optional

import streamlit as st

# Volitelný import "analyza.py" (pokud v repozitáři existuje)
_ANALYZA_AVAILABLE = False
try:
    import analyza  # type: ignore
    _ANALYZA_AVAILABLE = True
except Exception:
    _ANALYZA_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# KONFIGURACE A STYL
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Aplikace – Data a Reporty",
    page_icon="📊",
    layout="wide"
)

# Minimalistický styl (volitelné)
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    .stTabs [data-baseweb="tab-list"] { gap: 0.5rem; }
    .stTabs [data-baseweb="tab"] { background: #f6f6f6; border-radius: 8px; padding: 6px 10px; }
    </style>
    """,
    unsafe_allow_html=True
)

# ─────────────────────────────────────────────────────────────────────────────
# FUNKCE: Sestavení podkladu pro AI (TXT)
# UPRAV SI: napojení na stav/filtry/datové rámce.
# MUSÍ vracet str (ne None). Pro diakritiku posíláme UTF-8 bytes.
# ─────────────────────────────────────────────────────────────────────────────
def build_ai_prompt(state: st.session_state.__class__) -> str:
    """
    Sestav textový podklad pro AI model na základě uživatelských vstupů
    a interního stavu aplikace. Místa s TODO si napoj na své proměnné.
    """
    # TODO: níže si napoj konkrétní proměnné z tvé app (filtry, data…)
    vybrane_kategorie = state.get("vybrane_kategorie", [])
    poznamka = state.get("poznamka", "").strip()

    # Kostra výstupu – uprav dle potřeby
    lines = []
    lines.append("### PODKLAD PRO AI MODEL")
    lines.append("")
    lines.append("Parametry:")
    lines.append(f"- Vybrané kategorie: {', '.join(map(str, vybrane_kategorie)) or '—'}")
    if poznamka:
        lines.append(f"- Poznámka: {poznamka}")
    lines.append("")
    lines.append("Data:")
    # TODO: tady připoj souhrn dat (např. agregace z DataFrame), nebo vybrané položky
    lines.append("- (Sem vlož shrnutí / výpis relevantních dat)")
    lines.append("")
    lines.append("Instrukce pro model:")
    # TODO: sem dej instrukce, které modelu dáváš (role, formát výstupu…)
    lines.append("- Odpovídej česky, struční a srozumitelně.")
    lines.append("- Používej body a sekce.")
    lines.append("- Zahrň konkrétní doporučení a další kroky.")
    lines.append("")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR – vstupy, které můžeš využít v build_ai_prompt()
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Nastavení vstupů")
    st.multiselect(
        "Vyber kategorie",
        options=["A", "B", "C", "D"],           # TODO: nahraď reálnými kategoriemi
        default=[],
        key="vybrane_kategorie"
    )
    st.text_area(
        "Poznámka k reportu",
        placeholder="Volitelná poznámka, která se propíše do podkladu.",
        key="poznamka"
    )
    st.caption("Tyto volby se promítnou do podkladu v záložce „Reporty a podklady“.")

# ─────────────────────────────────────────────────────────────────────────────
# HLAVNÍ OBSAH – záložky
# ─────────────────────────────────────────────────────────────────────────────
st.title("Aplikace – Data, Reporty a Podklady")

tab_home, tab_reporty, tab_analyza, tab_nastaveni = st.tabs(
    ["🏠 Domů", "📝 Reporty a podklady", "📈 Analýza dat", "⚙️ Nastavení"]
)

# ─────────────────────────────────────────────────────────────────────────────
# TAB: Domů
# ─────────────────────────────────────────────────────────────────────────────
with tab_home:
    st.subheader("Vítej!")
    st.write(
        "Tato aplikace demonstruje opravené stahování TXT podkladu "
        "přes `st.download_button` (ošetřené **bytes** + unikátní `key`)."
    )
    st.info(
        "Pokud něco nefunguje, zkontroluj, že funkce `build_ai_prompt` vrací **neprázdný `str`** "
        "a že na hostingu používáš oficiální `st.download_button` – ne HTML kotvy."
    )

# ─────────────────────────────────────────────────────────────────────────────
# TAB: Reporty a podklady  (Oprava stahování)
# ─────────────────────────────────────────────────────────────────────────────
with tab_reporty:
    st.subheader("Reporty a podklady")

    # 1) Sestav text podkladu (musí být str)
    try:
        txt = build_ai_prompt(st.session_state) or ""
    except Exception as e:
        st.error(f"Nepodařilo se sestavit podklad: {e}")
        txt = ""

    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.text_area("Náhled podkladu", value=txt, height=260, key="preview_podklad")

    with col_b:
        st.markdown("**Stažení**")
        # 2) DOWNLOAD – musí dostat BYTES (UTF-8), ne cestu na disk ani None
        st.download_button(
            label="⬇️ Stáhnout podklad (TXT)",
            data=txt.encode("utf-8"),
            file_name="podklad_AI.txt",
            mime="text/plain; charset=utf-8",
            key="download_podklad_ai_txt"
        )

        # Volitelné: možnost uložit i na disk kontejneru (užitečné při ladění)
        with st.expander("Uložit i na disk (volitelné)"):
            save_dir = Path(".out")
            if st.button("Uložit na disk jako .out/podklad_AI.txt"):
                try:
                    save_dir.mkdir(parents=True, exist_ok=True)
                    (save_dir / "podklad_AI.txt").write_bytes(txt.encode("utf-8"))
                    st.success(f"Uloženo do: {save_dir / 'podklad_AI.txt'}")
                except Exception as e:
                    st.error(f"Chyba při ukládání: {e}")

    st.caption(
        "Tip: při úpravě vstupů v sidebaru se po kliknutí mimo pole provede rerun. "
        "Tím se náhled i obsah ke stažení aktualizují."
    )

# ─────────────────────────────────────────────────────────────────────────────
# TAB: Analýza dat
# ─────────────────────────────────────────────────────────────────────────────
with tab_analyza:
    st.subheader("Analýza dat")
    if _ANALYZA_AVAILABLE and hasattr(analyza, "render"):
        # Expectujeme funkci analyza.render(st.session_state) → vykreslí vlastní UI
        try:
            analyza.render(st.session_state)  # type: ignore
        except Exception as e:
            st.error(f"Chyba při vykreslení analýzy: {e}")
    else:
        st.info(
            "Soubor `analyza.py` nebyl nalezen nebo neobsahuje funkci `render`. "
            "Vytvoř soubor `analyza.py` s funkcí `render(session_state)`, pokud chceš panel Analýza."
        )

# ─────────────────────────────────────────────────────────────────────────────
# TAB: Nastavení
# ─────────────────────────────────────────────────────────────────────────────
with tab_nastaveni:
    st.subheader("Nastavení")
    st.write("Sem můžeš přidat trvalé volby, cache, přihlašování apod.")
    st.write("Níže je jen ukázkový reset stavu:")

    if st.button("Resetovat stav aplikace"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.success("Stav vymazán. Projeví se po dalším rerun.")

# ─────────────────────────────────────────────────────────────────────────────
# KONEC SOUBORU
# ─────────────────────────────────────────────────────────────────────────────
