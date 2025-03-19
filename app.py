import subprocess
import sys

# Definice mapování: klíč = název modulu, hodnota = název balíčku pro pip
required_packages = {
    "pandas": "pandas",
    "numpy": "numpy",
    "matplotlib": "matplotlib",
    "reportlab": "reportlab",
    "docx": "python-docx",
    "streamlit": "streamlit",
    "altair": "altair",
    "st_aggrid": "streamlit-aggrid",
    "openpyxl": "openpyxl",
}

# Kontrola a instalace chybějících balíčků
for module_name, package_name in required_packages.items():
    try:
        __import__(module_name)
    except ImportError:
        print(f"Balíček {package_name} nebyl nalezen. Instalace...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])

import streamlit as st
import pandas as pd
import altair as alt
import os
import base64
import logging
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from analyza import generuj_analyzu, generuj_word_report, priprav_podklad, load_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UPLOAD_FOLDER = "upload"
OUTPUT_FOLDER = "output"
HISTORICAL_FOLDER = "historical"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(HISTORICAL_FOLDER, exist_ok=True)

st.set_page_config(page_title="Automatizovaná analýza dat", layout="wide")

theme_choice = st.sidebar.radio("Vyberte režim zobrazení", ["Tmavý", "Světlý"])
if theme_choice == "Tmavý":
    st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background-color: #262730 !important;
        color: white !important;
    }
    [data-testid="stSidebar"] {
        background-color: #37393F !important;
    }
    /* Styl pro textová pole: přidání červeného rámečku */
    [data-testid="stTextArea"] textarea {
        border: 2px solid red !important;
        border-radius: 4px;
    }
    </style>
    """, unsafe_allow_html=True)
else:
    st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background-color: white !important;
        color: black !important;
    }
    [data-testid="stSidebar"] {
        background-color: #f0f2f6 !important;
    }
    h1, h2, h3, h4, h5, h6, .css-1d391kg {
        color: black !important;
    }
    .stButton > button {
        color: black !important;
    }
    </style>
    """, unsafe_allow_html=True)

col1, col2 = st.columns([1, 3])
with col1:
    if os.path.exists("logo_ftvs.png"):
        st.image("logo_ftvs.png", width=80)
with col2:
    st.markdown("### Aplikace – Fakulta tělesné výchovy a sportu")

st.title("📊 Automatizovaná analýza dat")

st.markdown(
    """
    <style>
    .css-1d391kg { font-size: 18px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True
)

def show_pdf(file_path):
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="900" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

st.sidebar.header("Nastavení a konfigurace")

with st.sidebar.expander("Načtení dat"):
    uploaded_file = st.file_uploader("Nahrajte soubor Excel", type=["xlsx"])
    if uploaded_file:
        file_path = os.path.join(UPLOAD_FOLDER, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        df = load_data(file_path)
        df.columns = df.columns.str.strip()
        st.dataframe(df.head())

if 'df' in locals():
    with st.sidebar.expander("Filtry"):
        if "Identifikace" in df.columns:
            ident_list = df["Identifikace"].unique().tolist()
            selected_ident = st.multiselect("Vyberte probanda", ident_list, default=ident_list)
            df = df[df["Identifikace"].isin(selected_ident)]
        if "Vek" in df.columns:
            min_age = int(df["Vek"].min())
            max_age = int(df["Vek"].max())
            age_range = st.slider("Vyberte věkový interval", min_age, max_age, (min_age, max_age))
            df = df[(df["Vek"] >= age_range[0]) & (df["Vek"] <= age_range[1])]
    
    with st.sidebar.expander("Konfigurace reportu"):
        proband_id = st.selectbox("Vyberte probanda pro report", df["Identifikace"].unique())
        default_columns = ["Jmeno", "Prijmeni", "Narozen", "Identifikace", "Vek", "Vyska", "Hmotnost"]
        available_columns = [col for col in df.columns if col not in default_columns]
        selected_columns = st.multiselect("Vyberte proměnné pro analýzu", available_columns, default=available_columns)
        graph_options = ["Poměr IR/ER", "Složení těla", "Síla úchopu a rychlost podání",
                         "Vnitřní/Vnější rotace (210°/s)", "Vnitřní/Vnější rotace (300°/s)"]
        selected_graphs = st.multiselect("Vyberte skupiny grafů", graph_options, default=graph_options)
        graph_type_options = ["Bar Chart", "Line Chart", "Scatter Plot"]
        selected_graph = st.selectbox("Vyberte typ grafu", graph_type_options, index=0, help="Zvolte způsob vykreslení grafů v reportu.")
        selected_graph_type_param = {"Bar Chart": "bar", "Line Chart": "line", "Scatter Plot": "scatter"}[selected_graph]
        numeric_vars = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]
        selected_graph_vars = st.multiselect("Vyberte proměnné pro individuální grafy", numeric_vars, default=numeric_vars)
        
    with st.sidebar.expander("Historická data – správa"):
        add_option = st.radio("Přidat data do historické databáze:", ("Jeden proband", "Celá skupina"))
        if st.button("Přidat aktuální měření do historické databáze", key="add_hist_data"):
            df["DatumMereni"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
            HIST_FILE = os.path.join(HISTORICAL_FOLDER, "historical_data.xlsx")
            if not os.path.exists(HIST_FILE):
                with pd.ExcelWriter(HIST_FILE, engine='openpyxl') as writer:
                    if add_option == "Jeden proband":
                        df[df["Identifikace"] == proband_id].to_excel(writer, index=False)
                    else:
                        df.to_excel(writer, index=False)
                st.success("Historická databáze vytvořena a data byla přidána.")
            else:
                hist_df = pd.read_excel(HIST_FILE, engine='openpyxl')
                if "Identifikace" not in hist_df.columns:
                    hist_df["Identifikace"] = hist_df["Jmeno"].astype(str) + " " + hist_df["Prijmeni"].astype(str) + ", " + hist_df["Narozen"].astype(str)
                df["DatumMereni"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
                new_data = df[df["Identifikace"] == proband_id] if add_option == "Jeden proband" else df
                hist_df = pd.concat([hist_df, new_data], ignore_index=True)
                with pd.ExcelWriter(HIST_FILE, engine='openpyxl', mode='w') as writer:
                    hist_df.to_excel(writer, index=False)
                st.success("Data byla přidána do historické databáze.")

    tab1, tab2, tab3, tab4 = st.tabs(["Dashboard", "Editace záznamů", "Reporty a podklady", "O aplikaci"])
    
    with tab1:
        st.header("Dashboard")
        st.subheader("Interaktivní grafy")
        param_opts = [col for col in df.columns if col not in ["Jmeno", "Prijmeni", "Narozen", "Identifikace", "Vek", "Vyska", "Hmotnost", "DatumMereni"]]
        if param_opts:
            parameter = st.selectbox("Vyberte parametr pro zobrazení distribuce", param_opts, key="param_current")
            base_chart = alt.Chart(df).mark_bar().encode(
                x=alt.X(f"{parameter}:Q", title=parameter),
                y=alt.Y("count()", title="Počet záznamů"),
                tooltip=[alt.Tooltip(f"{parameter}:Q", title=parameter), alt.Tooltip("count()", title="Počet")]
            )
            proband_value = df[df["Identifikace"] == proband_id][parameter].iloc[0]
            rule = alt.Chart(pd.DataFrame({
                'x': [proband_value],
                'Identifikace': [proband_id]
            })).mark_rule(color='red', strokeDash=[4,4], size=5).encode(
                x='x:Q',
                tooltip=[alt.Tooltip('x:Q', title=parameter), alt.Tooltip('Identifikace:N', title='Proband')]
            )
            chart = alt.layer(base_chart, rule).interactive()
            st.altair_chart(chart, use_container_width=True)
        st.dataframe(df)
        
        st.markdown("## Zobrazení Historických dat")
        HIST_FILE = os.path.join(HISTORICAL_FOLDER, "historical_data.xlsx")
        if os.path.exists(HIST_FILE):
            df_hist = pd.read_excel(HIST_FILE, engine='openpyxl')
            if "Identifikace" not in df_hist.columns:
                df_hist["Identifikace"] = df_hist["Jmeno"].astype(str) + " " + df_hist["Prijmeni"].astype(str) + ", " + df_hist["Narozen"].astype(str)
            if "Vek" in df_hist.columns:
                min_age_hist = int(df_hist["Vek"].min())
                max_age_hist = int(df_hist["Vek"].max())
                age_range_hist = st.slider("Vyberte věkový interval historických dat", min_age_hist, max_age_hist, (min_age_hist, max_age_hist), key="hist_age_slider_dashboard")
                df_hist = df_hist[(df_hist["Vek"] >= age_range_hist[0]) & (df_hist["Vek"] <= age_range_hist[1])]
            param_opts_hist = [col for col in df_hist.columns if col not in ["Jmeno", "Prijmeni", "Narozen", "Identifikace", "Vek", "Vyska", "Hmotnost", "DatumMereni"]]
            if param_opts_hist:
                parameter_hist = st.selectbox("Vyberte parametr pro zobrazení historických dat", param_opts_hist, key="param_hist_dashboard")
                base_chart_hist = alt.Chart(df_hist).mark_bar().encode(
                    x=alt.X(f"{parameter_hist}:Q", title=parameter_hist),
                    y=alt.Y("count()", title="Počet záznamů"),
                    tooltip=[alt.Tooltip(f"{parameter_hist}:Q", title=parameter_hist), alt.Tooltip("count()", title="Počet")]
                )
                proband_rows = df_hist[df_hist["Identifikace"] == proband_id]
                if not proband_rows.empty:
                    rule_df = proband_rows[[parameter_hist, "DatumMereni", "Identifikace"]].copy()
                    rule_df = rule_df.rename(columns={parameter_hist: "x"})
                    rule_hist = alt.Chart(rule_df).mark_rule(color='red', strokeDash=[4,4], size=5).encode(
                        x='x:Q',
                        tooltip=[alt.Tooltip('x:Q', title=parameter_hist),
                                 alt.Tooltip('DatumMereni:N', title='Datum'),
                                 alt.Tooltip('Identifikace:N', title='Proband')]
                    )
                    chart_hist = alt.layer(base_chart_hist, rule_hist).interactive()
                else:
                    chart_hist = base_chart_hist.interactive()
                st.altair_chart(chart_hist, use_container_width=True)
            st.dataframe(df_hist)
        else:
            st.error("Historická databáze neexistuje.")
    
    with tab2:
        st.header("Editace záznamů")
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_pagination(paginationAutoPageSize=True)
        gb.configure_default_column(editable=True)
        grid_options = gb.build()
        grid_response = AgGrid(df, gridOptions=grid_options, update_mode=GridUpdateMode.VALUE_CHANGED, reload_data=True)
        edited_df = grid_response["data"]
        if st.button("Uložit změny v datech", key="save_changes"):
            edited_df.to_excel(file_path, index=False)
            st.success("Data byla aktualizována!")
    
    with tab3:
        st.header("Reporty a podklady")
        report_format = st.radio("Vyberte formát reportu", ("PDF", "Word"), key="report_format")
        report_subtabs = st.tabs(["Proband vs skupina", "Proband vs předchozí měření"])
        
        with report_subtabs[0]:
            st.subheader("Porovnání probanda se skupinou")
            prumer_source_group = st.radio("Z čeho počítat průměry skupiny?", ("Aktuální data", "Historická data"), key="prumer_source_group")
            if prumer_source_group == "Aktuální data":
                group_label = "Aktuální skupina"
                data_source = None
            else:
                group_label = "Celá populace"
                HIST_FILE = os.path.join(HISTORICAL_FOLDER, "historical_data.xlsx")
                if os.path.exists(HIST_FILE):
                    data_source = pd.read_excel(os.path.join(HISTORICAL_FOLDER, "historical_data.xlsx"), engine='openpyxl')
                    if "Identifikace" not in data_source.columns:
                        data_source["Identifikace"] = data_source["Jmeno"].astype(str) + " " + data_source["Prijmeni"].astype(str) + ", " + data_source["Narozen"].astype(str)
                    if "Vek" in data_source.columns:
                        min_age = int(data_source["Vek"].min())
                        max_age = int(data_source["Vek"].max())
                        age_range = st.slider("Vyberte věkový interval historických dat", min_age, max_age, (min_age, max_age), key="hist_age_slider_report")
                        data_source = data_source[(data_source["Vek"] >= age_range[0]) & (data_source["Vek"] <= age_range[1])]
                else:
                    st.error("Historická databáze neexistuje.")
                    data_source = None
            advanced_stats_group = st.checkbox("Zobrazit rozšířené statistiky ve vygenerovaném hodonocení (Medián, Nejpeší a nejhorší výkon, Konfidenční intervaly)", value=False, key="advanced_stats_group")
            zaverecne_hodnoceni_group = st.text_area("Zadejte závěrečné doporučení (skupina)", height=200)
            if st.button("Generovat report (skupina)", key="gen_report_group"):
                if report_format == "PDF":
                    report_path = generuj_analyzu(
                        proband_id,
                        file_path,
                        zaverecne_hodnoceni_group,
                        selected_columns,
                        selected_graphs,
                        selected_graph_type_param,
                        data_df=data_source,
                        comparison_data=None,
                        advanced_stats=advanced_stats_group,
                        group_label=group_label,
                        selected_graph_vars=selected_graph_vars
                    )
                    with open(report_path, "rb") as f:
                        st.download_button("Stáhnout PDF", f, file_name=f"analyza_{proband_id}_skupina.pdf", mime="application/pdf")
                    st.success("PDF report vygenerován.")
                    show_pdf(report_path)
                else:
                    report_path = generuj_word_report(
                        proband_id,
                        file_path,
                        zaverecne_hodnoceni_group,
                        selected_columns,
                        selected_graphs,
                        selected_graph_type=selected_graph_type_param,
                        advanced_stats=advanced_stats_group,
                        group_label=group_label,
                        data_df=data_source,
                        comparison_data=None,
                        selected_graph_vars=selected_graph_vars
                    )
                    st.download_button("Stáhnout Word report", open(report_path, "rb"), file_name=f"analyza_{proband_id}_skupina.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                    st.info("Word report byl vygenerován. Otevřete jej ve Wordu a upravte dle potřeby.")
            
            if st.button("Vygenerovat podklady pro model AI (skupina)", key="gen_gpt_group"):
                podklad_text_group = priprav_podklad(proband_id, file_path, selected_columns, data_df=data_source)
                st.download_button("Stáhnout podklad – skupina", podklad_text_group, file_name=f"podklad_pro_{proband_id}_skupina.txt", mime="text/plain")
            st.markdown(
                '<a href="https://chatgpt.com/g/g-67c33271c8a081919ae40ad68ee41f49-ftvs-data-science-tenis" target="_blank" style="display: inline-block; background-color: #4CAF50; color: white; padding: 8px 16px; text-align: center; text-decoration: none; border-radius: 4px;">Otevřít model AI</a>',
                unsafe_allow_html=True
            )
        
        with report_subtabs[1]:
            st.subheader("Porovnání probanda s předchozím měřením")
            HIST_FILE = os.path.join(HISTORICAL_FOLDER, "historical_data.xlsx")
            if os.path.exists(HIST_FILE):
                df_hist = pd.read_excel(os.path.join(HISTORICAL_FOLDER, "historical_data.xlsx"), engine='openpyxl')
                if "Identifikace" not in df_hist.columns:
                    df_hist["Identifikace"] = df_hist["Jmeno"].astype(str) + " " + df_hist["Prijmeni"].astype(str) + ", " + df_hist["Narozen"].astype(str)
                proband_history = df_hist[df_hist["Identifikace"] == proband_id]
                if proband_history.empty:
                    st.error("Nebyla nalezena žádná historická měření pro tohoto probanda.")
                    comparison_row = None
                else:
                    dates = proband_history["DatumMereni"].unique()
                    selected_date = st.selectbox("Vyberte historické měření:", dates, key="historical_date")
                    comparison_row = proband_history[proband_history["DatumMereni"] == selected_date].iloc[0].to_dict()
            else:
                st.error("Historická databáze neexistuje.")
                comparison_row = None
            
            advanced_stats_time = st.checkbox("Zobrazit rozšířené statistiky, měřené skupiny probandů, ve vygenerovaném hodonocení (Medián, Nejpeší a nejhorší výkon, Konfidenční intervaly)", value=False, key="advanced_stats_time")
            zaverecne_hodnoceni_time = st.text_area("Zadejte závěrečné doporučení (časové srovnání)", height=200)
            if comparison_row is not None:
                if st.button("Generovat report (čas)", key="gen_report_time"):
                    if report_format == "PDF":
                        report_path = generuj_analyzu(
                            proband_id,
                            file_path,
                            zaverecne_hodnoceni_time,
                            selected_columns,
                            selected_graphs,
                            selected_graph_type_param,
                            data_df=df,
                            comparison_data=comparison_row,
                            advanced_stats=advanced_stats_time,
                            selected_graph_vars=selected_graph_vars
                        )
                        with open(report_path, "rb") as f:
                            st.download_button("Stáhnout PDF", f, file_name=f"analyza_{proband_id}_cas.pdf", mime="application/pdf")
                        st.success("PDF report vygenerován.")
                        show_pdf(report_path)
                    else:
                        report_path = generuj_word_report(
                            proband_id,
                            file_path,
                            zaverecne_hodnoceni_time,
                            selected_columns,
                            selected_graphs,
                            selected_graph_type=selected_graph_type_param,
                            advanced_stats=advanced_stats_time,
                            data_df=df,
                            comparison_data=comparison_row,
                            selected_graph_vars=selected_graph_vars
                        )
                        st.download_button("Stáhnout Word report", open(report_path, "rb"), file_name=f"analyza_{proband_id}_cas.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                        st.info("Word report byl vygenerován. Otevřete jej ve Wordu a upravte dle potřeby.")
                if st.button("Vygenerovat podklady pro model AI (čas)", key="gen_gpt_time"):
                    podklad_text_time = priprav_podklad(proband_id, file_path, selected_columns, data_df=df, comparison_data=comparison_row)
                    podklad_text_time += "\n\nPorovnání v čase: Toto podklad obsahuje hodnoty aktuálního měření a z vybraného historického měření, což umožňuje sledování změn v čase."
                    st.download_button("Stáhnout podklad – čas", podklad_text_time, file_name=f"podklad_pro_{proband_id}_cas.txt", mime="text/plain")
                st.markdown(
                    '<a href="https://chatgpt.com/g/g-67c33271c8a081919ae40ad68ee41f49-ftvs-data-science-tenis" target="_blank" style="display: inline-block; background-color: #4CAF50; color: white; padding: 8px 16px; text-align: center; text-decoration: none; border-radius: 4px;">Otevřít model AI</a>',
                    unsafe_allow_html=True
                )
            else:
                st.info("Pro porovnání v čase není dostupné žádné historické měření.")
    
    with tab4:
        st.header("O aplikaci")
        st.markdown("**Autor:** doc. PhDr. Michal Vágner, Ph.D.")
        st.markdown("**Email:** michal.vagner@ftvs.cuni.cz")
        st.markdown("### Návod k použití")
        st.markdown("""
**Část 1: Postup od nahrání souboru po vygenerování reportu**

1. **Načtení dat:**  
   - Nahrajte Excel soubor s daty pomocí tlačítka v levém panelu („Načtení dat“).  
   - Data se zobrazí v tabulce.

2. **Filtrování dat:**  
   - Pomocí filtru (podle unikátní identifikace a věku) vyberte, která data chcete zobrazit.

3. **Konfigurace reportu:**  
   - V sekci „Konfigurace reportu“ vyberte probanda, jehož report chcete vygenerovat, zvolte proměnné pro analýzu, předdefinované skupiny grafů a individuální grafy.
   - Vybrané předdefinované skupiny grafů se použijí pro standardní srovnání a individuální grafy zobrazí detailní pohled na každou číselnou proměnnou.

4. **Historická data:**  
   - V sekci „Historická data – správa“ můžete přidat aktuální měření do historické databáze.

5. **Generování reportu a podkladů:**  
   - Přejděte do záložky „Reporty a podklady“.
   - Vyberte formát reportu (PDF nebo Word) a zdroj dat (aktuální nebo historická).
   - V záložce **Proband vs skupina** se zobrazí tlačítka pro generování reportu a podkladů pro custom GPT model.
   - Ve záložce **Proband vs předchozí měření** jsou také tlačítka pro generování reportu a podkladů.

6. **Zobrazení reportu:**  
   - V případě PDF se report zobrazí přímo v aplikaci a nabídne se ke stažení.
   - Ve formátu Word se report nabídne ke stažení, poté jej otevřete a případně upravte ve Wordu.

**Část 2: Možnosti aplikace v jednotlivých sekcích**  

- **Dashboard:**  
  - Zobrazuje interaktivní grafy aktuálních dat s výraznou červenou svislou čárou.
  - Obsahuje také sekci „Zobrazení Historických dat“ s filtrem (sliderem) pro věkový interval.

- **Editace záznamů:**  
  - Umožňuje upravovat data v interaktivní tabulce.

- **Reporty a podklady:**  
  - Obsahuje dvě podzáložky pro srovnání probanda s aktuální skupinou nebo s historickým měřením.
  - Tlačítka pro generování reportu a podkladů jsou dostupná s unikátními klíči.
  - Kromě předdefinovaných skupin grafů se v reportu objeví i individuální grafy dle výběru.

- **O aplikaci:**  
  - Obsahuje informace o autorovi, kontakt a podrobný návod.
        """)
