else:  # bigquery mode
        st.write("Oppure prova una di queste domande rapide (BigQuery):")
        preset_questions_data = [
            ("Perf. Totale (7gg)", "Qual è stata la mia performance totale (clic, impressioni, CTR medio, posizione media) negli ultimi 7 giorni?"),
            ("Perf. Totale (28gg)", "Qual è stata la mia performance totale (clic, impressioni, CTR medio, posizione media) negli ultimi 28 giorni?"),
            ("Query Top (7gg)", "Quali sono le top 10 query per clic negli ultimi 7 giorni?"),
            ("Pagine Top (7gg)", "Quali sono le top 10 pagine per impressioni negli ultimi 7 giorni?"),
            ("Clic MoM", "Confronta i clic totali del mese scorso con quelli di due mesi fa."),
            ("Query in Calo", "Quali query hanno avuto il maggior calo di clic negli ultimi 28 giorni?"),
            ("Pagine Nuove", "Quali pagine hanno ricevuto impressioni negli ultimi 7 giorni ma non nei 7 precedenti?"),
            ("CTR Migliore", "Quali query hanno il CTR più alto negli ultimi 30 giorni (min 100 impressioni)?")
        ]

    cols = st.columns(4)
    for i, (label, question_text) in enumerate(preset_questions_data):
        col_idx = i % 4
        if cols[col_idx].button(label, key=f"preset_q_{i}"):
            user_question_input = question_text
            submit_button_main = True

    # Processamento domanda
    if submit_button_main and user_question_input:
        if st.session_state.data_source_mode == "gsc_api":
            # Modalità API GSC
            if st.session_state.gsc_data.empty:
                st.error("🤖💬 Carica prima i dati GSC usando il pulsante 'Carica Dati GSC' nella sidebar.")
            else:
                # Analizza con AI usando i dati GSC
                with st.spinner(f"🤖💬 Sto analizzando i dati GSC per: \"{user_question_input}\""):
                    summary, result_df = query_gsc_with_natural_language(user_question_input, st.session_state.gsc_data)
                
                if summary and not result_df.empty:
                    with st.chat_message("ai", avatar="🤖"):
                        st.markdown(summary)
                    
                    with st.expander("🔍 Risultati Dettagliati", expanded=False):
                        st.dataframe(result_df)
                        st.write(f"**Righe risultato:** {len(result_df)}")
                    
                    # Generazione grafico se abilitata
                    if enable_chart_generation and not result_df.empty:
                        st.markdown("---")
                        st.subheader("📊 Visualizzazione Grafica")
                        # TODO: Implementare generazione grafico per dati GSC
                        st.info("🚧 Generazione grafici per API GSC in sviluppo...")
                else:
                    st.warning("🤖💬 Non è stato possibile analizzare i dati o non ci sono risultati.")
        
        else:
            # Modalità BigQuery (codice esistente)
            # Reset risultati precedenti
            st.session_state.sql_query = ""
            st.session_state.query_results = None
            st.session_state.results_summary = ""
            
            # Genera SQL
            with st.spinner(f"🤖💬 Sto generando la query SQL per: \"{user_question_input}\""):
                sql_query = generate_sql_from_question(
                    st.session_state.selected_project_id, 
                    gcp_location, 
                    TARGET_GEMINI_MODEL, 
                    user_question_input,
                    st.session_state.table_schema_for_prompt, 
                    ""
                )

            if sql_query:
                with st.expander("🔍 Dettagli Tecnici", expanded=False):
                    st.subheader("Query SQL Generata:")
                    st.code(sql_query, language='sql')
                
                    # Esegui query
                    query_results = execute_bigquery_query(st.session_state.selected_project_id, sql_query)

                    if query_results is not None:
                        st.subheader("Risultati Grezzi (Prime 200 righe):")
                        if query_results.empty:
                            st.info("La query non ha restituito risultati.")
                        else:
                            st.dataframe(query_results.head(200))
                
                if query_results is not None and not query_results.empty:
                    # Genera riassunto
                    with st.spinner("🤖💬 Sto generando un riassunto dei risultati..."):
                        results_summary = summarize_results_with_llm(
                            st.session_state.selected_project_id, 
                            gcp_location, 
                            TARGET_GEMINI_MODEL, 
                            query_results, 
                            user_question_input
                        )
                    
                    if results_summary and results_summary != "Non ci sono dati da riassumere.":
                        with st.chat_message("ai", avatar="🤖"):
                            st.markdown(results_summary) 
                    elif query_results.empty or results_summary == "Non ci sono dati da riassumere.": 
                         st.info("🤖💬 La query non ha restituito risultati da riassumere o non ci sono dati.")
                    else: 
                        st.warning("🤖💬 Non è stato possibile generare un riassunto, ma la query ha prodotto risultati (vedi dettagli tecnici).")

                    # --- SEZIONE GENERAZIONE GRAFICO ---
                    if enable_chart_generation and not query_results.empty:
                        st.markdown("---")
                        st.subheader("📊 Visualizzazione Grafica (Beta)")
                        with st.spinner("🤖💬 Sto generando il codice per il grafico..."):
                            chart_code = generate_chart_code_with_llm(
                                st.session_state.selected_project_id, 
                                gcp_location, 
                                CHART_GENERATION_MODEL,
                                user_question_input, 
                                sql_query, 
                                query_results
                            )
                        
                        if chart_code:
                            try:
                                exec_scope = {
                                    "plt": plt, 
                                    "pd": pd, 
                                    "df": query_results.copy(),
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
                        elif enable_chart_generation:import streamlit as st
from google.cloud import aiplatform # type: ignore
from google.cloud import bigquery # type: ignore
import vertexai # type: ignore
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig # type: ignore
import pandas as pd
import os
import tempfile
import json
import atexit
import time
import matplotlib.pyplot as plt
import requests
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- Configurazione Pagina Streamlit (DEVE ESSERE IL PRIMO COMANDO STREAMLIT) ---
st.set_page_config(layout="wide", page_title="ChatGSC: Conversa con i dati di Google Search Console")

# --- Configurazione Supabase ---
# Legge i secrets configurati in Streamlit Cloud con gestione errori
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
except KeyError as e:
    st.error(f"🔑 Configurazione mancante: {e}")
    st.error("Per favore configura i secrets SUPABASE_URL e SUPABASE_ANON_KEY in Streamlit Cloud.")
    st.stop()

# Inizializza client Supabase
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase: Client = init_supabase()

# --- Stile CSS Globale per ingrandire il testo dei messaggi AI ---
st.markdown("""
<style>
    div[data-testid="stChatMessage"][data-testid-user-type="ai"] div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stChatMessage"][data-testid-user-type="ai"] div[data-testid="stMarkdownContainer"] li {
        font-size: 1.25em !important;
    }
    .login-container {
        background-color: #f0f2f6;
        padding: 2rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
    .user-info {
        background-color: #e8f5e8;
        padding: 1rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Modello Gemini da utilizzare
TARGET_GEMINI_MODEL = "gemini-2.0-flash-001"
CHART_GENERATION_MODEL = "gemini-2.0-flash-001"

# --- Gestione Autenticazione OAuth ---
# --- Gestione Autenticazione OAuth ---
def handle_oauth_callback():
    """Gestisce il callback OAuth e completa l'autenticazione"""
    # Controlla se ci sono parametri di callback nella URL
    query_params = st.query_params
    
    if 'code' in query_params:
        auth_code = query_params['code']
        st.info("🔄 Completamento autenticazione in corso...")
        
        try:
            # Scambia il codice di autorizzazione con i token
            response = supabase.auth.exchange_code_for_session({
                "auth_code": auth_code
            })
            
            if response.session:
                st.session_state.authenticated = True
                st.session_state.user_email = response.session.user.email if response.session.user else "Unknown"
                st.session_state.access_token = response.session.access_token
                st.session_state.refresh_token = response.session.refresh_token
                
                # Pulisci i parametri dalla URL e il link di auth
                st.query_params.clear()
                if hasattr(st.session_state, 'auth_url'):
                    del st.session_state.auth_url
                
                st.success("✅ Login completato con successo!")
                time.sleep(1)  # Breve pausa per mostrare il messaggio
                st.rerun()
            else:
                st.error("❌ Errore durante il completamento del login")
                st.query_params.clear()
                
        except Exception as e:
            st.error(f"❌ Errore nel callback OAuth: {e}")
            st.query_params.clear()
    
    elif 'error' in query_params:
        error_description = query_params.get('error_description', 'Errore sconosciuto')
        st.error(f"❌ Errore di autenticazione: {error_description}")
        st.query_params.clear()
        if hasattr(st.session_state, 'auth_url'):
            del st.session_state.auth_url

def handle_oauth_login():
    """Gestisce il login OAuth con Google tramite Supabase"""
    try:
        # Forza l'URL di produzione
        redirect_url = "https://chatgsc.streamlit.app"
        
        st.info(f"🔧 Debug: Usando redirect URL: {redirect_url}")
        
        # Genera URL di login OAuth con parametri espliciti
        auth_response = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {
                "redirect_to": redirect_url,
                "scopes": "https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/cloud-platform.read-only",
                "query_params": {
                    "access_type": "offline",
                    "prompt": "consent"
                }
            }
        })
        
        st.write(f"🔧 Debug: URL generato: {auth_response.url}")
        
        return auth_response.url
    except Exception as e:
        st.error(f"Errore durante la generazione dell'URL di login: {e}")
        return None

def check_authentication():
    """Verifica se l'utente è autenticato"""
    # Controlla se abbiamo un token di sessione in Supabase
    session = supabase.auth.get_session()
    
    if session and session.access_token:
        # Salva i dati utente in session_state
        st.session_state.authenticated = True
        st.session_state.user_email = session.user.email if session.user else "Unknown"
        st.session_state.access_token = session.access_token
        st.session_state.refresh_token = session.refresh_token
        return True
    
    return False

def logout():
    """Effettua il logout dell'utente"""
    try:
        supabase.auth.sign_out()
        # Reset session state
        for key in ['authenticated', 'user_email', 'access_token', 'refresh_token', 
                   'gsc_sites', 'selected_project_id', 'config_applied_successfully']:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()
    except Exception as e:
        st.error(f"Errore durante il logout: {e}")

def get_gsc_sites():
    """Recupera i siti disponibili da Google Search Console"""
    if not st.session_state.get('authenticated', False):
        return []
    
    try:
        # Usa il token OAuth per accedere a Google Search Console
        credentials = Credentials(
            token=st.session_state.access_token,
            refresh_token=st.session_state.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets.get("google_oauth_client_id"),
            client_secret=st.secrets.get("google_oauth_client_secret"),
            scopes=['https://www.googleapis.com/auth/webmasters.readonly']
        )
        
        # Costruisci il servizio GSC
        service = build('searchconsole', 'v1', credentials=credentials)
        
        # Ottieni la lista dei siti
        sites_response = service.sites().list().execute()
        sites = sites_response.get('siteEntry', [])
        
        return [site['siteUrl'] for site in sites]
        
    except Exception as e:
        st.error(f"Errore nel recupero dei siti GSC: {e}")
        return []

# --- Setup Credenziali GCP tramite OAuth ---
def setup_gcp_credentials_from_oauth():
    """Configura le credenziali GCP usando il token OAuth"""
    if not st.session_state.get('authenticated', False):
        return False
    
    try:
        # Crea credenziali Google Cloud usando il token OAuth
        credentials = Credentials(
            token=st.session_state.access_token,
            refresh_token=st.session_state.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets.get("google_oauth_client_id"),
            client_secret=st.secrets.get("google_oauth_client_secret"),
            scopes=[
                'https://www.googleapis.com/auth/webmasters.readonly',
                'https://www.googleapis.com/auth/cloud-platform.read-only',
                'https://www.googleapis.com/auth/bigquery.readonly'
            ]
        )
        
        # Salva le credenziali temporaneamente
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        creds_info = {
            'type': 'authorized_user',
            'client_id': st.secrets.get("google_oauth_client_id"),
            'client_secret': st.secrets.get("google_oauth_client_secret"),
            'refresh_token': st.session_state.refresh_token,
        }
        
        json.dump(creds_info, temp_file)
        temp_file.close()
        
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_file.name
        st.session_state.temp_credentials_file = temp_file.name
        
        return True
        
    except Exception as e:
        st.error(f"Errore nella configurazione delle credenziali GCP: {e}")
        return False

# --- Inizializzazione Session State ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user_email' not in st.session_state:
    st.session_state.user_email = ""
if 'gsc_sites' not in st.session_state:
    st.session_state.gsc_sites = []
if 'selected_site' not in st.session_state:
    st.session_state.selected_site = ""
if 'selected_project_id' not in st.session_state:
    st.session_state.selected_project_id = ""
if 'config_applied_successfully' not in st.session_state:
    st.session_state.config_applied_successfully = False
if 'table_schema_for_prompt' not in st.session_state:
    st.session_state.table_schema_for_prompt = ""
if 'data_source_mode' not in st.session_state:
    st.session_state.data_source_mode = "gsc_api"  # "gsc_api" o "bigquery"
if 'gsc_data' not in st.session_state:
    st.session_state.gsc_data = pd.DataFrame()

# --- Funzioni per GSC API ---
def get_gsc_data(site_url: str, start_date: str, end_date: str, dimensions: list = None, filters: list = None) -> pd.DataFrame:
    """Recupera dati da Google Search Console API"""
    if not st.session_state.get('authenticated', False):
        st.error("🤖💬 Utente non autenticato")
        return pd.DataFrame()
    
    try:
        # Usa il token OAuth per accedere a Google Search Console
        credentials = Credentials(
            token=st.session_state.access_token,
            refresh_token=st.session_state.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets.get("google_oauth_client_id"),
            client_secret=st.secrets.get("google_oauth_client_secret"),
            scopes=['https://www.googleapis.com/auth/webmasters.readonly']
        )
        
        # Costruisci il servizio GSC
        service = build('searchconsole', 'v1', credentials=credentials)
        
        # Prepara la richiesta
        request_body = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': dimensions or ['query'],
            'rowLimit': 25000
        }
        
        if filters:
            request_body['dimensionFilterGroups'] = filters
        
        # Esegui la query
        response = service.searchanalytics().query(
            siteUrl=site_url,
            body=request_body
        ).execute()
        
        # Converti in DataFrame
        if 'rows' in response:
            data = []
            for row in response['rows']:
                row_data = {}
                # Aggiungi dimensioni
                for i, dim in enumerate(dimensions or ['query']):
                    row_data[dim] = row['keys'][i]
                
                # Aggiungi metriche
                row_data['clicks'] = row.get('clicks', 0)
                row_data['impressions'] = row.get('impressions', 0)
                row_data['ctr'] = row.get('ctr', 0.0)
                row_data['position'] = row.get('position', 0.0)
                
                data.append(row_data)
            
            return pd.DataFrame(data)
        else:
            return pd.DataFrame()
        
    except Exception as e:
        st.error(f"Errore nel recupero dei dati GSC: {e}")
        return pd.DataFrame()

def query_gsc_with_natural_language(question: str, gsc_data: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Interroga i dati GSC usando linguaggio naturale tramite AI"""
    if gsc_data.empty:
        return "Non ci sono dati GSC disponibili per rispondere alla domanda.", pd.DataFrame()
    
    if not st.session_state.get('authenticated', False):
        return "Utente non autenticato.", pd.DataFrame()
    
    try:
        # Usa Vertex AI per analizzare la domanda e generare codice pandas
        vertexai.init(project=st.session_state.selected_project_id, location="europe-west1") 
        model = GenerativeModel(TARGET_GEMINI_MODEL)
        
        # Prepara info sui dati
        columns_info = f"Colonne disponibili: {list(gsc_data.columns)}"
        sample_data = gsc_data.head(3).to_string(index=False)
        data_shape = f"Dataset: {gsc_data.shape[0]} righe, {gsc_data.shape[1]} colonne"
        
        prompt = f"""
Sei un esperto analista di dati per Google Search Console. 
Hai a disposizione un DataFrame pandas chiamato 'df' con dati GSC.

{data_shape}
{columns_info}

Campione dati:
{sample_data}

Domanda dell'utente: "{question}"

Genera codice Python che:
1. Analizza il DataFrame 'df' per rispondere alla domanda
2. Crea un nuovo DataFrame 'result_df' con i risultati
3. Include solo operazioni pandas (filter, groupby, sort, etc.)
4. Non include print(), display() o plotting

Esempio di output:
```python
# Analizza i dati per rispondere alla domanda
result_df = df.groupby('query')['clicks'].sum().sort_values(ascending=False).head(10).reset_index()
```

Restituisci SOLO il codice Python, senza spiegazioni.
"""
        
        response = model.generate_content(prompt)
        
        if response.candidates and response.candidates[0].content.parts:
            code = response.candidates[0].content.parts[0].text.strip()
            
            # Pulisci il codice
            code = code.replace("```python", "").replace("```", "").strip()
            
            # Esegui il codice
            exec_scope = {"df": gsc_data.copy(), "pd": pd, "result_df": pd.DataFrame()}
            exec(code, exec_scope)
            
            result_df = exec_scope.get('result_df', pd.DataFrame())
            
            # Genera riassunto
            if not result_df.empty:
                summary_prompt = f"""
Domanda: "{question}"

Risultati ottenuti:
{result_df.head(10).to_string(index=False)}

Fornisci un riassunto conciso dei risultati in italiano, evidenziando i punti chiave con **grassetto**.
"""
                summary_response = model.generate_content(summary_prompt)
                summary = summary_response.candidates[0].content.parts[0].text.strip() if summary_response.candidates else "Analisi completata."
            else:
                summary = "L'analisi non ha prodotto risultati."
            
            return summary, result_df
        else:
            return "Errore nella generazione del codice di analisi.", pd.DataFrame()
            
    except Exception as e:
        return f"Errore nell'analisi: {e}", pd.DataFrame()

# --- Funzioni Core (mantenute uguali) ---
def get_table_schema_for_prompt(project_id: str, dataset_id: str, table_names_str: str) -> str | None:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"): 
        st.error("🤖💬 Le credenziali GCP non sono state configurate.")
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
        
    final_schema_prompt = "\n\n".join(schema_prompt_parts)
    return final_schema_prompt

def generate_sql_from_question(project_id: str, location: str, model_name: str, question: str, table_schema_prompt: str, few_shot_examples_str: str) -> str | None:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"): 
        st.error("🤖💬 Le credenziali GCP non sono state configurate.")
        return None
    if not all([project_id, location, model_name, question, table_schema_prompt]):
        st.error("🤖💬 Mancano alcuni parametri per la generazione SQL.")
        return None

    try:
        vertexai.init(project=project_id, location=location) 
        model = GenerativeModel(model_name)
        prompt_parts = [
            "Sei un esperto assistente AI che traduce domande in linguaggio naturale in query SQL per Google BigQuery,",
            "specifiche per i dati di Google Search Console. Le date nelle domande (es. 'ieri', 'la scorsa settimana') devono essere interpretate",
            "rispetto alla data corrente (CURRENT_DATE()).",
            "\nSchema delle tabelle disponibili:",
            table_schema_prompt,
            "\nDialetto SQL: Google BigQuery Standard SQL.",
            "Considera solo le colonne e le tabelle definite sopra.",
            "Rispondi SOLO con la query SQL. Non aggiungere spiegazioni o commenti.",
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
        return sql_query
    except Exception as e:
        st.error(f"🤖💬 Errore durante la chiamata a Vertex AI: {e}") 
        return None

def execute_bigquery_query(project_id: str, sql_query: str) -> pd.DataFrame | None:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        st.error("Le credenziali GCP non sono state configurate.")
        return None
    if not project_id or not sql_query:
        st.error("🤖💬 ID Progetto e query SQL sono necessari per l'esecuzione su BigQuery.")
        return None
    try:
        client = bigquery.Client(project=project_id) 
        query_job = client.query(sql_query)
        results_df = query_job.to_dataframe() 
        return results_df
    except Exception as e:
        st.error(f"🤖💬 Errore durante l'esecuzione della query BigQuery: {e}")
        return None

def summarize_results_with_llm(project_id: str, location: str, model_name: str, results_df: pd.DataFrame, original_question: str) -> str | None:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        st.error("🤖💬 Le credenziali GCP non sono state configurate.")
        return None
    if results_df.empty:
        return "Non ci sono dati da riassumere." 
    if not all([project_id, location, model_name]):
        st.error("🤖💬 Mancano alcuni parametri per la generazione del riassunto.")
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

E i seguenti risultati ottenuti da una query SQL:
{results_sample_text}

Fornisci un breve riassunto conciso e in linguaggio naturale di questi risultati, rispondendo direttamente alla domanda originale dell'utente.
Metti in grassetto (usando **testo**) le metriche e i dati più importanti.
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
    """Genera codice Python Matplotlib per visualizzare i dati."""
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        st.error("🤖💬 Credenziali GCP non configurate.")
        return None
    if query_results_df.empty:
        st.info("🤖💬 Nessun dato disponibile per generare un grafico.")
        return None
    
    try:
        vertexai.init(project=project_id, location=location)
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
Genera codice Python usando Matplotlib per visualizzare questi dati:

Domanda: "{original_question}"
Query SQL: {sql_query}

Colonne disponibili:
{column_info}

Campione dati:
{data_sample}

Il codice deve:
1. Usare il DataFrame 'df' (già disponibile)
2. Creare figura con `fig, ax = plt.subplots(figsize=(10, 6))`
3. Scegliere il grafico più appropriato
4. Includere titolo e etichette
5. Assegnare la figura alla variabile 'fig'
6. NON includere plt.show()

Restituisci SOLO il codice Python.
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

# --- Interfaccia Principale ---
st.title("Ciao, sono ChatGSC 🤖💬")
st.caption("Fammi una domanda sui tuoi dati di Google Search Console. La mia AI la tradurrà in SQL e ti risponderò!")

# --- Gestione Callback OAuth (DEVE essere prima di tutto) ---
handle_oauth_callback()

# --- Controllo Autenticazione ---
# Verifica se l'utente è autenticato
if not check_authentication():
    st.session_state.authenticated = False

# Sidebar per autenticazione e configurazione
with st.sidebar:
    st.header("🔐 Autenticazione")
    
    if not st.session_state.get('authenticated', False):
        st.markdown("""
        <div class="login-container">
            <h4>Accedi con Google</h4>
            <p>Per utilizzare ChatGSC, effettua il login con il tuo account Google che ha accesso a Google Search Console.</p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("🔑 Accedi con Google", key="login_button", help="Login OAuth con Google"):
            auth_url = handle_oauth_login()
            if auth_url:
                st.session_state.auth_url = auth_url
                st.rerun()
        
        # Mostra il link di redirect se disponibile
        if hasattr(st.session_state, 'auth_url') and st.session_state.auth_url:
            st.markdown("### 🔗 Completa il Login")
            st.link_button(
                "🚀 Vai a Google per Autenticarti", 
                st.session_state.auth_url,
                help="Clicca per completare l'autenticazione OAuth"
            )
            st.info("👆 Clicca il pulsante sopra per completare il login OAuth")
            
            # Reset del link dopo un po'
            if st.button("🔄 Genera Nuovo Link", key="reset_auth_link"):
                if hasattr(st.session_state, 'auth_url'):
                    del st.session_state.auth_url
                st.rerun()
        
        st.markdown("---")
        st.subheader("ℹ️ Come funziona")
        st.write("1. **Login OAuth**: Accedi con Google")
        st.write("2. **Permessi**: Autorizza l'accesso a GSC e GCP")
        st.write("3. **Configurazione**: Seleziona progetto e dataset")
        st.write("4. **Chat**: Fai domande sui tuoi dati!")
        
    else:
        # Utente autenticato - mostra info e configurazione
        st.markdown(f"""
        <div class="user-info">
            <h4>👤 Utente Connesso</h4>
            <p><strong>Email:</strong> {st.session_state.user_email}</p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("🚪 Logout", key="logout_button"):
            logout()
        
        st.markdown("---")
        st.subheader("📊 Sorgente Dati")
        
        # Selezione modalità dati
        data_mode = st.radio(
            "Come vuoi interrogare i tuoi dati?",
            options=["gsc_api", "bigquery"],
            format_func=lambda x: {
                "gsc_api": "🔗 API Google Search Console (Diretto)",
                "bigquery": "📊 BigQuery (SQL)"
            }[x],
            key="data_mode_selector",
            help="Scegli se usare le API GSC direttamente o i dati esportati in BigQuery"
        )
        st.session_state.data_source_mode = data_mode
        
        if data_mode == "gsc_api":
            st.markdown("### 🔗 Configurazione API GSC")
            
            # Carica siti GSC se non già fatto
            if not st.session_state.gsc_sites:
                with st.spinner("Caricando i tuoi siti GSC..."):
                    st.session_state.gsc_sites = get_gsc_sites()
            
            # Selezione sito GSC
            if st.session_state.gsc_sites:
                selected_site = st.selectbox(
                    "🌐 Seleziona Sito GSC",
                    options=st.session_state.gsc_sites,
                    key="site_selector"
                )
                st.session_state.selected_site = selected_site
                
                # Configurazione periodo e dimensioni
                col1, col2 = st.columns(2)
                with col1:
                    start_date = st.date_input(
                        "📅 Data Inizio",
                        value=pd.Timestamp.now() - pd.Timedelta(days=30),
                        key="gsc_start_date"
                    )
                with col2:
                    end_date = st.date_input(
                        "📅 Data Fine", 
                        value=pd.Timestamp.now() - pd.Timedelta(days=1),
                        key="gsc_end_date"
                    )
                
                dimensions = st.multiselect(
                    "📏 Dimensioni",
                    options=['query', 'page', 'country', 'device', 'searchAppearance'],
                    default=['query'],
                    help="Seleziona le dimensioni per l'analisi",
                    key="gsc_dimensions"
                )
                
                if st.button("📥 Carica Dati GSC", key="load_gsc_data"):
                    if selected_site and start_date and end_date:
                        with st.spinner("Caricando dati da Google Search Console..."):
                            st.session_state.gsc_data = get_gsc_data(
                                selected_site,
                                start_date.strftime('%Y-%m-%d'),
                                end_date.strftime('%Y-%m-%d'),
                                dimensions
                            )
                        
                        if not st.session_state.gsc_data.empty:
                            st.success(f"✅ Caricati {len(st.session_state.gsc_data)} record da GSC!")
                            st.session_state.config_applied_successfully = True
                            
                            # Mostra anteprima
                            with st.expander("👀 Anteprima Dati", expanded=False):
                                st.dataframe(st.session_state.gsc_data.head(10))
                                st.write(f"**Forma dataset:** {st.session_state.gsc_data.shape}")
                        else:
                            st.warning("⚠️ Nessun dato trovato per il periodo selezionato")
                    else:
                        st.error("❌ Seleziona sito e periodo validi")
            else:
                st.warning("Nessun sito GSC trovato per il tuo account")
        
        elif data_mode == "bigquery":
            st.markdown("### 📊 Configurazione BigQuery")
            
            # Configurazione progetto GCP
            gcp_project_id = st.text_input(
                "🔧 ID Progetto Google Cloud",
                value=st.session_state.get('selected_project_id', ''),
                help="Progetto GCP dove sono i dati BigQuery"
            )
            
            gcp_location = st.text_input(
                "🌍 Location Vertex AI",
                value="europe-west1",
                help="Regione per Vertex AI"
            )
            
            bq_dataset_id = st.text_input(
                "📊 ID Dataset BigQuery",
                value="",
                help="Dataset con le tabelle GSC"
            )
            
            bq_table_names_str = st.text_area(
                "📋 Nomi Tabelle GSC",
                value="searchdata_url_impression,searchdata_site_impression",
                help="Tabelle GSC separate da virgola"
            )
            
            if st.button("✅ Applica Configurazione BigQuery", key="apply_bq_config"):
                if all([gcp_project_id, gcp_location, bq_dataset_id, bq_table_names_str]):
                    if setup_gcp_credentials_from_oauth():
                        st.session_state.selected_project_id = gcp_project_id
                        
                        # Carica schema tabelle
                        with st.spinner("Caricando schema tabelle..."):
                            st.session_state.table_schema_for_prompt = get_table_schema_for_prompt(
                                gcp_project_id, bq_dataset_id, bq_table_names_str
                            )
                        
                        if st.session_state.table_schema_for_prompt:
                            st.success("✅ Configurazione BigQuery applicata!")
                            st.session_state.config_applied_successfully = True
                        else:
                            st.error("❌ Errore nel caricamento dello schema")
                    else:
                        st.error("❌ Errore nella configurazione delle credenziali")
                else:
                    st.error("❌ Compila tutti i campi richiesti")
        
        # Opzione per grafici (per entrambe le modalità)
        enable_chart_generation = st.checkbox(
            "📊 Crea grafico con AI",
            value=False,
            key="enable_chart"
        )
        
        if st.session_state.get('config_applied_successfully', False):
            if st.session_state.data_source_mode == "gsc_api":
                st.success("🟢 Configurazione API GSC attiva")
            else:
                st.success("🟢 Configurazione BigQuery attiva")

# --- Area Principale Chat ---
if not st.session_state.get('authenticated', False):
    st.markdown("""
    ## 🔐 Accesso Richiesto
    
    Per utilizzare ChatGSC, devi prima effettuare il login con Google dalla sidebar.
    
    ### Cosa ti serve:
    - Account Google con accesso a Google Search Console
    - Progetto Google Cloud con BigQuery e Vertex AI attivati
    - Dati GSC esportati in BigQuery
    
    ### Permessi richiesti:
    - **Google Search Console**: Lettura dati siti
    - **Google Cloud Platform**: Accesso BigQuery e Vertex AI
    """)

elif not st.session_state.get('config_applied_successfully', False):
    st.markdown("""
    ## ⚙️ Configurazione Richiesta
    
    Completa la configurazione nella sidebar per iniziare a utilizzare ChatGSC.
    """)

else:
    # Chat interface
    with st.form(key='query_form'):
        user_question_input = st.text_area(
            "La tua domanda:", 
            height=100, 
            placeholder="Es. Quante impressioni ho ricevuto la scorsa settimana per le query che contengono 'AI'?",
            key="user_question_text_area" 
        )
        submit_button_main = st.form_submit_button(label="Chiedi a ChatGSC 💬")

    # Domande preimpostate basate sulla modalità
    if st.session_state.data_source_mode == "gsc_api":
        st.write("Oppure prova una di queste domande rapide (API GSC):")
        preset_questions_data = [
            ("Top 10 Query", "Mostrami le top 10 query per numero di clic"),
            ("CTR Migliori", "Quali query hanno il CTR più alto (minimo 100 impressioni)?"),
            ("Query Lunghe", "Mostrami le query con più di 5 parole ordinate per clic"),
            ("Pagine Top", "Quali sono le pagine con più impressioni?"),
            ("Performance Mobile", "Come performano le query su dispositivi mobile vs desktop?"),
            ("Query Branded", "Mostrami le query che contengono il nome del brand"),
            ("Posizioni Basse", "Quali query hanno posizione media sopra 20 ma molte impressioni?"),
            ("Trend CTR", "Qual è il CTR medio per fasce di posizione (1-3, 4-10, 11+)?")
    ]

    cols = st.columns(4)
    for i, (label, question_text) in enumerate(preset_questions_data):
        col_idx = i % 4
        if cols[col_idx].button(label, key=f"preset_q_{i}"):
            user_question_input = question_text
            submit_button_main = True

    # Processamento domanda
    if submit_button_main and user_question_input:
        # Reset risultati precedenti
        st.session_state.sql_query = ""
        st.session_state.query_results = None
        st.session_state.results_summary = ""
        
        # Genera SQL
        with st.spinner(f"🤖💬 Sto generando la query SQL per: \"{user_question_input}\""):
            sql_query = generate_sql_from_question(
                st.session_state.selected_project_id, 
                gcp_location, 
                TARGET_GEMINI_MODEL, 
                user_question_input,
                st.session_state.table_schema_for_prompt, 
                ""
            )

        if sql_query:
            with st.expander("🔍 Dettagli Tecnici", expanded=False):
                st.subheader("Query SQL Generata:")
                st.code(sql_query, language='sql')
            
                # Esegui query
                query_results = execute_bigquery_query(st.session_state.selected_project_id, sql_query)

                if query_results is not None:
                    st.subheader("Risultati Grezzi (Prime 200 righe):")
                    if query_results.empty:
                        st.info("La query non ha restituito risultati.")
                    else:
                        st.dataframe(query_results.head(200))
            
            if query_results is not None and not query_results.empty:
                # Genera riassunto
                with st.spinner("🤖💬 Sto generando un riassunto dei risultati..."):
                    results_summary = summarize_results_with_llm(
                        st.session_state.selected_project_id, 
                        gcp_location, 
                        TARGET_GEMINI_MODEL, 
                        query_results, 
                        user_question_input
                    )
                
                if results_summary and results_summary != "Non ci sono dati da riassumere.":
                    with st.chat_message("ai", avatar="🤖"):
                        st.markdown(results_summary) 
                elif query_results.empty or results_summary == "Non ci sono dati da riassumere.": 
                     st.info("🤖💬 La query non ha restituito risultati da riassumere o non ci sono dati.")
                else: 
                    st.warning("🤖💬 Non è stato possibile generare un riassunto, ma la query ha prodotto risultati (vedi dettagli tecnici).")

                # --- SEZIONE GENERAZIONE GRAFICO ---
                if enable_chart_generation and not query_results.empty:
                    st.markdown("---")
                    st.subheader("📊 Visualizzazione Grafica (Beta)")
                    with st.spinner("🤖💬 Sto generando il codice per il grafico..."):
                        chart_code = generate_chart_code_with_llm(
                            st.session_state.selected_project_id, 
                            gcp_location, 
                            CHART_GENERATION_MODEL,
                            user_question_input, 
                            sql_query, 
                            query_results
                        )
                    
                    if chart_code:
                        try:
                            exec_scope = {
                                "plt": plt, 
                                "pd": pd, 
                                "df": query_results.copy(),
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
                    elif enable_chart_generation:
                        st.warning("🤖💬 Non è stato possibile generare il codice per il grafico.")
                # --- FINE SEZIONE GENERAZIONE GRAFICO ---
        else:
            st.error("Non è stato possibile generare una query SQL per la tua domanda.")

# --- Footer ---
st.markdown("---")
left_footer_col, right_footer_col = st.columns([0.85, 0.15]) 

with left_footer_col:
    st.markdown(
        """
        <div style="text-align: left; padding-top: 10px; padding-bottom: 10px;">
            Made with ❤️ by <a href="https://www.linkedin.com/in/francisco-nardi-212b338b/" target="_blank" style="text-decoration: none; color: inherit;">Francisco Nardi</a>
        </div>
        """,
        unsafe_allow_html=True
    )

with right_footer_col:
    st.markdown("<div style='padding-top: 10px;'></div>", unsafe_allow_html=True) 
    if st.button("Privacy Policy", key="privacy_button_popup_footer", help="Leggi l'informativa sulla privacy"):
        st.session_state.show_privacy_policy = True

# --- Privacy Policy Aggiornata ---
PRIVACY_POLICY_TEXT_OAUTH = """
**Informativa sulla Privacy per ChatGSC**

**Ultimo aggiornamento:** Gennaio 2025

**1. Informazioni che Raccogliamo**

Quando utilizzi ChatGSC con l'autenticazione OAuth 2.0, raccogliamo le seguenti informazioni:

* **Informazioni sull'Account Google:** Quando ti autentichi utilizzando OAuth 2.0 tramite Supabase, riceviamo informazioni di base dal tuo profilo Google necessarie per stabilire una connessione sicura, incluso il tuo indirizzo email. Non memorizziamo la tua password di Google.

* **Token di Accesso OAuth:** Conserviamo temporaneamente i token di accesso OAuth necessari per accedere ai tuoi dati di Google Search Console e Google Cloud Platform durante la sessione.

* **Dati di Google Search Console:** Con il tuo esplicito consenso tramite il flusso OAuth 2.0, l'applicazione accede ai dati del tuo Google Search Console. Questi dati includono metriche di performance del sito web come query di ricerca, clic, impressioni, CTR, posizione media, URL delle pagine, ecc.

* **Interazioni con l'AI:** Le domande che poni all'AI e le risposte generate vengono processate tramite i servizi di Vertex AI di Google Cloud.

**2. Come Utilizziamo le Tue Informazioni**

Utilizziamo le informazioni raccolte per:

* **Fornire il Servizio:** Per autenticarti tramite OAuth 2.0, permetterti di interagire con i tuoi dati di Google Search Console, generare query SQL ed elaborare risposte tramite Vertex AI.
* **Sicurezza:** Per mantenere la sicurezza della tua sessione e proteggere i tuoi dati.
* **Migliorare l'Applicazione:** Per analizzare l'utilizzo e migliorare le funzionalità di ChatGSC.

**3. Condivisione e Divulgazione delle Informazioni**

Non vendiamo né affittiamo le tue informazioni personali a terzi. Potremmo condividere le tue informazioni solo nelle seguenti circostanze:

* **Con i Servizi Google Cloud Platform e Supabase:** Le tue domande e i dati di Search Console vengono processati tramite Google BigQuery, Vertex AI e l'infrastruttura di autenticazione Supabase.
* **Per Requisiti Legali:** Se richiesto dalla legge o in risposta a validi processi legali.
* **Con il Tuo Consenso:** Per qualsiasi altra finalità, solo con il tuo esplicito consenso.

**4. Sicurezza dei Dati**

* **Autenticazione OAuth 2.0:** Utilizziamo il protocollo sicuro OAuth 2.0 tramite Supabase per l'autenticazione. I token di accesso sono gestiti in modo sicuro e utilizzati solo per accedere ai servizi autorizzati.
* **Crittografia:** Tutte le comunicazioni tra l'applicazione e i servizi esterni sono crittografate utilizzando HTTPS.
* **Accesso Limitato:** L'applicazione richiede solo i permessi minimi necessari per funzionare.

**5. Conservazione dei Dati**

* **Token OAuth:** I token di accesso vengono conservati solo per la durata della sessione utente e vengono eliminati al logout.
* **Dati di Search Console:** Non archiviamo copie permanenti dei tuoi dati di Google Search Console. I dati vengono letti "on-demand" per rispondere alle tue domande.
* **Cronologia delle Query:** Le query e i risultati vengono conservati solo durante la sessione attiva.

**6. I Tuoi Diritti**

* **Controllo dell'Accesso:** Puoi revocare in qualsiasi momento l'accesso dell'applicazione ai tuoi dati Google tramite le impostazioni di sicurezza del tuo Account Google.
* **Logout:** Puoi disconnetterti in qualsiasi momento, il che eliminerà i tuoi token di accesso dalla sessione.
* **Cancellazione:** Al logout o alla chiusura della sessione, tutti i dati temporanei vengono eliminati.

**7. Servizi di Terze Parti**

Questa applicazione utilizza:
* **Supabase:** Per l'autenticazione OAuth e la gestione delle sessioni
* **Google Cloud Platform:** Per BigQuery e Vertex AI
* **Google Search Console API:** Per accedere ai tuoi dati GSC

Questi servizi sono soggetti alle proprie informative sulla privacy.

**8. Modifiche a Questa Informativa**

Potremmo aggiornare questa Informativa sulla Privacy di tanto in tanto. Ti informeremo di eventuali modifiche significative pubblicando la nuova Informativa sulla Privacy nell'applicazione.

**9. Contatti**

Per domande su questa Informativa sulla Privacy, contattaci a:
- Email: info@francisconardi
- LinkedIn: Francisco Nardi

---
*Questa informativa è specifica per l'implementazione OAuth 2.0 di ChatGSC e deve essere adattata alle specifiche legali della tua giurisdizione.*
"""

if st.session_state.get('show_privacy_policy', False):
    st.subheader("Informativa sulla Privacy per ChatGSC")
    st.markdown(f"<div style='height: 400px; overflow-y: auto; border: 1px solid #ccc; padding:10px;'>{PRIVACY_POLICY_TEXT_OAUTH.replace('**', '<b>').replace('\n', '<br>')}</div>", unsafe_allow_html=True)
    if st.button("Chiudi Informativa", key="close_privacy_policy_main_area"):
        st.session_state.show_privacy_policy = False
        st.rerun()

# --- Cleanup temporaneo ---
def cleanup_temp_files():
    """Pulisce i file temporanei delle credenziali"""
    if hasattr(st.session_state, 'temp_credentials_file'):
        try:
            if os.path.exists(st.session_state.temp_credentials_file):
                os.remove(st.session_state.temp_credentials_file)
        except:
            pass

# Registra cleanup alla chiusura
atexit.register(cleanup_temp_files)
