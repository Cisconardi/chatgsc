import streamlit as st
import os
import time
import atexit
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Import delle modalità
from gsc_direct import GSCDirectMode
from bigquery_mode import BigQueryMode

# --- Configurazione Pagina Streamlit ---
st.set_page_config(layout="wide", page_title="ChatGSC: Conversa con i dati di Google Search Console")

# --- Stile CSS Globale ---
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

# --- Configurazione Supabase ---
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

# --- Gestione Autenticazione OAuth ---
def handle_oauth_callback():
    """Gestisce il callback OAuth e completa l'autenticazione"""
    query_params = st.query_params
    
    if 'code' in query_params:
        auth_code = query_params['code']
        st.info("🔄 Completamento autenticazione in corso...")
        
        try:
            response = supabase.auth.exchange_code_for_session({
                "auth_code": auth_code
            })
            
            if response.session:
                st.session_state.authenticated = True
                st.session_state.user_email = response.session.user.email if response.session.user else "Unknown"
                st.session_state.access_token = response.session.access_token
                st.session_state.refresh_token = response.session.refresh_token
                
                st.query_params.clear()
                if hasattr(st.session_state, 'auth_url'):
                    del st.session_state.auth_url
                
                st.success("✅ Login completato con successo!")
                time.sleep(1)
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
        redirect_url = "https://chatgsc.streamlit.app"
        
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
        
        return auth_response.url
    except Exception as e:
        st.error(f"Errore durante la generazione dell'URL di login: {e}")
        return None

def check_authentication():
    """Verifica se l'utente è autenticato"""
    session = supabase.auth.get_session()
    
    if session and session.access_token:
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
                   'gsc_sites_data', 'selected_project_id', 'config_applied_successfully',
                   'analysis_mode', 'gsc_config', 'gsc_data']:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()
    except Exception as e:
        st.error(f"Errore durante il logout: {e}")

def refresh_credentials():
    """Aggiorna i token OAuth se necessario"""
    try:
        from google.auth.transport.requests import Request
        
        credentials = Credentials(
            token=st.session_state.access_token,
            refresh_token=st.session_state.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets.get("google_oauth_client_id"),
            client_secret=st.secrets.get("google_oauth_client_secret"),
            scopes=['https://www.googleapis.com/auth/webmasters.readonly', 
                   'https://www.googleapis.com/auth/cloud-platform.read-only']
        )
        
        # Refresh se necessario
        if credentials.expired:
            credentials.refresh(Request())
            # Aggiorna i token in session state
            st.session_state.access_token = credentials.token
            st.session_state.refresh_token = credentials.refresh_token
        
        return credentials
        
    except Exception as e:
        st.error(f"Errore nel refresh delle credenziali: {e}")
        # Forza re-login
        st.session_state.authenticated = False
        st.rerun()
        return None

def get_gsc_sites():
    """Recupera i siti disponibili da Google Search Console"""
    if not st.session_state.get('authenticated', False):
        return []
    
    try:
        # Ottieni credenziali aggiornate
        credentials = refresh_credentials()
        if not credentials:
            return []
        
        service = build('searchconsole', 'v1', credentials=credentials)
        sites_response = service.sites().list().execute()
        sites = sites_response.get('siteEntry', [])
        
        return [{'url': site['siteUrl'], 'permission': site['permissionLevel']} for site in sites]
        
    except Exception as e:
        error_msg = str(e)
        if 'invalid_grant' in error_msg or 'Bad Request' in error_msg:
            st.error("🔑 Sessione scaduta. Per favore, effettua nuovamente il login.")
            st.session_state.authenticated = False
            if st.button("🔄 Ricarica Pagina", key="reload_after_token_error"):
                st.rerun()
        else:
            st.error(f"Errore nel recupero dei siti GSC: {e}")
        return []

# --- Inizializzazione Session State ---
def init_session_state():
    """Inizializza tutte le variabili di sessione"""
    defaults = {
        'authenticated': False,
        'user_email': "",
        'gsc_sites_data': [],
        'selected_site': "",
        'selected_project_id': "",
        'config_applied_successfully': False,
        'table_schema_for_prompt': "",
        'analysis_mode': "🔍 Google Search Console Diretto",
        'gsc_config': None,
        'gsc_data': None,
        'enable_chart_generation': False
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# --- Cleanup File Temporanei ---
def cleanup_temp_files():
    """Pulisce i file temporanei delle credenziali"""
    if hasattr(st.session_state, 'temp_credentials_file'):
        try:
            if os.path.exists(st.session_state.temp_credentials_file):
                os.remove(st.session_state.temp_credentials_file)
        except:
            pass

atexit.register(cleanup_temp_files)

# --- Privacy Policy ---
PRIVACY_POLICY_TEXT = """
**Informativa sulla Privacy per ChatGSC**

**Ultimo aggiornamento:** Gennaio 2025

Questa applicazione utilizza l'autenticazione OAuth 2.0 tramite Supabase per accedere ai tuoi dati di Google Search Console.

**Dati Raccolti:**
- Informazioni di base del profilo Google (email)
- Token di accesso OAuth temporanei
- Dati di Google Search Console (solo durante le sessioni attive)

**Utilizzo:**
- Autenticazione sicura tramite OAuth 2.0
- Analisi dati GSC tramite AI
- Generazione di insight e visualizzazioni

**Sicurezza:**
- I token vengono conservati solo durante la sessione
- Nessun dato permanente viene salvato
- Comunicazioni crittografate HTTPS

**I Tuoi Diritti:**
- Puoi disconnetterti in qualsiasi momento
- Puoi revocare l'accesso dalle impostazioni Google
- Tutti i dati temporanei vengono eliminati al logout

Per domande: info@francisconardi
"""

# --- MAIN APP ---
def main():
    """Funzione principale dell'applicazione"""
    
    # Inizializza session state
    init_session_state()
    
    # Header
    st.title("Ciao, sono ChatGSC 🤖💬")
    st.caption("Fammi una domanda sui tuoi dati di Google Search Console. La mia AI la tradurrà e ti risponderò!")

    # Gestione callback OAuth
    handle_oauth_callback()

    # Controllo autenticazione
    if not check_authentication():
        st.session_state.authenticated = False

    # Sidebar per autenticazione e configurazione
    with st.sidebar:
        st.header("🔐 Autenticazione")
        
        if not st.session_state.get('authenticated', False):
            # Sezione login
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
            
            # Mostra link di redirect se disponibile
            if hasattr(st.session_state, 'auth_url') and st.session_state.auth_url:
                st.markdown("### 🔗 Completa il Login")
                st.link_button(
                    "🚀 Vai a Google per Autenticarti", 
                    st.session_state.auth_url,
                    help="Clicca per completare l'autenticazione OAuth"
                )
                st.info("👆 Clicca il pulsante sopra per completare il login OAuth")
                
                if st.button("🔄 Genera Nuovo Link", key="reset_auth_link"):
                    if hasattr(st.session_state, 'auth_url'):
                        del st.session_state.auth_url
                    st.rerun()
            
            st.markdown("---")
            st.subheader("ℹ️ Come funziona")
            st.write("1. **Login OAuth**: Accedi con Google")
            st.write("2. **Permessi**: Autorizza l'accesso a GSC e GCP")
            st.write("3. **Configurazione**: Seleziona modalità e parametri")
            st.write("4. **Chat**: Fai domande sui tuoi dati!")
            
        else:
            # Utente autenticato
            st.markdown(f"""
            <div class="user-info">
                <h4>👤 Utente Connesso</h4>
                <p><strong>Email:</strong> {st.session_state.user_email}</p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🚪 Logout", key="logout_button"):
                logout()
            
            st.markdown("---")
            
            # Selezione modalità
            st.subheader("⚙️ Modalità di Analisi")
            analysis_mode = st.radio(
                "Scegli come analizzare i dati:",
                ["🔍 Google Search Console Diretto", "📊 BigQuery (Avanzato)"],
                key="analysis_mode_selector",
                help="GSC Diretto: Più semplice, dati in tempo reale\nBigQuery: Più potente, richiede export GSC → BQ"
            )
            
            st.session_state.analysis_mode = analysis_mode
            
            # Opzione grafici
            st.markdown("---")
            enable_chart_generation = st.checkbox(
                "📊 Crea grafico con AI",
                value=False,
                key="enable_chart"
            )
            st.session_state.enable_chart_generation = enable_chart_generation

    # Area principale
    if not st.session_state.get('authenticated', False):
        # Schermata di benvenuto per utenti non autenticati
        st.markdown("""
        ## 🔐 Accesso Richiesto
        
        Per utilizzare ChatGSC, devi prima effettuare il login con Google dalla sidebar.
        
        ### Cosa ti serve:
        - Account Google con accesso a Google Search Console
        - Per BigQuery: Progetto Google Cloud con BigQuery e Vertex AI attivati
        
        ### Permessi richiesti:
        - **Google Search Console**: Lettura dati siti
        - **Google Cloud Platform**: Accesso BigQuery e Vertex AI (solo per modalità avanzata)
        """)

    else:
        # Utente autenticato - mostra la modalità appropriata
        current_mode = st.session_state.get('analysis_mode', '🔍 Google Search Console Diretto')
        
        if current_mode == "🔍 Google Search Console Diretto":
            # Carica modalità GSC Diretta
            gsc_mode = GSCDirectMode(st.session_state, get_gsc_sites)
            gsc_mode.render()
            
        else:
            # Carica modalità BigQuery
            bq_mode = BigQueryMode(st.session_state)
            bq_mode.render()

    # Footer
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
        if st.button("Privacy Policy", key="privacy_button", help="Leggi l'informativa sulla privacy"):
            st.session_state.show_privacy_policy = True

    # Privacy Policy
    if st.session_state.get('show_privacy_policy', False):
        st.subheader("Informativa sulla Privacy per ChatGSC")
        st.markdown(f"<div style='height: 400px; overflow-y: auto; border: 1px solid #ccc; padding:10px;'>{PRIVACY_POLICY_TEXT.replace('**', '<b>').replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
        if st.button("Chiudi Informativa", key="close_privacy_policy"):
            st.session_state.show_privacy_policy = False
            st.rerun()

if __name__ == "__main__":
    main()
