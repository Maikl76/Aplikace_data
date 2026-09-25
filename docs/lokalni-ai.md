# Lokální jazykový model pro text zprávy

Model běží **na vašem počítači** (nebo později na fakultním serveru).
Data nikam neodcházejí a model dostane jen pseudonymní kód sportovce,
nikdy jméno.

## Co model dělá a co ne

**Nevyhodnocuje.** Posouzení – je hodnota pod hranicí, přesahuje změna
chybu měření, je asymetrie nad prahem – dělají pravidla a analytika,
auditovatelně a vždy stejně.

**Píše.** Dostane hotová fakta (nálezy, klíčové metriky se změnou proti
minulému měření, asymetrie, doporučení z pravidel, citace) a z nich
sestaví souvislý český souhrn s celkovým zhodnocením.

**Pojistky:**

- Text se po vygenerování strojově zkontroluje: **každé číslo v něm musí
  pocházet z dat.** Jakmile model napíše číslo, které tam není (třeba
  „12 týdnů posilování“), text se zahodí a použije se šablona.
- Když model neběží nebo neodpoví, zpráva vznikne ze šablony. Model
  nikdy nezastaví práci.
- U každé zprávy je vidět, kdo text sestavil (model, nebo šablona),
  a když model neprošel, proč.
- Zprávu vydává člověk. Text od modelu si před vydáním přečtěte – kontrola
  čísel neodhalí nešikovnou formulaci.

## Instalace s LM Studiem (Windows)

LM Studio je aplikace s grafickým rozhraním: modely se v ní hledají,
stahují a zapínají klikáním.

### 1. Instalace

Stáhněte z **https://lmstudio.ai** a nainstalujte.

### 2. Model

V LM Studiu vlevo **Discover** (lupa) a vyhledejte:

| Paměť | Hledejte | |
|---|---|---|
| 8 GB | `gemma-3-4b` | |
| 16 GB | `gemma-3-12b` nebo `qwen3-8b` | |

U výsledku LM Studio ukazuje, jestli se model do vašeho počítače vejde
(*Full GPU offload possible* / *Likely too large*). Stáhněte variantu
označenou **Q4_K_M** – dobrý poměr kvality a velikosti.

Rychlá zkouška: záložka **Chat**, nahoře vyberte model a napište
*„Napiš jednou větou česky, co je výskok z podřepu.“*

### 3. Server

Vlevo záložka **Developer** (zelená ikona `>_`):

1. Nahoře vyberte stažený model (**Select a model to load**).
2. Přepínač **Status: Stopped** → **Running**.

Server běží na `http://localhost:1234`. Nechte LM Studio otevřené –
když ho zavřete, server se vypne.

### 4. Propojení s aplikací

V okně, kde spouštíte aplikaci (s aktivním `(.venv)`):

```
git pull
python manage.py migrate
```

```
set LLM_ENABLED=True
set LLM_BASE_URL=http://localhost:1234/v1
set LLM_MODEL=zatim-nevim
```

```
python manage.py llm_check
```

Příkaz vypíše, jaké modely server nabízí, a upozorní, že `zatim-nevim`
mezi nimi není. **Zkopírujte název přesně, jak ho vypsal** (třeba
`google/gemma-3-4b`) a nastavte ho:

```
set LLM_MODEL=google/gemma-3-4b
python manage.py llm_check
```

Teď musí skončit `Spojení funguje, čísla sedí.`

> Název modelu v LM Studiu se od toho, co vidíte v nabídce, často liší.
> Proto ho nechte vypsat, místo abyste ho opisoval.

Pak `python manage.py runserver` jako obvykle a pokračujte bodem
*Zkouška na zprávě* níže.

## Instalace s Ollamou (Windows)

### 1. Ollama

Stáhněte instalátor z **https://ollama.com/download** a nainstalujte.
Ollama pak běží na pozadí (ikona u hodin).

### 2. Model

Podle paměti počítače (Správce úloh → Výkon → Paměť):

| Paměť | Model | Velikost |
|---|---|---|
| 8 GB | `gemma3:4b` | ~3 GB |
| 16 GB | `gemma3:12b` nebo `qwen3:8b` | 5–8 GB |
| grafická karta NVIDIA s 8+ GB | cokoli z výše, výrazně rychleji | |

V příkazovém řádku:

```
ollama pull gemma3:4b
```

Rychlá zkouška, že umí česky:

```
ollama run gemma3:4b "Napiš jednou větou česky, co je výskok z podřepu."
```

> Nabídka modelů se mění – aktuální je na **https://ollama.com/library**.
> Malé modely (do ~8B) píšou česky použitelně, ale ne vždy elegantně.
> Větší model = lepší čeština, ale pomalejší.

### 3. Propojení s aplikací

V okně, kde spouštíte aplikaci (s aktivním `(.venv)`):

```
git pull
python manage.py migrate
```

```
set LLM_ENABLED=True
set LLM_MODEL=gemma3:4b
```

Kontrola spojení:

```
python manage.py llm_check
```

Musí skončit `Spojení funguje, čísla sedí.` Pokud hlásí, že model přidal
čísla navíc, spojení je v pořádku – jen je vidět, jak by pojistka
zasáhla.

Pak `python manage.py runserver` jako obvykle.

## Zkouška na zprávě

**Měření → testovací den → Vytvořit zprávu z tohoto měření.** Na stránce
zprávy vpravo v části *Doložitelnost* uvidíte, kdo text sestavil
a za jak dlouho.

Aby měl model o čem psát, zapněte v **Katalogu → Pravidla** ukázková
pravidla (zakládají se vypnutá, protože jejich prahy jsou ilustrativní).

## Rychlost

Bez grafické karty trvá souhrn jednoho sportovce řádově desítky sekund
až pár minut. Stránka mezitím čeká – u zkoušení to nevadí, pro provoz se
generování přesune na pozadí.

## Nastavení

| Proměnná | Výchozí | Význam |
|---|---|---|
| `LLM_ENABLED` | `False` | zapnutí modelu |
| `LLM_MODEL` | `gemma3:4b` | název modelu v Ollamě |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | adresa serveru: Ollama `:11434`, LM Studio `http://localhost:1234/v1` |
| `LLM_TIMEOUT` | `300` | kolik sekund čekat na odpověď |
| `LLM_TEMPERATURE` | `0.2` | nízká = střídmější, méně vymýšlí |

## Ukázka na PythonAnywhere

Tam model **není** a nebude: bezplatný účet ho neutáhne a na váš
počítač nedosáhne. Zprávy tam vznikají ze šablon.
