import streamlit as st
from google.cloud import aiplatform # type: ignore
from google.cloud import bigquery # type: ignore
import vertexai # type: ignore
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig # type: ignore
import pandas as pd
import os
import tempfile
import json
import atexit
import matplotlib.pyplot as plt 
from google_auth_oauthlib.flow import Flow # Per OAuth
from google.oauth2.credentials import Credentials # Per OAuth
import google.auth # Per ottenere il progetto di default dalle credenziali OAuth

# --- Configurazione Pagina Streamlit (DEVE ESSERE IL PRIMO COMANDO STREAMLIT) ---
st.set_page_config(layout="wide", page_title="ChatGSC: Conversa con i dati di Google Search Console")

# --- Stile CSS Globale per ingrandire il testo dei messaggi AI ---
st.markdown("""
<style>
    div[data-testid="stChatMessage"][data-testid-user-type="ai"] div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stChatMessage"][data-testid-user-type="ai"] div[data-testid="stMarkdownContainer"] li {
        font-size: 1.25em !important; /* Puoi aggiustare 1.25em a tuo piacimento */
    }
</style>
""", unsafe_allow_html=True)


# --- Inizio Setup Credenziali GCP ---
_temp_gcp_creds_file_path = None

def _cleanup_temp_creds_file():
    global _temp_gcp_creds_file_path
    if _temp_gcp_creds_file_path and os.path.exists(_temp_gcp_creds_file_path):
        try:
            os.remove(_temp_gcp_creds_file_path)
            print(f"DEBUG: Pulito file credenziali temporaneo: {_temp_gcp_creds_file_path}")
        except Exception as e:
            print(f"DEBUG: Errore durante la pulizia del file credenziali temporaneo: {e}")
            pass
atexit.register(_cleanup_temp_creds_file)

def reset_all_auth_states():
    """Resetta tutti gli stati di autenticazione e configurazione."""
    global _temp_gcp_creds_file_path
    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
        del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    if _temp_gcp_creds_file_path and os.path.exists(_temp_gcp_creds_file_path):
        try: os.remove(_temp_gcp_creds_file_path)
        except Exception: pass
    _temp_gcp_creds_file_path = None
    
    keys_to_reset = [
        'credentials_successfully_loaded_by_app', 'uploaded_project_id', 
        'last_uploaded_file_id_processed_successfully', 'config_applied_successfully',
        'table_schema_for_prompt', 'current_schema_config_key', 
        'oauth_flow_initiated', 'user_oauth_credentials', 'oauth_project_id',
        'auth_method' 
    ]
    for key in keys_to_reset:
        if key in st.session_state:
            del st.session_state[key] # Rimuove la chiave per un reset completo
    # Re-inizializza i valori di default per le chiavi appena rimosse
    initialize_session_state() 
    print("DEBUG: Tutti gli stati di autenticazione e configurazione resettati e reinizializzati.")


def load_credentials_from_service_account_file(uploaded_file):
    global _temp_gcp_creds_file_path
    reset_all_auth_states() 

    if uploaded_file is not None:
        try:
            gcp_sa_json_str = uploaded_file.getvalue().decode("utf-8")
            creds_dict = json.loads(gcp_sa_json_str)
            st.session_state.uploaded_project_id = creds_dict.get("project_id")
            if not st.session_state.uploaded_project_id:
                st.warning("🤖💬 Il file JSON caricato non contiene un 'project_id'. Sarà necessario inserirlo manualmente.")

            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_json_file:
                temp_json_file.write(gcp_sa_json_str)
                _temp_gcp_creds_file_path = temp_json_file.name
            
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _temp_gcp_creds_file_path
            st.session_state.credentials_successfully_loaded_by_app = True
            st.session_state.last_uploaded_file_id_processed_successfully = uploaded_file.file_id
            return True
        except json.JSONDecodeError as json_err:
            st.error(f"🤖💬 Il file caricato non contiene un JSON valido: {json_err}.")
        except Exception as e:
            st.error(f"🤖💬 Errore durante il caricamento del file delle credenziali: {e}")
        
        reset_all_auth_states() 
        return False
    return False

# --- Fine Setup Credenziali GCP ---

# Modello Gemini da utilizzare
TARGET_GEMINI_MODEL = "gemini-2.0-flash-001" 
CHART_GENERATION_MODEL = "gemini-2.0-flash-001"

# --- Testo Privacy Policy ---
PRIVACY_POLICY_TEXT = """
**Informativa sulla Privacy per ChatGSC**

**Ultimo aggiornamento:** 25 Maggio 2025

**Nota Importante:** Questa applicazione permette l'autenticazione tramite caricamento di un file JSON di credenziali di un account di servizio Google Cloud oppure, in alternativa, tramite il flusso OAuth 2.0 di Google (se configurato dall'amministratore dell'app). Questa informativa copre entrambi gli scenari.

Benvenuto in ChatGSC! La tua privacy è importante per noi. Questa Informativa sulla Privacy spiega come raccogliamo, utilizziamo, divulghiamo e proteggiamo le tue informazioni quando utilizzi la nostra applicazione ChatGSC per interagire con i tuoi dati di Google Search Console tramite Google BigQuery e Vertex AI.

**1. Informazioni che Raccogliamo**

A seconda del metodo di autenticazione utilizzato:

* **Se utilizzi il caricamento del File JSON dell'Account di Servizio:**
    * **File di Credenziali dell'Account di Servizio Google Cloud:** Per funzionare, l'applicazione richiede di caricare un file JSON contenente le credenziali di un account di servizio Google Cloud. Questo file contiene informazioni sensibili (come chiavi private) che permettono all'applicazione di agire per conto di tale account di servizio per accedere alle risorse Google Cloud (BigQuery e Vertex AI) specificate nel tuo progetto. **Questo file viene elaborato localmente nel browser o temporaneamente sul server durante l'esecuzione dell'app per impostare l'autenticazione, ma non viene memorizzato in modo persistente dall'applicazione ChatGSC stessa oltre la durata della sessione di utilizzo o la necessità di autenticazione.**
* **Se utilizzi l'autenticazione OAuth 2.0 di Google (se abilitata):**
    * **Informazioni sull'Account Google:** Quando ti autentichi utilizzando OAuth 2.0, riceviamo informazioni di base dal tuo profilo Google necessarie per stabilire una connessione sicura e per identificarti come utente autorizzato. Questo di solito include il tuo indirizzo email e informazioni di profilo di base. Non memorizziamo la tua password di Google.
    * **Token di Accesso e Aggiornamento OAuth:** L'applicazione riceverà token da Google per accedere alle API per tuo conto. Questi token sono gestiti in modo sicuro.

Indipendentemente dal metodo di autenticazione:
* **Dati di Google Search Console:** Con la tua autorizzazione (tramite le credenziali dell'account di servizio o il consenso OAuth 2.0), l'applicazione accederà ai dati del tuo Google Search Console archiviati nel tuo progetto Google BigQuery. Questi dati includono metriche di performance del sito web come query di ricerca, clic, impressioni, CTR, posizione media, URL delle pagine, ecc. L'applicazione legge questi dati solo per rispondere alle tue domande.
* **Interazioni con l'AI:** Le domande che poni all'AI e le risposte generate vengono processate tramite i servizi di Google Cloud Vertex AI.

**2. Come Utilizziamo le Tue Informazioni**

Utilizziamo le informazioni raccolte per:

* **Fornire e Personalizzare il Servizio:** Per autenticarti, permetterti di interagire con i tuoi dati di Google Search Console, generare query SQL ed elaborare risposte tramite Vertex AI.
* **Funzionamento dell'Applicazione:** Le credenziali (file JSON o token OAuth) sono usate esclusivamente per consentire all'applicazione di effettuare chiamate API autenticate a Google BigQuery e Vertex AI per tuo conto.

**3. Condivisione e Divulgazione delle Informazioni**

Non vendiamo né affittiamo le tue informazioni personali a terzi.

* **Con i Servizi Google Cloud Platform:** Le tue domande e i dati di Search Console vengono processati tramite Google BigQuery e Vertex AI come parte integrante del funzionamento dell'applicazione. L'utilizzo di questi servizi è soggetto alle informative sulla privacy e ai termini di servizio di Google Cloud.
* **File di Credenziali (se usato):** Il file di credenziali JSON caricato viene utilizzato per creare un file temporaneo sul server dove l'app è in esecuzione, al solo scopo di impostare l'autenticazione per le librerie client di Google. Questo file temporaneo viene eliminato al termine della sessione dello script.
* **Per Requisiti Legali:** Se richiesto dalla legge o in risposta a validi processi legali.

**4. Sicurezza dei Dati**

* **File JSON Account di Servizio (se usato):** È tua responsabilità gestire la sicurezza del file JSON del tuo account di servizio prima di caricarlo.
* **OAuth 2.0 (se usato):** L'accesso ai tuoi dati avviene tramite il protocollo sicuro OAuth 2.0.
* Adottiamo misure ragionevoli per proteggere le tue informazioni. Tuttavia, nessuna trasmissione via Internet o metodo di archiviazione elettronica è sicuro al 100%.

**5. Conservazione dei Dati**

* **File di Credenziali Caricato (se usato):** Utilizzato temporaneamente per la sessione e poi eliminato.
* **Token OAuth (se usato):** Conservati solo per la durata necessaria a mantenere attiva la tua sessione o come consentito da Google.
* **Dati di Search Console:** Non archiviamo copie permanenti dei tuoi dati di Google Search Console. I dati vengono letti da BigQuery "on-demand".

**6. I Tuoi Diritti e Responsabilità**

* Hai il controllo sul file JSON del tuo account di servizio e sui permessi IAM ad esso associati (se usi questo metodo).
* Se usi OAuth 2.0, puoi revocare l'accesso dell'applicazione ai tuoi dati Google tramite le impostazioni di sicurezza del tuo Account Google.

**7. Modifiche a Questa Informativa sulla Privacy**

Potremmo aggiornare questa Informativa sulla Privacy. Ti informeremo pubblicando la nuova Informativa sull'applicazione.

**8. Contattaci**

Se hai domande, contattaci a: info@francisconardi o su LinkedIn

---
*Nota Importante: Questa è una bozza generica. Adattala alle funzionalità specifiche della tua app e assicurati che sia conforme alle leggi sulla privacy applicabili.*
"""

# --- Funzioni Core ---

def get_gcp_credentials_object():
    """Restituisce un oggetto credenziali GCP valido o None."""
    if st.session_state.get('auth_method') == 'Accedi con Google (OAuth 2.0)' and 'user_oauth_credentials' in st.session_state:
        creds_info = st.session_state.user_oauth_credentials
        if creds_info and 'token' in creds_info:
            try:
                return Credentials(
                    token=creds_info['token'],
                    refresh_token=creds_info.get('refresh_token'),
                    token_uri=creds_info.get('token_uri'), # Necessario per il refresh
                    client_id=creds_info.get('client_id'), # Necessario per il refresh
                    client_secret=creds_info.get('client_secret'), # Necessario per il refresh
                    scopes=creds_info.get('scopes')
                )
            except Exception as e:
                print(f"DEBUG: Errore nella creazione dell'oggetto Credentials da OAuth: {e}")
                return None
    elif st.session_state.get('auth_method') == "Carica File JSON Account di Servizio" and os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        try:
            credentials, _ = google.auth.load_credentials_from_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
            return credentials
        except Exception as e:
            print(f"DEBUG: Errore nel caricamento delle credenziali SA da file: {e}")
            return None
    return None


def get_table_schema_for_prompt(project_id: str, dataset_id: str, table_names_str: str) -> str | None:
    gcp_creds_obj = get_gcp_credentials_object()
    if not gcp_creds_obj: 
        st.error("🤖💬 Le credenziali GCP non sono state caricate correttamente. Scegli un metodo di autenticazione e completa i passaggi, poi applica la configurazione.")
        return None
    if not project_id or not dataset_id or not table_names_str:
        st.error("🤖💬 ID Progetto, ID Dataset e Nomi Tabelle sono necessari per recuperare lo schema.")
        return None
    table_names = [name.strip() for name in table_names_str.split(',') if name.strip()]
    if not table_names:
        st.error("🤖💬 Per favore, fornisci almeno un nome di tabella valido.")
        return None
    try:
        client = bigquery.Client(project=project_id, credentials=gcp_creds_obj) 
    except Exception as e:
        st.error(f"🤖💬 Impossibile inizializzare il client BigQuery: {e}. Verifica le credenziali e i permessi.")
        return None
    schema_prompt_parts = []
    all_tables_failed = True
    for table_name in table_names:
        full_table_id = f"{project_id}.{dataset_id}.{table_name}"
        try:
            table_ref = client.dataset(dataset_id, project=project_id).table(table_name)
            table = client.get_table(table_ref)
            columns_desc = []
            for schema_field in table.schema:
                description = f" (Descrizione: {schema_field.description})" if schema_field.description else ""
                columns_desc.append(f"  - {schema_field.name} ({schema_field.field_type}){description}")
            schema_prompt_parts.append(
                f"Tabella: `{full_table_id}`\nColonne:\n" + "\n".join(columns_desc)
            )
            all_tables_failed = False 
        except Exception as e:
            st.warning(f"Impossibile recuperare lo schema per la tabella {full_table_id}: {e}")
            schema_prompt_parts.append(f"# Errore nel recupero schema per tabella: {full_table_id}")
    if all_tables_failed and table_names: 
        st.error("Nessuno schema di tabella è stato recuperato con successo. Controlla i nomi delle tabelle, i permessi e la configurazione del progetto.")
        return None
    if not schema_prompt_parts and table_names: 
        st.warning("get_table_schema_for_prompt: schema_prompt_parts è vuoto alla fine, ma c'erano tabelle da processare.")
        return None
    final_schema_prompt = "\n\n".join(schema_prompt_parts)
    return final_schema_prompt

def generate_sql_from_question(project_id: str, location: str, model_name: str, question: str, table_schema_prompt: str, few_shot_examples_str: str) -> str | None:
    gcp_creds_obj = get_gcp_credentials_object()
    if not gcp_creds_obj: 
        st.error("🤖💬 Le credenziali GCP non sono state caricate. Impossibile procedere con la generazione SQL.")
        return None
    if not all([project_id, location, model_name, question, table_schema_prompt]):
        st.error("🤖💬 Mancano alcuni parametri per la generazione SQL (progetto, location, modello, domanda, schema).")
        return None
    try:
        vertexai.init(project=project_id, location=location, credentials=gcp_creds_obj) 
        model = GenerativeModel(model_name)
        prompt_parts = [
            "Sei un esperto assistente AI che traduce domande in linguaggio naturale in query SQL per Google BigQuery,",
            "specifiche per i dati di Google Search Console. Le date nelle domande (es. 'ieri', 'la scorsa settimana') devono essere interpretate",
            "rispetto alla data corrente (CURRENT_DATE()).",
            "\nSchema delle tabelle disponibili (assicurati di usare i nomi completi delle tabelle es. `progetto.dataset.tabella` nelle query):",
            table_schema_prompt,
            "\nDialetto SQL: Google BigQuery Standard SQL.",
            "Considera solo le colonne e le tabelle definite sopra.",
            "Se una domanda riguarda un periodo temporale (es. 'la scorsa settimana', 'ultimo mese'),",
            "traduci queste espressioni in opportune clausole WHERE sulla colonna `data_date` o simile colonna di data.",
            "Rispondi SOLO con la query SQL. Non aggiungere spiegazioni come 'Ecco la query SQL:', commenti SQL (--) o ```sql.",
            "Se la domanda non può essere tradotta in una query SQL basata sullo schema fornito, rispondi con 'ERRORE: Domanda non traducibile'.",
        ]
        if few_shot_examples_str and few_shot_examples_str.strip(): 
            prompt_parts.append("\nEcco alcuni esempi:")
            prompt_parts.append(few_shot_examples_str)
        prompt_parts.extend([
            f"\nDomanda dell'utente: \"{question}\"",
            "SQL:"
        ])
        full_prompt = "\n".join(prompt_parts)
        st.session_state.last_prompt = full_prompt
        generation_config = GenerationConfig(temperature=0.1, max_output_tokens=1024)
        response = model.generate_content(full_prompt, generation_config=generation_config)
        
        if not response.candidates or not response.candidates[0].content.parts:
            st.error("🤖💬 Il modello non ha restituito una risposta valida.")
            return None
        sql_query = response.candidates[0].content.parts[0].text.strip()
        if "ERRORE:" in sql_query:
            st.error(f"🤖💬 Il modello ha indicato un errore: {sql_query}")
            return None
        sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
        if not sql_query.lower().startswith("select") and not sql_query.lower().startswith("with"):
            st.warning(f"La risposta del modello non sembra una query SELECT/WITH valida: {sql_query}. Tentativo di esecuzione comunque.")
        return sql_query
    except Exception as e:
        st.error(f"🤖💬 Errore durante la chiamata a Vertex AI: {e}") 
        if 'last_prompt' in st.session_state:
            st.expander("Ultimo Prompt Inviato (Debug)").code(st.session_state.last_prompt, language='text')
        return None

def execute_bigquery_query(project_id: str, sql_query: str) -> pd.DataFrame | None:
    gcp_creds_obj = get_gcp_credentials_object()
    if not gcp_creds_obj:
        st.error("Le credenziali GCP non sono state caricate. Impossibile procedere con l'esecuzione della query.")
        return None
    if not project_id or not sql_query:
        st.error("🤖💬 ID Progetto e query SQL sono necessari per l'esecuzione su BigQuery.")
        return None
    try:
        client = bigquery.Client(project=project_id, credentials=gcp_creds_obj) 
        query_job = client.query(sql_query)
        results_df = query_job.to_dataframe() 
        return results_df
    except Exception as e:
        st.error(f"🤖💬 Errore durante l'esecuzione della query BigQuery: {e}")
        return None

def summarize_results_with_llm(project_id: str, location: str, model_name: str, results_df: pd.DataFrame, original_question: str) -> str | None:
    gcp_creds_obj = get_gcp_credentials_object()
    if not gcp_creds_obj:
        st.error("🤖💬 Le credenziali GCP non sono state caricate. Impossibile procedere con il riassunto.")
        return None
    if results_df.empty:
        return "Non ci sono dati da riassumere." 
    if not all([project_id, location, model_name]):
        st.error("🤖💬 Mancano alcuni parametri per la generazione del riassunto (progetto, location, modello).")
        return None
    try:
        vertexai.init(project=project_id, location=location, credentials=gcp_creds_obj) 
        model = GenerativeModel(model_name)
        results_sample_text = results_df.head(20).to_string(index=False)
        if len(results_df) > 20:
            results_sample_text += f"\n... e altre {len(results_df)-20} righe."
        prompt = f"""
Data la seguente domanda dell'utente:
"{original_question}"
E i seguenti risultati ottenuti da una query SQL (massimo 20 righe mostrate se più lunghe):
{results_sample_text}
Fornisci un breve riassunto conciso e in linguaggio naturale di questi risultati, rispondendo direttamente alla domanda originale dell'utente.
Non ripetere la domanda. Sii colloquiale. Se i risultati sono vuoti o non significativi, indicalo gentilmente.
**Importante: Nel tuo riassunto, metti in grassetto (usando la sintassi Markdown `**testo in grassetto**`) i seguenti tipi di informazioni per evidenziarli:**
- **Metriche e KPI specifici** (es. `**1.234 clic**`, `**CTR del 5.6%**`, `**posizione media 3.2**`)
- **Date o periodi di tempo rilevanti** (es. `**ieri**`, `**la scorsa settimana**`, `**dal 1 Maggio al 15 Maggio**`)
- **Trend numerici significativi** (es. `**un aumento del 20%**`, `**un calo di 500 impressioni**`)
- **Trend testuali o qualitativi importanti** (es. `**un notevole miglioramento**`, `**performance stabile**`, `**peggioramento significativo**`)
- **Nomi di query, pagine o segmenti specifici se sono il focus della risposta.**
"""
        generation_config = GenerationConfig(temperature=0.5, max_output_tokens=512)
        response = model.generate_content(prompt, generation_config=generation_config)
        if not response.candidates or not response.candidates[0].content.parts:
             st.warning("Il modello non ha restituito un riassunto valido.")
             return "Non è stato possibile generare un riassunto."
        return response.candidates[0].content.parts[0].text.strip()
    except Exception as e:
        st.error(f"Errore durante la generazione del riassunto: {e}")
        return "Errore nella generazione del riassunto."

def generate_chart_code_with_llm(project_id: str, location: str, model_name: str, original_question:str, sql_query:str, query_results_df: pd.DataFrame) -> str | None:
    gcp_creds_obj = get_gcp_credentials_object()
    if not gcp_creds_obj:
        st.error("🤖💬 Credenziali GCP non caricate. Impossibile generare codice per il grafico.")
        return None
    if query_results_df.empty:
        st.info("🤖💬 Nessun dato disponibile per generare un grafico.")
        return None
    try:
        vertexai.init(project=project_id, location=location, credentials=gcp_creds_obj)
        model = GenerativeModel(model_name)
        if len(query_results_df) > 10:
            data_sample = query_results_df.sample(min(10, len(query_results_df))).to_string(index=False)
        else:
            data_sample = query_results_df.to_string(index=False)
        column_details = []
        for col in query_results_df.columns:
            col_type = str(query_results_df[col].dtype)
            column_details.append(f"- Colonna '{col}' (tipo: {col_type})")
        column_info = "\n".join(column_details)
        chart_prompt = f"""
Considerando la domanda originale dell'utente:
"{original_question}"
E la query SQL eseguita:
```sql
{sql_query}
```
I dati restituiti hanno le seguenti colonne e tipi:
{column_info}
Ecco un campione dei dati (usa il DataFrame completo chiamato 'df' che ti verrà passato nello scope di esecuzione):
{data_sample}
Genera codice Python **SOLO** usando la libreria Matplotlib per creare un grafico che visualizzi efficacemente questi dati in relazione alla domanda originale.
Il codice Python generato deve:
1.  Assumere che `import matplotlib.pyplot as plt` e `import pandas as pd` siano già stati eseguiti.
2.  Assumere che i dati della query siano disponibili in un DataFrame Pandas chiamato `df`.
3.  Creare una figura Matplotlib e un asse (es. `fig, ax = plt.subplots(figsize=(10, 6))`). Prova a rendere il grafico leggibile.
4.  Usare l'asse `ax` per disegnare il grafico (es. `ax.barh(df['colonna_y'], df['colonna_x'])`, `ax.plot(df['colonna_x'], df['colonna_y'])` ecc.). Scegli il tipo di grafico più appropriato.
5.  Includere un titolo descrittivo per il grafico usando `ax.set_title('Titolo Descrittivo')`.
6.  Includere etichette chiare per gli assi X e Y (`ax.set_xlabel(...)`, `ax.set_ylabel(...)`) se il grafico non è autoesplicativo (es. grafici a torta).
7.  Se si usa un grafico a barre o a linee con etichette sull'asse X, assicurarsi che le etichette siano leggibili, ruotandole se necessario (es. `plt.setp(ax.get_xticklabels(), rotation=45, ha='right')`). Considera `ax.tick_params(axis='x', labelrotation=45)` per versioni più recenti di matplotlib.
8.  Usare `fig.tight_layout()` per migliorare la disposizione.
9.  **Importante:** Il codice NON deve includere `plt.show()`.
10. **Critico:** La figura Matplotlib creata DEVE essere assegnata a una variabile chiamata `fig` (es. `fig, ax = plt.subplots()`).
11. Se i dati non si prestano bene a una visualizzazione grafica significativa o sono troppo complessi per un grafico standard, puoi restituire un commento Python tipo `# Non è stato possibile generare un grafico significativo per questi dati.` invece del codice.
12. Privilegia grafici a barre orizzontali se stai mostrando classifiche (es. top query), con le etichette sull'asse Y.
13. Se ci sono molte categorie sull'asse X (es. date), considera di visualizzare solo un campione o aggregare.

Restituisci SOLO il blocco di codice Python. Non aggiungere spiegazioni o testo introduttivo/conclusivo.
"""
        response = model.generate_content(chart_prompt)
        if response.candidates and response.candidates[0].content.parts:
            code_content = response.candidates[0].content.parts[0].text.strip()
            if code_content.startswith("```python"):
                code_content = code_content[len("```python"):].strip()
            if code_content.endswith("```"):
                code_content = code_content[:-len("```")].strip()
            if "# Non è stato possibile generare un grafico significativo" in code_content:
                st.info(f"🤖💬 AI: {code_content}")
                return None
            return code_content
        else:
            st.warning("🤖💬 L'AI non ha generato codice per il grafico.")
            return None
    except Exception as e:
        st.error(f"🤖💬 Errore durante la generazione del codice del grafico: {e}")
        return None

# --- Interfaccia Streamlit ---
st.title("Ciao, sono ChatGSC 🤖💬")
st.caption("Fammi una domanda sui tuoi dati di Google Search Console archiviati in BigQuery. La mia AI la tradurrà in SQL e ti risponderò!")

expander_title_text = "ℹ️ Istruzioni per la Configurazione Iniziale"
with st.expander(expander_title_text, expanded=False):
    st.write("Per utilizzare questa applicazione, assicurati di aver completato i seguenti passaggi:")
    st.write("---") 
    st.subheader("1. Esportazione Dati GSC in BigQuery:")
    st.write("- Configura l'esportazione dei dati di Google Search Console verso un dataset BigQuery nel tuo progetto Google Cloud.")
    st.write("- [Guida ufficiale Google per l'esportazione GSC a BigQuery](https://support.google.com/webmasters/answer/12918484).")
    st.write("---")
    st.subheader("2. Creazione Account di Servizio GCP e Download Chiave JSON (Metodo 1):")
    st.write('- Nel tuo progetto Google Cloud, vai su "IAM e amministrazione" > "Account di servizio".')
    st.write("- Crea un nuovo account di servizio (es. `gsc-chatbot-sa`).")
    st.write("- Assegna i seguenti ruoli minimi a questo account di servizio sul progetto:")
    st.write("  - `Vertex AI User` (per accedere ai modelli Gemini)")
    st.write("  - `BigQuery Data Viewer` (per leggere dati e metadati delle tabelle)")
    st.write("  - `BigQuery Job User` (per eseguire query)")
    st.write("- Crea una chiave JSON per questo account di servizio e **scaricala sul tuo computer.** Questo file verrà caricato nell'app.")
    st.write("---")
    st.subheader("3. Configurazione OAuth 2.0 (Metodo 2 - Alternativo/Futuro):")
    st.write("- Se preferisci usare OAuth 2.0 (l'utente si autentica con il proprio account Google):")
    st.write('  - In GCP > "API e servizi" > "Credenziali", crea un "ID client OAuth".')
    st.write('  - Tipo applicazione: "Applicazione web".')
    st.write("  - Aggiungi l'URI di reindirizzamento corretto per la tua app Streamlit (es. `http://localhost:8501` per locale, o l'URL della tua app deployata).")
    st.write("  - Prendi nota dell'ID Client e del Client Secret. Dovrai aggiungerli come secrets di Streamlit (`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`).")
    st.write('  - Configura la "Schermata consenso OAuth" con gli ambiti necessari (es. `openid`, `userinfo.email`, `bigquery.readonly`, `cloud-platform`).')
    st.write("---")
    st.subheader("4. Abilitazione API Necessarie:")
    st.write("- Nel tuo progetto Google Cloud, assicurati che le seguenti API siano abilitate:")
    st.write("  - `Vertex AI API`")
    st.write("  - `BigQuery API`")
    st.write("  - `Identity and Access Management (IAM) API` (generalmente abilitata di default)")
    st.write("  - `OAuth2 API` (se usi OAuth 2.0, spesso parte di Google Identity Platform o simile)")
    st.write("---")
    st.subheader("5. Configurazione Parametri App (Sidebar):")
    st.write("- Scegli il metodo di autenticazione nella sidebar.")
    st.write("- Se usi il file JSON, caricalo.")
    st.write("- Inserisci l'**ID del tuo Progetto Google Cloud** (quello contenente i dati BigQuery e dove usare Vertex AI). Se hai caricato un file di credenziali JSON, questo campo potrebbe essere precompilato.")
    st.write(f"- Specifica la **Location Vertex AI** (es. `europe-west1`, `us-central1`). Assicurati che il modello `{TARGET_GEMINI_MODEL}` sia disponibile in questa regione per il tuo progetto.")
    st.write("- Inserisci l'**ID del Dataset BigQuery** dove hai esportato i dati GSC.")
    st.write("- Fornisci i **Nomi delle Tabelle GSC** (separate da virgola) che vuoi interrogare (es. `searchdata_url_impression`, `searchdata_site_impression`).")
    st.write("---")
    st.subheader("6. Applica Configurazione (nella Sidebar):")
    st.write("- Dopo aver completato la configurazione per il metodo di autenticazione scelto e inserito tutti i parametri, premi il pulsante **'Applica Configurazione'** nella sidebar per attivare l'applicazione.")
    st.write("---")
    st.write("Una volta configurato tutto, potrai fare domande sui tuoi dati!")

# Inizializza st.session_state
def initialize_session_state():
    default_session_state = {
        'uploaded_project_id': None, 'sql_query': "", 'query_results': None,
        'results_summary': "", 'table_schema_for_prompt': "", 'last_prompt': "",
        'current_schema_config_key': "", 'credentials_successfully_loaded_by_app': False,
        'last_uploaded_file_id_processed_successfully': None, 
        'config_applied_successfully': False, 'show_privacy_policy': False,
        'user_question_from_button': "", 'submit_from_preset_button': False,
        'auth_method': "Carica File JSON Account di Servizio", # Default al metodo JSON
        'oauth_flow_initiated': False, 'user_oauth_credentials': None,
        'oauth_project_id': None, 'gcp_project_id_input': "example-project-id",
        'enable_chart_generation': False
    }
    for key, value in default_session_state.items():
        if key not in st.session_state:
            st.session_state[key] = value

initialize_session_state()


def on_config_change():
    st.session_state.config_applied_successfully = False
    st.session_state.current_schema_config_key = "" 
    print("DEBUG: Configurazione cambiata, config_applied_successfully resettato.")

def on_auth_method_change():
    reset_all_auth_states() 
    on_config_change() 


# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Configurazione")

    auth_method_options = ["Carica File JSON Account di Servizio"]
    oauth_configured = False
    try:
        if st.secrets.get("OAUTH_CLIENT_ID") and st.secrets.get("OAUTH_CLIENT_SECRET"):
            auth_method_options.append("Accedi con Google (OAuth 2.0)")
            oauth_configured = True
    except Exception: 
        pass # st.secrets non disponibile in locale senza .streamlit/secrets.toml

    # Se c'è solo un'opzione o se auth_method non è ancora stato impostato correttamente
    if len(auth_method_options) == 1 or st.session_state.auth_method not in auth_method_options:
        st.session_state.auth_method = auth_method_options[0]
    
    if len(auth_method_options) > 1:
        st.session_state.auth_method = st.radio(
            "Scegli il metodo di autenticazione:",
            auth_method_options,
            key="auth_method_radio",
            on_change=on_auth_method_change,
            index=auth_method_options.index(st.session_state.auth_method)
        )
    else:
        st.info(f"Metodo di autenticazione: {st.session_state.auth_method}")

    
    st.divider()

    if st.session_state.auth_method == "Carica File JSON Account di Servizio":
        st.subheader("1a. Carica File Credenziali Account di Servizio")
        uploaded_credential_file = st.file_uploader(
            "Seleziona il file JSON della chiave del tuo account di servizio GCP", 
            type="json", 
            key="credential_uploader_sa",
            on_change=on_config_change 
        )
        if uploaded_credential_file is not None:
            current_file_unique_id = uploaded_credential_file.file_id
            if st.session_state.last_uploaded_file_id_processed_successfully != current_file_unique_id or \
               not st.session_state.credentials_successfully_loaded_by_app:
                if load_credentials_from_service_account_file(uploaded_credential_file):
                    st.session_state.gcp_project_id_input = st.session_state.uploaded_project_id or "example-project-id"
                    st.rerun() 
        elif uploaded_credential_file is None and st.session_state.credentials_successfully_loaded_by_app:
            reset_config_and_creds_state() 
            st.rerun()
        
        if st.session_state.credentials_successfully_loaded_by_app:
            st.success("🤖💬 Credenziali da file JSON caricate.")
        else:
            st.warning("🤖💬 Carica file credenziali JSON.")

    elif st.session_state.auth_method == "Accedi con Google (OAuth 2.0)":
        st.subheader("1b. Autenticazione Google (OAuth 2.0)")
        OAUTH_CLIENT_ID = st.secrets.get("OAUTH_CLIENT_ID")
        OAUTH_CLIENT_SECRET = st.secrets.get("OAUTH_CLIENT_SECRET")
        
        # Gestione REDIRECT_URI più robusta
        if "STREAMLIT_SERVER_ADDRESS" in os.environ and "STREAMLIT_SERVER_PORT" in os.environ: # Streamlit Cloud
             base_url = os.environ.get("STREAMLIT_SERVER_ADDRESS", "") # Questo sarà l'URL pubblico
             if not base_url.startswith("http"):
                 base_url = "https://" + base_url # Assumiamo HTTPS per Streamlit Cloud
             REDIRECT_URI = base_url.strip("/") + "/"
        else: # Sviluppo locale
            try:
                from streamlit.web.server.server import Server
                session_info = Server.get_current().get_session_info(st.runtime.scriptrunner.get_script_run_ctx().session_id)
                if session_info and hasattr(session_info, 'ws_base_url'):
                    http_protocol = "https" if session_info.ws_base_url.startswith("wss:") else "http"
                    host_port_path = session_info.ws_base_url.split("://")[1].split("/stream")[0]
                    REDIRECT_URI = f"{http_protocol}://{host_port_path}/"
                else: 
                    REDIRECT_URI = "http://localhost:8501/"
            except Exception:
                 REDIRECT_URI = "http://localhost:8501/"
        # st.caption(f"DEBUG: Redirect URI: {REDIRECT_URI}")


        SCOPES = [
            "openid", "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/cloud-platform", 
            "https://www.googleapis.com/auth/bigquery.readonly"
        ]

        if not st.session_state.get('user_oauth_credentials'):
            query_params = st.query_params
            auth_code = query_params.get("code")
            if auth_code and isinstance(auth_code, list): auth_code = auth_code[0]

            client_config_dict = {
                "web": {
                    "client_id": OAUTH_CLIENT_ID, "client_secret": OAUTH_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
                }
            }
            flow = Flow.from_client_config(client_config_dict, scopes=SCOPES, redirect_uri=REDIRECT_URI)

            if auth_code and not st.session_state.get('oauth_flow_initiated', False):
                try:
                    flow.fetch_token(code=auth_code)
                    credentials = flow.credentials
                    st.session_state.user_oauth_credentials = {
                        "token": credentials.token, "refresh_token": credentials.refresh_token,
                        "token_uri": credentials.token_uri, "client_id": credentials.client_id,
                        "client_secret": credentials.client_secret, "scopes": credentials.scopes
                    }
                    st.session_state.credentials_successfully_loaded_by_app = True # Indica che le credenziali sono caricate
                    st.session_state.oauth_flow_initiated = False
                    
                    # Tenta di ottenere il project_id dalle credenziali utente (best-effort)
                    try:
                        # Per usare le credenziali utente per questa chiamata, devono essere impostate
                        # temporaneamente o passate esplicitamente.
                        # Questo è complesso da fare in modo sicuro e robusto qui.
                        # Per ora, l'utente dovrà inserire il project_id.
                        st.session_state.uploaded_project_id = None # Non precompilare da OAuth per ora
                        st.session_state.gcp_project_id_input = "" # Richiedi input
                    except Exception as e_proj:
                        print(f"DEBUG: Impossibile ottenere project_id da credenziali OAuth: {e_proj}")
                        st.session_state.gcp_project_id_input = ""
                    
                    st.success("🤖💬 Accesso con Google riuscito!")
                    # Rimuovi il codice dalla URL e fai un rerun
                    st.query_params.clear() # Rimuove il codice dalla URL
                    st.rerun()
                except Exception as e:
                    st.error(f"🤖💬 Errore durante lo scambio del token OAuth: {e}")
                    st.session_state.oauth_flow_initiated = False
            else:
                if not st.session_state.get('oauth_flow_initiated'):
                    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
                    st.markdown(f'<a href="{auth_url}" target="_self" class="button">Accedi con Google</a>', unsafe_allow_html=True)
                    st.markdown("""
                    <style>.button {display:inline-block; background-color:#4285F4; color:white; padding:10px 15px; text-align:center; border-radius:4px; text-decoration:none; font-weight:bold;}</style>
                    """, unsafe_allow_html=True)
                    if st.button("Avvia Flusso OAuth (se il link non funziona)", key="oauth_manual_start"):
                        st.session_state.oauth_flow_initiated = True
                        st.rerun()
        
        if st.session_state.get('user_oauth_credentials'):
            st.success("🤖💬 Autenticato con Google.")
            if st.button("Logout da Google", key="oauth_logout"):
                reset_all_auth_states()
                st.rerun()

    st.divider()
    st.subheader("2. Parametri Query")
    
    current_project_id_value = "example-project-id" 
    if st.session_state.auth_method == "Carica File JSON Account di Servizio":
        current_project_id_value = st.session_state.get('uploaded_project_id', "example-project-id")
    elif st.session_state.auth_method == "Accedi con Google (OAuth 2.0)":
        current_project_id_value = st.session_state.get('gcp_project_id_input', "example-project-id")

    gcp_project_id = st.text_input("ID Progetto Google Cloud", 
                                   value=current_project_id_value, 
                                   help="ID progetto GCP. Con JSON, precompilato. Con OAuth, inseriscilo.",
                                   on_change=on_config_change,
                                   key="gcp_project_id_input_field")
    if st.session_state.auth_method == "Accedi con Google (OAuth 2.0)":
        st.session_state.gcp_project_id_input = gcp_project_id


    gcp_location = st.text_input("Location Vertex AI", "europe-west1", 
                                 help="Es. us-central1. Modello deve essere disponibile qui.",
                                 on_change=on_config_change)
    bq_dataset_id = st.text_input("ID Dataset BigQuery", 
                                  value="example-dataset-id", 
                                  help="Dataset contenente le tabelle GSC.",
                                  on_change=on_config_change)
    bq_table_names_str = st.text_area(
        "Nomi Tabelle GSC (separate da virgola)", 
        "searchdata_url_impression,searchdata_site_impression", 
        help="🤖💬 Nomi tabelle GSC, es. searchdata_site_impression, searchdata_url_impression",
        on_change=on_config_change
    )
    
    st.markdown(f"ℹ️ Modello AI utilizzato: **{TARGET_GEMINI_MODEL}**.")
    few_shot_examples = "" 

    st.divider() 
    enable_chart_generation = st.checkbox("📊 Crea grafico con AI", value=False, on_change=on_config_change, key="enable_chart")
    st.session_state.enable_chart_generation = enable_chart_generation 

    st.divider() 
    st.markdown("⚠️ **Nota sui Costi:** L'utilizzo di questa applicazione comporta chiamate alle API di Google Cloud Platform (Vertex AI, BigQuery) che sono soggette a costi. Assicurati di comprendere e monitorare i [prezzi di GCP](https://cloud.google.com/pricing).", unsafe_allow_html=True)
    st.divider() 
    
    apply_config_button = st.button("Applica Configurazione", key="apply_config")

    if apply_config_button:
        all_fields_filled = True
        if st.session_state.auth_method == "Carica File JSON Account di Servizio" and not st.session_state.credentials_successfully_loaded_by_app:
            st.error("🤖💬 Per favore, carica un file di credenziali JSON valido.")
            all_fields_filled = False
        elif st.session_state.auth_method == "Accedi con Google (OAuth 2.0)" and not st.session_state.get('user_oauth_credentials'):
            st.error("🤖💬 Per favore, completa l'accesso con Google.")
            all_fields_filled = False
        elif not st.session_state.auth_method:
             st.error("🤖💬 Scegli un metodo di autenticazione.")
             all_fields_filled = False

        if not gcp_project_id:
            st.error("🤖💬 ID Progetto Google Cloud è obbligatorio.")
            all_fields_filled = False
        if not gcp_location: st.error("🤖💬 Location Vertex AI è obbligatoria."); all_fields_filled = False
        if not bq_dataset_id: st.error("🤖💬 ID Dataset BigQuery è obbligatorio."); all_fields_filled = False
        if not bq_table_names_str: st.error("🤖💬 Nomi Tabelle GSC sono obbligatori."); all_fields_filled = False
        
        if all_fields_filled:
            st.session_state.config_applied_successfully = True
            st.session_state.current_schema_config_key = "" 
            st.success("🤖💬 Configurazione applicata! Ora puoi fare domande.")
            st.rerun() 
        else:
            st.session_state.config_applied_successfully = False
    
    if st.session_state.config_applied_successfully:
        st.info("Configurazione attiva. Modifica i campi e riapplica se necessario.")


# Logica per caricare lo schema solo se la configurazione è stata applicata
creds_available_for_schema = (st.session_state.auth_method == "Carica File JSON Account di Servizio" and os.getenv("GOOGLE_APPLICATION_CREDENTIALS")) or \
                             (st.session_state.auth_method == "Accedi con Google (OAuth 2.0)" and st.session_state.get('user_oauth_credentials'))

if st.session_state.config_applied_successfully and creds_available_for_schema:
    if gcp_project_id and bq_dataset_id and bq_table_names_str:
        schema_config_key = f"{gcp_project_id}_{bq_dataset_id}_{bq_table_names_str}"
        if st.session_state.current_schema_config_key != schema_config_key or not st.session_state.table_schema_for_prompt:
            with st.spinner("Recupero schema tabelle da BigQuery..."):
                st.session_state.table_schema_for_prompt = get_table_schema_for_prompt(gcp_project_id, bq_dataset_id, bq_table_names_str)
            st.session_state.current_schema_config_key = schema_config_key
            if st.session_state.table_schema_for_prompt:
                if hasattr(st, 'sidebar') and st.sidebar: 
                    with st.sidebar.expander("Vedi Schema Caricato per Prompt (Debug)", expanded=False): 
                        st.code(st.session_state.table_schema_for_prompt, language='text')

# --- Sezione Form Principale e Pulsanti Preimpostati ---
with st.form(key='query_form'):
    user_question_input = st.text_area(
        "La tua domanda:", 
        value=st.session_state.get("user_question_from_button", ""),
        height=100, 
        placeholder="Es. Quante impressioni ho ricevuto la scorsa settimana per le query che contengono 'AI'?",
        key="user_question_text_area" 
    )
    submit_button_main = st.form_submit_button(label="Chiedi a ChatGSC 💬")

st.write("Oppure prova una di queste domande rapide (clicca per avviare l'analisi):")
preset_questions_data = [
    ("Perf. Totale (7gg)", "Qual è stata la mia performance totale (clic, impressioni, CTR medio, posizione media) negli ultimi 7 giorni?"),
    ("Perf. Totale (28gg)", "Qual è stata la mia performance totale (clic, impressioni, CTR medio, posizione media) negli ultimi 28 giorni?"),
    ("Perf. Totale (6M)", "Qual è stata la mia performance totale (clic, impressioni, CTR medio, posizione media) negli ultimi 6 mesi?"),
    ("Perf. Totale (12M)", "Qual è stata la mia performance totale (clic, impressioni, CTR medio, posizione media) negli ultimi 12 mesi?"),
    ("Clic MoM (Mese Prec.)", "Confronta i clic totali del mese scorso con quelli di due mesi fa."),
    ("Clic YoY (Mese Prec.)", "Confronta i clic totali del mese scorso con quelli dello stesso mese dell'anno precedente."),
    ("Query in Calo (28gg)", "Quali query hanno avuto il maggior calo di clic negli ultimi 28 giorni rispetto ai 28 giorni precedenti? Fai la lista con elenco puntato numerato delle peggiori 10 con i relativi click persi."),
    ("Pagine Nuove (7gg)", "Quali sono le url che hanno ricevuto impressioni negli ultimi 7 giorni ma non ne avevano nei 7 giorni precedenti? Fai la lista con la crescite di impression più significative (max 10) con relativo aumento di impressioni.")
]

buttons_per_row = 4 
num_rows = (len(preset_questions_data) + buttons_per_row - 1) // buttons_per_row

for i in range(num_rows):
    cols = st.columns(buttons_per_row)
    for j in range(buttons_per_row):
        button_index = i * buttons_per_row + j
        if button_index < len(preset_questions_data):
            label, question_text = preset_questions_data[button_index]
            if cols[j].button(label, key=f"preset_q_{button_index}"):
                st.session_state.user_question_from_button = question_text
                st.session_state.submit_from_preset_button = True
                st.rerun()
        else:
            cols[j].empty() 

question_to_process = ""
if st.session_state.get('submit_from_preset_button', False):
    question_to_process = st.session_state.get("user_question_from_button", "")
    st.session_state.submit_from_preset_button = False 
    st.session_state.user_question_from_button = "" 
elif submit_button_main and user_question_input:
    question_to_process = user_question_input
    st.session_state.user_question_from_button = "" 

if question_to_process:
    if not st.session_state.config_applied_successfully:
        st.error("🤖💬 Per favore, completa e applica la configurazione nella sidebar prima di fare domande.")
    elif not st.session_state.table_schema_for_prompt: 
        st.error("🤖💬 Lo schema delle tabelle non è disponibile. Verifica la configurazione e i permessi, poi riapplica la configurazione.")
    else:
        st.session_state.sql_query = ""
        st.session_state.query_results = None
        st.session_state.results_summary = ""
        
        llm_model_name_to_use = TARGET_GEMINI_MODEL

        with st.spinner(f"🤖💬 Sto pensando (usando {llm_model_name_to_use}) e generando la query SQL per: \"{question_to_process}\""):
            st.session_state.sql_query = generate_sql_from_question(
                gcp_project_id, gcp_location, llm_model_name_to_use, question_to_process, 
                st.session_state.table_schema_for_prompt, few_shot_examples 
            )

        if st.session_state.sql_query:
            with st.expander("🔍 Dettagli Tecnici (Query SQL e Risultati Grezzi)", expanded=False):
                st.subheader("Query SQL Generata:")
                st.code(st.session_state.sql_query, language='sql')
            
                st.session_state.query_results = execute_bigquery_query(gcp_project_id, st.session_state.sql_query)

                if st.session_state.query_results is not None:
                    st.subheader("Risultati Grezzi dalla Query (Primi 200):")
                    if st.session_state.query_results.empty:
                        st.info("La query non ha restituito risultati.")
                    else:
                        st.dataframe(st.session_state.query_results.head(200))
                else: 
                    st.error("Fallimento esecuzione query BigQuery (vedi messaggi di errore sopra).")
            
            if st.session_state.query_results is not None:
                with st.spinner(f"🤖💬 Sto generando un riassunto dei risultati (usando {llm_model_name_to_use})..."):
                    st.session_state.results_summary = summarize_results_with_llm(
                        gcp_project_id, gcp_location, llm_model_name_to_use, 
                        st.session_state.query_results, question_to_process
                    )
                
                if st.session_state.results_summary and st.session_state.results_summary != "Non ci sono dati da riassumere.":
                    with st.chat_message("ai", avatar="🤖"):
                        st.markdown(st.session_state.results_summary) 
                elif st.session_state.query_results.empty or st.session_state.results_summary == "Non ci sono dati da riassumere.": 
                     st.info("🤖💬 La query non ha restituito risultati da riassumere o non ci sono dati.")
                else: 
                    st.warning("🤖💬 Non è stato possibile generare un riassunto, ma la query ha prodotto risultati (vedi dettagli tecnici).")

                # --- SEZIONE GENERAZIONE GRAFICO ---
                if st.session_state.get('enable_chart_generation', False) and \
                   st.session_state.query_results is not None and \
                   not st.session_state.query_results.empty:
                    st.markdown("---")
                    st.subheader("📊 Visualizzazione Grafica (Beta)")
                    with st.spinner("🤖💬 Sto generando il codice per il grafico..."):
                        chart_code = generate_chart_code_with_llm(
                            gcp_project_id, 
                            gcp_location, 
                            CHART_GENERATION_MODEL,
                            question_to_process, 
                            st.session_state.sql_query, 
                            st.session_state.query_results
                        )
                    
                    if chart_code:
                        try:
                            exec_scope = {
                                "plt": plt, 
                                "pd": pd, 
                                "df": st.session_state.query_results.copy(),
                                "fig": None 
                            }
                            exec(chart_code, exec_scope)
                            fig_generated = exec_scope.get("fig")

                            if fig_generated is not None:
                                st.pyplot(fig_generated)
                            else:
                                st.warning("🤖💬 L'AI ha generato codice, ma non è stato possibile creare un grafico ('fig' non trovata).")
                                with st.expander("Vedi codice grafico generato (Debug)"):
                                    st.code(chart_code, language="python")
                        except Exception as e:
                            st.error(f"🤖💬 Errore durante l'esecuzione del codice del grafico: {e}")
                            with st.expander("Vedi codice grafico generato (che ha causato l'errore)"):
                                st.code(chart_code, language="python")
                    elif st.session_state.enable_chart_generation: 
                        st.warning("🤖💬 Non è stato possibile generare il codice per il grafico.")
                # --- FINE SEZIONE GENERAZIONE GRAFICO ---
        else:
            st.error("Non è stato possibile generare una query SQL per la tua domanda.")
            if 'last_prompt' in st.session_state and st.session_state.last_prompt:
                 with st.expander("Debug: Ultimo Prompt Inviato all'LLM per SQL"):
                    st.code(st.session_state.last_prompt, language='text')


# Footer e Dialogo Privacy Policy
st.markdown("---")
left_footer_col, right_footer_col = st.columns([0.85, 0.15]) 

with left_footer_col:
    st.markdown(
        """
        <div style="text-align: left; padding-top: 10px; padding-bottom: 10px;">
            Made with ❤️ by <a href="[https://www.linkedin.com/in/francisco-nardi-212b338b/](https://www.linkedin.com/in/francisco-nardi-212b338b/)" target="_blank" style="text-decoration: none; color: inherit;">Francisco Nardi</a>
        </div>
        """,
        unsafe_allow_html=True
    )

with right_footer_col:
    st.markdown("<div style='padding-top: 10px;'></div>", unsafe_allow_html=True) 
    if st.button("Privacy Policy", key="privacy_button_popup_footer", help="Leggi l'informativa sulla privacy"):
        st.session_state.show_privacy_policy = True


if st.session_state.get('show_privacy_policy', False):
    st.subheader("Informativa sulla Privacy per ChatGSC")
    privacy_container = st.container()
    with privacy_container: 
        # Sostituisci ** con <b> e \n con <br> per un rendering HTML semplice
        # Questo è un workaround per lo scroll e la formattazione in assenza di st.dialog
        privacy_html = PRIVACY_POLICY_TEXT.replace('**', '<b>').replace('\n', '<br>')
        # Rimuovi l'ultimo <br> se presente per evitare spazio extra alla fine
        if privacy_html.endswith('<br>'):
            privacy_html = privacy_html[:-4]
        st.markdown(f"<div style='height: 400px; overflow-y: auto; border: 1px solid #ccc; padding:10px;'>{privacy_html}</div>", unsafe_allow_html=True)
    if st.button("Chiudi Informativa", key="close_privacy_policy_main_area"):
        st.session_state.show_privacy_policy = False
        st.rerun() 
