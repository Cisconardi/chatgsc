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
st.set_page_config(layout="wide", page_title="ChatGSC: Conversa con i dati di Google Search Console")

# --- Inizio Setup Credenziali GCP (CON FILE UPLOAD) ---
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

def reset_config_and_creds_state():
    """Resetta lo stato relativo alle credenziali e alla configurazione applicata."""
    global _temp_gcp_creds_file_path
    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
        del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    if _temp_gcp_creds_file_path and os.path.exists(_temp_gcp_creds_file_path):
        try:
            os.remove(_temp_gcp_creds_file_path)
        except Exception:
            pass
    _temp_gcp_creds_file_path = None
    st.session_state.credentials_successfully_loaded_by_app = False
    st.session_state.uploaded_project_id = None
    st.session_state.last_uploaded_file_id_processed_successfully = None
    st.session_state.config_applied_successfully = False 
    st.session_state.table_schema_for_prompt = "" 
    st.session_state.current_schema_config_key = "" 
    print("DEBUG: Stato credenziali e configurazione resettato.")


def load_credentials_from_uploaded_file(uploaded_file):
    global _temp_gcp_creds_file_path
    reset_config_and_creds_state() 

    if uploaded_file is not None:
        try:
            gcp_sa_json_str = uploaded_file.getvalue().decode("utf-8")
            
            try:
                creds_dict = json.loads(gcp_sa_json_str)
                st.session_state.uploaded_project_id = creds_dict.get("project_id")
                if not st.session_state.uploaded_project_id:
                    st.warning("🤖💬 Il file JSON caricato non contiene un 'project_id'. Sarà necessario inserirlo manualmente.")
            except json.JSONDecodeError as json_err:
                st.error(f"🤖💬 Il file caricato non contiene un JSON valido: {json_err}.")
                return False

            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_json_file:
                temp_json_file.write(gcp_sa_json_str)
                _temp_gcp_creds_file_path = temp_json_file.name
            
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _temp_gcp_creds_file_path
            print(f"DEBUG: Credenziali caricate da file upload: {_temp_gcp_creds_file_path}")
            st.session_state.credentials_successfully_loaded_by_app = True
            st.session_state.last_uploaded_file_id_processed_successfully = uploaded_file.file_id
            return True
        except Exception as e:
            st.error(f"🤖💬 Errore durante il caricamento del file delle credenziali: {e}")
            reset_config_and_creds_state() 
            return False
    return False

# --- Fine Setup Credenziali GCP ---

# Modello Gemini da utilizzare
TARGET_GEMINI_MODEL = "gemini-2.0-flash-001"

# --- Funzioni Core ---

def get_table_schema_for_prompt(project_id: str, dataset_id: str, table_names_str: str) -> str | None:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"): 
        st.error("🤖💬 Le credenziali GCP non sono state caricate. Carica il file JSON e applica la configurazione.")
        return None
    if not project_id or not dataset_id or not table_names_str:
        st.error("🤖💬 ID Progetto, ID Dataset e Nomi Tabelle sono necessari per recuperare lo schema.")
        return None

    table_names = [name.strip() for name in table_names_str.split(',') if name.strip()]
    if not table_names:
        st.error("🤖💬 Per favore, fornisci almeno un nome di tabella valido.")
        return None
    
    try:
        client = bigquery.Client(project=project_id) 
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
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"): 
        st.error("🤖💬 Le credenziali GCP non sono state caricate. Impossibile procedere con la generazione SQL.")
        return None
    if not all([project_id, location, model_name, question, table_schema_prompt]):
        st.error("🤖💬 Mancano alcuni parametri per la generazione SQL (progetto, location, modello, domanda, schema).")
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
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        st.error("Le credenziali GCP non sono state caricate. Impossibile procedere con l'esecuzione della query.")
        return None
    if not project_id or not sql_query:
        st.error("🤖💬 ID Progetto e query SQL sono necessari per l'esecuzione su BigQuery.")
        return None
    try:
        client = bigquery.Client(project=project_id) 
        # st.info(f"Esecuzione query su BigQuery...") # Nascosto
        query_job = client.query(sql_query)
        results_df = query_job.to_dataframe() 
        # st.success(f"🤖💬 Query completata! {len(results_df)} righe restituite.") # Nascosto
        return results_df
    except Exception as e:
        st.error(f"🤖💬 Errore durante l'esecuzione della query BigQuery: {e}")
        # st.code(sql_query, language='sql') # Nascosto
        return None

def summarize_results_with_llm(project_id: str, location: str, model_name: str, results_df: pd.DataFrame, original_question: str) -> str | None:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        st.error("🤖💬 Le credenziali GCP non sono state caricate. Impossibile procedere con il riassunto.")
        return None
    if results_df.empty:
        return "Non ci sono dati da riassumere." 
    if not all([project_id, location, model_name]):
        st.error("🤖💬 Mancano alcuni parametri per la generazione del riassunto (progetto, location, modello).")
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
    st.subheader("2. Creazione Account di Servizio GCP e Download Chiave JSON:")
    st.write('- Nel tuo progetto Google Cloud, vai su "IAM e amministrazione" > "Account di servizio".')
    st.write("- Crea un nuovo account di servizio (es. `gsc-chatbot-sa`).")
    st.write("- Assegna i seguenti ruoli minimi a questo account di servizio sul progetto:")
    st.write("  - `Vertex AI User` (per accedere ai modelli Gemini)")
    st.write("  - `BigQuery Data Viewer` (per leggere dati e metadati delle tabelle)")
    st.write("  - `BigQuery Job User` (per eseguire query)")
    st.write("- Crea una chiave JSON per questo account di servizio e **scaricala sul tuo computer.**")
    st.write("---")
    st.subheader("3. Caricamento File Credenziali (nella Sidebar):")
    st.write("- Nella sidebar di questa applicazione, troverai una sezione per caricare il file JSON della chiave dell'account di servizio che hai scaricato al punto 2.")
    st.write("- Carica il file per autenticare l'applicazione.")
    st.write("---")
    st.subheader("4. Abilitazione API Necessarie:")
    st.write("- Nel tuo progetto Google Cloud, assicurati che le seguenti API siano abilitate:")
    st.write("  - `Vertex AI API`")
    st.write("  - `BigQuery API`")
    st.write("---")
    st.subheader("5. Configurazione Parametri App (Sidebar):")
    st.write("- Inserisci l'**ID del tuo Progetto Google Cloud** (quello contenente i dati BigQuery e dove usare Vertex AI). Se hai caricato un file di credenziali, questo campo potrebbe essere precompilato.")
    st.write(f"- Specifica la **Location Vertex AI** (es. `europe-west1`, `us-central1`). Assicurati che il modello `{TARGET_GEMINI_MODEL}` sia disponibile in questa regione per il tuo progetto.")
    st.write("- Inserisci l'**ID del Dataset BigQuery** dove hai esportato i dati GSC.")
    st.write("- Fornisci i **Nomi delle Tabelle GSC** (separate da virgola) che vuoi interrogare (es. `searchdata_url_impression`, `searchdata_site_impression`).")
    st.write("---")
    st.subheader("6. Applica Configurazione (nella Sidebar):")
    st.write("- Dopo aver caricato le credenziali e inserito tutti i parametri, premi il pulsante **'Applica Configurazione'** nella sidebar per attivare l'applicazione.")
    st.write("---")
    st.write("Una volta configurato tutto, potrai fare domande sui tuoi dati!")

# Inizializza st.session_state se non esiste
if 'uploaded_project_id' not in st.session_state:
    st.session_state.uploaded_project_id = None
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
if 'credentials_successfully_loaded_by_app' not in st.session_state:
    st.session_state.credentials_successfully_loaded_by_app = False
if 'last_uploaded_file_id_processed_successfully' not in st.session_state: 
    st.session_state.last_uploaded_file_id_processed_successfully = None
if 'config_applied_successfully' not in st.session_state: 
    st.session_state.config_applied_successfully = False

def on_config_change():
    st.session_state.config_applied_successfully = False
    st.session_state.current_schema_config_key = "" 
    print("DEBUG: Configurazione cambiata, config_applied_successfully resettato.")


with st.sidebar:
    st.header("⚙️ Configurazione")

    st.subheader("1. Carica File Credenziali GCP (JSON)")
    uploaded_credential_file = st.file_uploader(
        "Seleziona il file JSON della chiave del tuo account di servizio GCP", 
        type="json", 
        key="credential_uploader",
        on_change=on_config_change 
    )

    if uploaded_credential_file is not None:
        current_file_unique_id = uploaded_credential_file.file_id
        if st.session_state.last_uploaded_file_id_processed_successfully != current_file_unique_id or \
           not st.session_state.credentials_successfully_loaded_by_app:
            if load_credentials_from_uploaded_file(uploaded_credential_file):
                st.session_state.credentials_successfully_loaded_by_app = True
                st.session_state.last_uploaded_file_id_processed_successfully = current_file_unique_id 
                st.rerun() 
            else:
                st.session_state.credentials_successfully_loaded_by_app = False
    elif uploaded_credential_file is None and st.session_state.credentials_successfully_loaded_by_app:
        print("DEBUG: File uploader svuotato, resetto stato credenziali.")
        reset_config_and_creds_state() 
        st.rerun()

    if st.session_state.credentials_successfully_loaded_by_app:
        st.success("🤖💬 Credenziali GCP caricate.")
    else:
        st.warning("🤖💬 Carica file credenziali GCP.")

    st.divider()
    st.subheader("2. Parametri Query")
    
    default_project_id = st.session_state.get('uploaded_project_id', "example-project-id")
    gcp_project_id = st.text_input("ID Progetto Google Cloud", 
                                   value=default_project_id, 
                                   help="ID progetto GCP. Precompilato dal JSON se possibile.",
                                   on_change=on_config_change)
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
    # Rimosso enable_summary checkbox
    
    st.divider()
    apply_config_button = st.button("Applica Configurazione", key="apply_config")

    if apply_config_button:
        all_fields_filled = True
        if not st.session_state.credentials_successfully_loaded_by_app:
            st.error("🤖💬 Per favore, carica prima un file di credenziali valido.")
            all_fields_filled = False
        if not gcp_project_id:
            st.error("🤖💬 ID Progetto Google Cloud è obbligatorio.")
            all_fields_filled = False
        if not gcp_location:
            st.error("🤖💬 Location Vertex AI è obbligatoria.")
            all_fields_filled = False
        if not bq_dataset_id:
            st.error("🤖💬 ID Dataset BigQuery è obbligatorio.")
            all_fields_filled = False
        if not bq_table_names_str:
            st.error("🤖💬 Nomi Tabelle GSC sono obbligatori.")
            all_fields_filled = False
        
        if all_fields_filled:
            st.session_state.config_applied_successfully = True
            st.session_state.current_schema_config_key = "" 
            st.success("🤖💬 Configurazione applicata! Ora puoi fare domande.")
            st.rerun() 
        else:
            st.session_state.config_applied_successfully = False
    
    if st.session_state.config_applied_successfully:
        st.info("Configurazione attiva. Modifica i campi e riapplica se necessario.")


if st.session_state.config_applied_successfully:
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and gcp_project_id and bq_dataset_id and bq_table_names_str:
        schema_config_key = f"{gcp_project_id}_{bq_dataset_id}_{bq_table_names_str}"
        if st.session_state.current_schema_config_key != schema_config_key or not st.session_state.table_schema_for_prompt:
            with st.spinner("Recupero schema tabelle da BigQuery..."):
                st.session_state.table_schema_for_prompt = get_table_schema_for_prompt(gcp_project_id, bq_dataset_id, bq_table_names_str)
            st.session_state.current_schema_config_key = schema_config_key
            if st.session_state.table_schema_for_prompt:
                if hasattr(st, 'sidebar') and st.sidebar: 
                    with st.sidebar.expander("Vedi Schema Caricato per Prompt (Debug)", expanded=False): 
                        st.code(st.session_state.table_schema_for_prompt, language='text')


with st.form(key='query_form'):
    user_question = st.text_area("La tua domanda:", height=100, placeholder="Es. Quante impressioni ho ricevuto la scorsa settimana per le query che contengono 'AI'?")
    submit_button = st.form_submit_button(label="Chiedi a ChatGSC 💬")

if submit_button and user_question:
    if not st.session_state.config_applied_successfully:
        st.error("🤖💬 Per favore, completa e applica la configurazione nella sidebar prima di fare domande.")
    elif not st.session_state.table_schema_for_prompt: 
        st.error("🤖💬 Lo schema delle tabelle non è disponibile. Verifica la configurazione e i permessi, poi riapplica la configurazione.")
    else:
        st.session_state.sql_query = ""
        st.session_state.query_results = None
        st.session_state.results_summary = ""
        
        llm_model_name_to_use = TARGET_GEMINI_MODEL

        with st.spinner(f"🤖💬 Sto pensando (usando {llm_model_name_to_use}) e generando la query SQL..."):
            st.session_state.sql_query = generate_sql_from_question(
                gcp_project_id, gcp_location, llm_model_name_to_use, user_question, 
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
                        st.session_state.query_results, user_question
                    )
                
                if st.session_state.results_summary and st.session_state.results_summary != "Non ci sono dati da riassumere.":
                    with st.chat_message("ai", avatar="🤖"):
                        # Rimosso lo stile HTML per l'ingrandimento, usa il rendering Markdown standard
                        st.markdown(st.session_state.results_summary) 
                elif st.session_state.query_results.empty or st.session_state.results_summary == "Non ci sono dati da riassumere.": 
                     st.info("🤖💬 La query non ha restituito risultati da riassumere o non ci sono dati.")
                else: 
                    st.warning("🤖💬 Non è stato possibile generare un riassunto, ma la query ha prodotto risultati (vedi dettagli tecnici).")
        else:
            st.error("Non è stato possibile generare una query SQL per la tua domanda.")
            if 'last_prompt' in st.session_state and st.session_state.last_prompt:
                 with st.expander("Debug: Ultimo Prompt Inviato all'LLM per SQL"):
                    st.code(st.session_state.last_prompt, language='text')


st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; padding: 10px;">
        Made with ❤️ by <a href="[https://www.linkedin.com/in/francisco-nardi-212b338b/](https://www.linkedin.com/in/francisco-nardi-212b338b/)" target="_blank">Francisco Nardi</a>
    </div>
    """,
    unsafe_allow_html=True
)
