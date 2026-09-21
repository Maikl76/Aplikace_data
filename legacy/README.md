# Legacy – původní Streamlit aplikace

Tato složka obsahuje původní aplikaci postavenou na Streamlitu. Zůstává
funkční, dokud nová platforma nepokryje všechno, co uměla (fáze 1).

Spuštění:

    pip install -r legacy/requirements.txt
    streamlit run legacy/app.py

Po dokončení fáze 1 (náhrada Streamlitu) se tato složka smaže.

## Co se z ní přenáší do nové platformy

| Původní místo | Nová podoba |
|---|---|
| `analyza.py` → `GRAPH_GROUPS` | `catalog.Protocol` + `catalog.MetricDef` v databázi |
| `analyza.py` → `variable_legends` | `MetricDef.description` |
| `analyza.py` → `desired_direction` | `MetricDef.direction` |
| `analyza.py` → `interpretuj_graf()` | `rules.Rule` + `analytics` (MDC/SWC) |
| `app.py` → historická data v Excelu | `measurements.TestSession` + `Measurement` |
| `Identifikace = jméno + příjmení + narození` | `subjects.Subject.code` (pseudonym) |
