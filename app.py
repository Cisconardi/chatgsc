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

# --- Configurazione Pagina Streamlit (DEVE ESSERE IL PRIMO COMANDO STREAMLIT) ---
st.set_page_config(layout="wide", page_title="Conversa con GSC via BigQuery")

# --- Inizio Setup Credenziali GCP (MODIFICATO PER GESTIRE AttrDict) ---
_temp_gcp_creds_file_path = None

def _cleanup_temp_creds_file():
    global _temp_gcp_creds_file_path
    if _temp_gcp_creds_file_path and os.path.exists(_temp_gcp_creds_file_path):
        try:
            os.remove(_temp_gcp_creds_file_path)
        except Exception:
            pass

atexit.register(_cleanup_temp_creds_file)

try:
    if hasattr(st, 'secrets'):
        required_secrets = [
            "type", "project_id", "private_key_id", "private_key",
            "client_email", "client_id", "auth_uri", "token_uri",
            "auth_provider_x509_cert_url", "client_x509_cert_url"
        ]
        all_required_secrets_present = all(key in st.secrets for key in required_secrets)

        gcp_sa_json_str = None # Inizializza a None

        if all_required_secrets_present:
            if hasattr(st, 'sidebar') and st.sidebar: 
                 st.sidebar.info("Tentativo di costruire credenziali da secrets individuali.")
            
            gcp_credentials_dict = {}
            for key in required_secrets:
                value = st.secrets[key]
                if not isinstance(value, str):
                    if hasattr(st, 'sidebar') and st.sidebar:
                        st.sidebar.warning(f"Secret '{key}' (tipo: {type(value)}) convertito in stringa.")
                    value = str(value)
                gcp_credentials_dict[key] = value
            
            if "universe_domain" in st.secrets:
                 value_ud = st.secrets["universe_domain"]
                 if not isinstance(value_ud, str):
                     if hasattr(st, 'sidebar') and st.sidebar:
                        st.sidebar.warning(f"Secret 'universe_domain' (tipo: {type(value_ud)}) convertito in stringa.")
                     value_ud = str(value_ud)
                 gcp_credentials_dict["universe_domain"] = value_ud
            
            gcp_sa_json_str = json.dumps(gcp_credentials_dict) # Questo produce una stringa JSON

        elif "GCP_SERVICE_ACCOUNT_JSON" in st.secrets and st.secrets["GCP_SERVICE_ACCOUNT_JSON"]:
            if hasattr(st, 'sidebar') and st.sidebar:
                st.sidebar.info("Tentativo di usare il secret GCP_SERVICE_ACCOUNT_JSON completo.")
            
            gcp_sa_json_value = st.secrets["GCP_SERVICE_ACCOUNT_JSON"]
            
            if isinstance(gcp_sa_json_value, str):
                # Se è già una stringa, si assume sia un JSON valido o da validare
                gcp_sa_json_str = gcp_sa_json_value
                try:
                    json.loads(gcp_sa_json_str) # Valida se la stringa è un JSON corretto
                except json.JSONDecodeError as json_err:
                    error_message = f"Il secret GCP_SERVICE_ACCOUNT_JSON (fornito come stringa) non è JSON valido: {json_err}. Contenuto (prime 200 chars): {gcp_sa_json_str[:200]}..."
                    if hasattr(st, 'sidebar') and st.sidebar:
                        st.sidebar.error(error_message)
                    raise ValueError(error_message) from json_err
            # Modifica qui per gestire correttamente AttrDict e altri dict-like
            elif hasattr(gcp_sa_json_value, 'items') and callable(getattr(gcp_sa_json_value, 'items')):
                # Se è un dizionario/AttrDict (es. da una tabella TOML), serializzalo in una stringa JSON
                if hasattr(st, 'sidebar') and st.sidebar:
                    st.sidebar.warning(f"Il secret GCP_SERVICE_ACCOUNT_JSON era un oggetto dict-like (tipo: {type(gcp_sa_json_value)}). Convertito in stringa JSON.")
                try:
                    gcp_sa_json_str = json.dumps(dict(gcp_sa_json_value)) # Converte AttrDict/dict-like in dict, poi in stringa JSON
                except Exception as dump_err:
                    error_message = f"Errore durante la conversione del secret GCP_SERVICE_ACCOUNT_JSON (tipo: {type(gcp_sa_json_value)}) in JSON: {dump_err}"
                    if hasattr(st, 'sidebar') and st.sidebar:
                        st.sidebar.error(error_message)
                    raise ValueError(error_message) from dump_err
            else:
                # Tipo inaspettato, prova a convertirlo in stringa e spera sia un JSON
                if hasattr(st, 'sidebar') and st.sidebar:
                    st.sidebar.warning(f"Il secret GCP_SERVICE_ACCOUNT_JSON non era né stringa né dict-like (tipo: {type(gcp_sa_json_value)}). Tentativo di conversione diretta a stringa e validazione JSON.")
                gcp_sa_json_str = str(gcp_sa_json_value)
                try:
                    json.loads(gcp_sa_json_str) # Valida
                except json.JSONDecodeError as json_err:
                    error_message = f"Il secret GCP_SERVICE_ACCOUNT_JSON (convertito da tipo sconosciuto {type(gcp_sa_json_value)}) non è JSON valido: {json_err}. Contenuto (prime 200 chars): {gcp_sa_json_str[:200]}..."
                    if hasattr(st, 'sidebar') and st.sidebar:
                        st.sidebar.error(error_message)
                    raise ValueError(error_message) from json_err
        
        if gcp_sa_json_str is not None: # Assicura che gcp_sa_json_str sia stato impostato
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_json_file:
                temp_json_file.write(gcp_sa_json_str) # Ora gcp_sa_json_str dovrebbe essere sempre una stringa JSON
                _temp_gcp_creds_file_path = temp_json_file.name
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _temp_gcp_creds_file_path
            if hasattr(st, 'sidebar') and st.sidebar:
                 st.sidebar.success("Credenziali GCP elaborate e file temporaneo creato.")
        else:
            missing_keys_str = ""
            if not all_required_secrets_present and not ("GCP_SERVICE_ACCOUNT_JSON" in st.secrets and st.secrets["GCP_SERVICE_ACCOUNT_JSON"]):
                 missing_keys = [key for key in required_secrets if key not in st.secrets]
                 missing_keys_str = f" (secrets individuali mancanti: {', '.join(missing_keys)})"
            
            message = (
                "Credenziali GCP non configurate correttamente. "
                "Assicurati che tutti i campi del JSON dell'account di servizio siano definiti come secrets individuali, "
                f"oppure fornisci un singolo secret 'GCP_SERVICE_ACCOUNT_JSON' come stringa JSON o tabella TOML.{missing_keys_str}"
            )
            if hasattr(st, 'sidebar') and st.sidebar:
                st.sidebar.error(message)

    elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        if hasattr(st, 'sidebar') and st.sidebar:
            st.sidebar.info("Utilizzo di GOOGLE_APPLICATION_CREDENTIALS esistente dall'ambiente (sviluppo locale).")
    else:
        if hasattr(st, 'sidebar') and st.sidebar:
            st.sidebar.error(
                "Credenziali GCP non configurate. "
                "Per il deploy su Streamlit Cloud, configura i secrets. "
                "Per lo sviluppo locale, imposta la variabile d'ambiente GOOGLE_APPLICATION_CREDENTIALS."
            )
except Exception as e:
    error_msg_setup = f"Errore durante il setup delle credenziali GCP: {e}"
    if hasattr(st, 'sidebar') and st.sidebar:
        st.sidebar.error(error_msg_setup)
# --- Fine Setup Credenziali GCP ---


# --- Funzioni Core (DA QUI IN POI IL CODICE RIMANE INVARIATO) ---

def get_table_schema_for_prompt(project_id: str, dataset_id: str, table_names_str: str) -> str | None:
    """
    Recupera lo schema delle tabelle specificate da BigQuery e lo formatta per il prompt LLM.
    table_names_str: Una stringa di nomi di tabelle separati da virgola.
    """
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"): 
        st.error("Le credenziali GCP non sono state caricate. Impossibile procedere con get_table_schema_for_prompt.")
        return None
    if not project_id or not dataset_id or not table_names_str:
        st.error("ID Progetto, ID Dataset e Nomi Tabelle sono necessari per recuperare lo schema.")
        return None

    table_names = [name.strip() for name in table_names_str.split(',') if name.strip()]
    if not table_names:
        st.error("Per favore, fornisci almeno un nome di tabella valido.")
        return None

    try:
        client = bigquery.Client(project=project_id) 
    except Exception as e:
        st.error(f"Impossibile inizializzare il client BigQuery: {e}. Assicurati che le credenziali siano configurate.")
        return None
        
    schema_prompt_parts = []
    
    all_tables_failed = True
    for table_name in table_names:
        try:
            table_ref = client.dataset(dataset_id, project=project_id).table(table_name)
            table = client.get_table(table_ref)
            columns_desc = []
            for schema_field in table.schema:
                description = f" (Descrizione: {schema_field.description})" if schema_field.description else ""
                columns_desc.append(f"  - {schema_field.name} ({schema_field.field_type}){description}")
            
            schema_prompt_parts.append(
                f"Tabella: `{project_id}.{dataset_id}.{table_name}`\nColonne:\n" + "\n".join(columns_desc)
            )
            all_tables_failed = False 
        except Exception as e:
            st.warning(f"Impossibile recuperare lo schema per la tabella {project_id}.{dataset_id}.{table_name}: {e}")
            schema_prompt_parts.append(f"# Errore nel recupero schema per tabella: {project_id}.{dataset_id}.{table_name}")

    if all_tables_failed and table_names: 
        st.error("Nessuno schema di tabella è stato recuperato con successo. Controlla i nomi delle tabelle, i permessi e la configurazione del progetto.")
        return None
        
    return "\n\n".join(schema_prompt_parts)


def generate_sql_from_question(project_id: str, location: str, model_name: str, question: str, table_schema_prompt: str, few_shot_examples_str: str) -> str | None:
    """Genera una query SQL da una domanda in linguaggio naturale utilizzando Vertex AI."""
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"): 
        st.error("Le credenziali GCP non sono state caricate. Impossibile procedere con generate_sql_from_question.")
        return None
    if not all([project_id, location, model_name, question, table_schema_prompt]):
        st.error("Mancano alcuni parametri per la generazione SQL (progetto, location, modello, domanda, schema).")
        return None

    try:
        vertexai.init(project=project_id, location=location) 
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

        generation_config = GenerationConfig(
            temperature=0.1, 
            max_output_tokens=1024 
        )

        response = model.generate_content(full_prompt, generation_config=generation_config)
        
        if not response.candidates or not response.candidates[0].content.parts:
            st.error("Il modello non ha restituito una risposta valida.")
            st.write("Risposta grezza del modello:", response)
            return None

        sql_query = response.candidates[0].content.parts[0].text.strip()

        if "ERRORE:" in sql_query:
            st.error(f"Il modello ha indicato un errore: {sql_query}")
            return None
        
        sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

        if not sql_query.lower().startswith("select") and not sql_query.lower().startswith("with"):
            st.warning(f"La risposta del modello non sembra una query SELECT/WITH valida: {sql_query}. Tentativo di esecuzione comunque.")
        
        return sql_query

    except Exception as e:
        st.error(f"Errore durante la chiamata a Vertex AI: {e}")
        if 'last_prompt' in st.session_state:
            st.expander("Ultimo Prompt Inviato (Debug)").code(st.session_state.last_prompt, language='text')
        return None


def execute_bigquery_query(project_id: str, sql_query: str) -> pd.DataFrame | None:
    """Esegue una query SQL su BigQuery e restituisce i risultati come DataFrame Pandas."""
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        st.error("Le credenziali GCP non sono state caricate. Impossibile procedere con execute_bigquery_query.")
        return None
    if not project_id or not sql_query:
        st.error("ID Progetto e query SQL sono necessari per l'esecuzione su BigQuery.")
        return None
    try:
        client = bigquery.Client(project=project_id) 
        st.info(f"Esecuzione query su BigQuery...")
        query_job = client.query(sql_query)
        results_df = query_job.to_dataframe() 
        st.success(f"Query completata! {len(results_df)} righe restituite.")
        return results_df
    except Exception as e:
        st.error(f"Errore durante l'esecuzione della query BigQuery: {e}")
        st.code(sql_query, language='sql')
        return None

def summarize_results_with_llm(project_id: str, location: str, model_name: str, results_df: pd.DataFrame, original_question: str) -> str | None:
    """Riassume i risultati della query in linguaggio naturale utilizzando Vertex AI."""
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        st.error("Le credenziali GCP non sono state caricate. Impossibile procedere con summarize_results_with_llm.")
        return None
    if results_df.empty:
        return "Non ci sono dati da riassumere."
    if not all([project_id, location, model_name]):
        st.error("Mancano alcuni parametri per la generazione del riassunto (progetto, location, modello).")
        return None

    try:
        vertexai.init(project=project_id, location=location) 
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


# --- Interfaccia Streamlit ---
st.title("💬 Conversa con i tuoi dati di Google Search Console")
st.caption("Fai una domanda in linguaggio naturale sui tuoi dati GSC archiviati in BigQuery. L'AI la tradurrà in SQL!")

with st.sidebar:
    st.header("⚙️ Configurazione")
    
    gcp_project_id = st.text_input("ID Progetto Google Cloud", 
                                   value="nlp-project-448915", # PRECOMPILATO
                                   help="Il tuo ID progetto GCP dove risiedono i dati BigQuery e dove usare Vertex AI.")
    gcp_location = st.text_input("Location Vertex AI", "europe-west1", help="Es. us-central1, europe-west1. Deve supportare il modello scelto.")
    bq_dataset_id = st.text_input("ID Dataset BigQuery", 
                                  value="gscbu", # PRECOMPILATO
                                  help="Il dataset contenente le tabelle GSC.")
    bq_table_names_str = st.text_area(
        "Nomi Tabelle GSC (separate da virgola)", 
        "searchdata_url_impression", # PRECOMPILATO
        help="Nomi delle tabelle GSC nel dataset specificato, es. searchdata_site_impression, searchdata_url_impression"
    )
    llm_model_name = st.selectbox(
        "Modello LLM Vertex AI (Generazione SQL)",
        ("gemini-1.5-flash-001", "gemini-1.0-pro-001", "gemini-1.5-pro-001"),
        index=0,
        help="Scegli il modello per tradurre la domanda in SQL. Gemini 1.5 Flash è veloce ed economico."
    )
    
    st.subheader("Esempi Few-Shot (Opzionale ma Raccomandato)")
    st.caption("Aggiungi esempi per migliorare la traduzione NL-to-SQL. Usa i nomi completi delle tabelle (`progetto.dataset.tabella`).")
    few_shot_examples = st.text_area(
        "Formato: Domanda: [la tua domanda]\\nSQL: [la tua query SQL corrispondente]\\n(un esempio per blocco, separa gli esempi con una linea vuota)",
        height=200,
        placeholder="Domanda: Quali sono state le mie 10 query con più clic il mese scorso?\nSQL: SELECT query, SUM(clicks) as total_clicks FROM `your-project.your_dataset.searchdata_site_impression` WHERE data_date >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH) AND data_date < DATE_TRUNC(CURRENT_DATE(), MONTH) GROUP BY query ORDER BY total_clicks DESC LIMIT 10\n\nDomanda: Impressioni totali per la pagina '/mia-pagina/' ieri\nSQL: SELECT SUM(impressions) FROM `your-project.your_dataset.searchdata_url_impression` WHERE page = '/mia-pagina/' AND data_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)"
    )
    
    enable_summary = st.checkbox("Abilita riassunto LLM dei risultati", value=True)
    if enable_summary:
        summary_model_name = st.selectbox(
            "Modello LLM Vertex AI (Riassunto Risultati)",
            ("gemini-1.5-flash-001", "gemini-1.0-pro-001"),
            index=0,
            help="Scegli il modello per riassumere i risultati. Gemini 1.5 Flash è una buona opzione."
        )

if 'sql_query' not in st.session_state:
    st.session_state.sql_query = ""
if 'query_results' not in st.session_state:
    st.session_state.query_results = None
if 'results_summary' not in st.session_state:
    st.session_state.results_summary = ""
if 'table_schema_for_prompt' not in st.session_state:
    st.session_state.table_schema_for_prompt = ""
if 'last_prompt' not in st.session_state:
    st.session_state.last_prompt = ""
if 'current_schema_config_key' not in st.session_state:
    st.session_state.current_schema_config_key = ""

schema_config_key = f"{gcp_project_id}_{bq_dataset_id}_{bq_table_names_str}"
if gcp_project_id and bq_dataset_id and bq_table_names_str:
    if st.session_state.current_schema_config_key != schema_config_key:
        with st.spinner("Recupero schema tabelle da BigQuery..."):
            st.session_state.table_schema_for_prompt = get_table_schema_for_prompt(gcp_project_id, bq_dataset_id, bq_table_names_str)
        st.session_state.current_schema_config_key = schema_config_key
        if st.session_state.table_schema_for_prompt:
            if hasattr(st, 'sidebar') and st.sidebar: 
                st.sidebar.success("Schema tabelle caricato!")
                with st.sidebar.expander("Vedi Schema Caricato per Prompt"):
                    st.code(st.session_state.table_schema_for_prompt, language='text')
elif not (gcp_project_id and bq_dataset_id and bq_table_names_str) and any([gcp_project_id, bq_dataset_id, bq_table_names_str]): 
     if hasattr(st, 'sidebar') and st.sidebar: 
        st.sidebar.warning("Completa ID Progetto, ID Dataset e Nomi Tabelle per caricare lo schema.")


with st.form(key='query_form'):
    user_question = st.text_area("La tua domanda:", height=100, placeholder="Es. Quante impressioni ho ricevuto la scorsa settimana per le query che contengono 'AI'?")
    submit_button = st.form_submit_button(label="Chiedi all'AI ✨")

if submit_button and user_question:
    gcp_creds_loaded = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

    if not all([gcp_project_id, gcp_location, bq_dataset_id, bq_table_names_str]):
        st.error("Per favore, completa la configurazione nella sidebar (ID Progetto, Location, Dataset, Tabelle).")
    elif not st.session_state.table_schema_for_prompt:
        st.error("Lo schema delle tabelle non è stato caricato correttamente. Controlla la configurazione e i messaggi nella sidebar.")
    elif not gcp_creds_loaded:
         st.error("Le credenziali Google Cloud non sono caricate. Controlla la configurazione dei secrets o dell'ambiente e i messaggi nella sidebar.")
    else:
        st.session_state.sql_query = ""
        st.session_state.query_results = None
        st.session_state.results_summary = ""
        
        with st.spinner("L'AI sta pensando e generando la query SQL..."):
            st.session_state.sql_query = generate_sql_from_question(
                gcp_project_id, gcp_location, llm_model_name, user_question, 
                st.session_state.table_schema_for_prompt, few_shot_examples
            )

        if st.session_state.sql_query:
            st.subheader("🔍 Query SQL Generata:")
            st.code(st.session_state.sql_query, language='sql')
            
            with st.spinner(f"Esecuzione query su BigQuery nel progetto {gcp_project_id}..."):
                st.session_state.query_results = execute_bigquery_query(gcp_project_id, st.session_state.sql_query)

            if st.session_state.query_results is not None:
                st.subheader("📊 Risultati dalla Query:")
                if st.session_state.query_results.empty:
                    st.info("La query non ha restituito risultati.")
                else:
                    st.dataframe(st.session_state.query_results)

                    if enable_summary:
                        # Assicurati che summary_model_name sia definito se enable_summary è True
                        current_summary_model = llm_model_name # Default al modello SQL
                        if 'summary_model_name' in locals() and summary_model_name:
                            current_summary_model = summary_model_name
                        elif 'summary_model_name' in globals() and globals()['summary_model_name']: # Controllo globale se definito prima
                            current_summary_model = globals()['summary_model_name']


                        with st.spinner("L'AI sta generando un riassunto dei risultati..."):
                            st.session_state.results_summary = summarize_results_with_llm(
                                gcp_project_id, gcp_location, current_summary_model, 
                                st.session_state.query_results, user_question
                            )
                        if st.session_state.results_summary:
                            st.subheader("📝 Riassunto dei Risultati:")
                            st.markdown(st.session_state.results_summary)
        else:
            st.error("Non è stato possibile generare una query SQL per la tua domanda.")
            if 'last_prompt' in st.session_state and st.session_state.last_prompt:
                 with st.expander("Debug: Ultimo Prompt Inviato all'LLM per SQL"):
                    st.code(st.session_state.last_prompt, language='text')

elif not submit_button:
    if st.session_state.sql_query:
        st.subheader("🔍 Query SQL Generata (Precedente):")
        st.code(st.session_state.sql_query, language='sql')
    if st.session_state.query_results is not None:
        st.subheader("📊 Risultati dalla Query (Precedente):")
        if st.session_state.query_results.empty:
            st.info("La query non ha restituito risultati.")
        else:
            st.dataframe(st.session_state.query_results)
    if st.session_state.results_summary:
        st.subheader("📝 Riassunto dei Risultati (Precedente):")
        st.markdown(st.session_state.results_summary)

st.markdown("---")
st.caption("Sviluppato con Vertex AI Gemini e Streamlit.")
