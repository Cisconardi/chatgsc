import streamlit as st
import os
import time
import atexit
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
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
            
            if response.session and response.session.access_token:
                # Salva dati di sessione
                st.session_state.authenticated = True
                st.session_state.user_email = response.session.user.email if response.session.user else "Unknown"
                
                # Ottieni provider token da Supabase
                try:
                    # Cerca il provider token Google nelle identities
                    google_identity = None
                    if response.session.user and response.session.user.identities:
                        for identity in response.session.user.identities:
                            if identity.provider == 'google':
                                google_identity = identity
                                break
                    
                    if google_identity and hasattr(google_identity, 'access_token'):
                        # Usa il token Google direttamente
                        st.session_state.access_token = google_identity.access_token
                        st.session_state.refresh_token = google_identity.refresh_token if hasattr(google_identity, 'refresh_token') else None
                    else:
                        # Fallback: usa il token Supabase (potrebbe non funzionare per Google APIs)
                        st.session_state.access_token = response.session.access_token
                        st.session_state.refresh_token = response.session.refresh_token
                        st.warning("⚠️ Usando token Supabase - potrebbe essere necessario riconfigurare l'OAuth")
                
                except Exception as token_error:
                    st.error(f"Errore nell'estrazione dei token Google: {token_error}")
                    # Usa i token Supabase come fallback
                    st.session_state.access_token = response.session.access_token
                    st.session_state.refresh_token = response.session.refresh_token
                
                # Test credenziali
                test_success = False
                try:
                    credentials = Credentials(
                        token=st.session_state.access_token,
                        refresh_token=st.session_state.refresh_token,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=st.secrets.get("google_oauth_client_id"),
                        client_secret=st.secrets.get("google_oauth_client_secret"),
                        scopes=['https://www.googleapis.com/auth/webmasters.readonly']
                    )
                    
                    # Test rapido
                    service = build('searchconsole', 'v1', credentials=credentials)
                    test_response = service.sites().list().execute()
                    test_success = True
                    st.session_state.credentials_verified = True
                    
                except Exception as cred_error:
                    st.session_state.credentials_verified = False
                    st.error(f"❌ Test credenziali fallito: {cred_error}")
                
                # Pulisci URL e stato
                st.query_params.clear()
                if hasattr(st.session_state, 'auth_url'):
                    del st.session_state.auth_url
                
                if test_success:
                    st.success("✅ Login e verifica credenziali completati!")
                else:
                    st.warning("⚠️ Login completato ma credenziali Google non verificate")
                
                time.sleep(1)
                st.rerun()
            else:
                st.error("❌ Errore durante il completamento del login: Sessione non valida")
                st.query_params.clear()
                
        except Exception as e:
            st.error(f"❌ Errore nel callback OAuth: {e}")
            # In caso di errore, pulisci tutto
            st.query_params.clear()
            st.session_state.authenticated = False
            if hasattr(st.session_state, 'auth_url'):
                del st.session_state.auth_url
    
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
                "scopes": "openid email profile https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/cloud-platform.read-only",
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
    # Prima controlla se abbiamo dati di sessione locali
    if st.session_state.get('authenticated', False) and st.session_state.get('access_token'):
        return True
    
    # Poi controlla la sessione Supabase
    try:
        session = supabase.auth.get_session()
        
        if session and session.access_token:
            st.session_state.authenticated = True
            st.session_state.user_email = session.user.email if session.user else "Unknown"
            st.session_state.access_token = session.access_token
            st.session_state.refresh_token = session.refresh_token
            return True
    except Exception as e:
        # Se c'è un errore nel recupero della sessione, considera non autenticato
        st.session_state.authenticated = False
    
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
        # Diagnostica dettagliata
        if not st.session_state.get('access_token'):
            st.error("❌ Access token mancante")
            return []
        
        # Ottieni credenziali aggiornate
        credentials = refresh_credentials()
        if not credentials:
            return []
        
        # Debug delle credenziali
        st.info(f"🔍 Debug: Token valido: {credentials.valid}, Scaduto: {credentials.expired}")
        
        service = build('searchconsole', 'v1', credentials=credentials)
        sites_response = service.sites().list().execute()
        sites = sites_response.get('siteEntry', [])
        
        st.success(f"✅ API GSC risposta OK: {len(sites)} siti trovati")
        
        return [{'url': site['siteUrl'], 'permission': site['permissionLevel']} for site in sites]
        
    except Exception as e:
        error_msg = str(e)
        st.error(f"❌ Errore dettagliato: {error_msg}")
        
        if 'invalid_grant' in error_msg or 'Bad Request' in error_msg:
            st.error("🔑 **Diagnosi**: Token Google non validi o scaduti")
            st.info("**Soluzioni possibili:**")
            st.info("1. Clicca 'Forza Re-autenticazione' nella sidebar")
            st.info("2. Verifica configurazione OAuth in Supabase")
            st.info("3. Controlla che l'app abbia i permessi GSC")
            
            st.session_state.authenticated = False
            if st.button("🔄 Vai al Login", key="gsc_login_redirect"):
                st.rerun()
        elif 'insufficient authentication scopes' in error_msg.lower():
            st.error("🔐 **Diagnosi**: Scope OAuth insufficienti")
            st.info("L'app non ha i permessi per accedere a Google Search Console")
        elif 'quotaExceeded' in error_msg:
            st.warning("⚠️ **Diagnosi**: Quota API superata, riprova più tardi")
        else:
            st.error("🔧 **Diagnosi**: Errore generico delle API Google")
            
        return []

# --- Inizializzazione Session State ---
def init_session_state():
    """Inizializza tutte le variabili di sessione"""
    defaults = {
        'authenticated': False,
        'user_email': "",
        'access_token': None,
        'refresh_token': None,
        'credentials_verified': False,
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
            
            # Istruzioni per problemi comuni
            with st.expander("🔧 Risoluzione Problemi", expanded=False):
                st.markdown("""
                **Se vedi "Sessione scaduta" o "invalid_grant":**
                
                1. **Verifica Supabase Dashboard:**
                   - Authentication → Providers → Google
                   - Assicurati che "Enable Google provider" sia ON
                   - Copia il "Callback URL" mostrato
                
                2. **Verifica Google Cloud Console:**
                   - API & Services → Credentials
                   - Il tuo OAuth 2.0 Client deve avere:
                   - Authorized redirect URIs con l'URL di Supabase
                   - Google Search Console API abilitata
                
                3. **Scope Richiesti in Supabase:**
                   - `openid email profile`
                   - `https://www.googleapis.com/auth/webmasters.readonly`
                
                4. **Se persiste il problema:**
                   - Clicca "Forza Re-autenticazione" sopra
                   - Controlla che l'account Google abbia accesso a GSC
                """)
            
            
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
            
            # Test credenziali per debug
            if st.button("🔍 Testa Credenziali GSC", key="test_credentials"):
                with st.spinner("Testando credenziali..."):
                    # Debug info
                    st.write("**Debug Info:**")
                    st.write(f"- Access token presente: {bool(st.session_state.get('access_token'))}")
                    st.write(f"- Refresh token presente: {bool(st.session_state.get('refresh_token'))}")
                    
                    test_sites = get_gsc_sites()
                    if test_sites:
                        st.success(f"✅ Credenziali OK! Trovati {len(test_sites)} siti.")
                        st.session_state.credentials_verified = True
                    else:
                        st.error("❌ Problema con le credenziali.")
                        st.session_state.credentials_verified = False
            
            # Pulsante per re-autenticazione forzata
            if st.button("🔄 Forza Re-autenticazione", key="force_reauth"):
                st.session_state.authenticated = False
                st.session_state.access_token = None
                st.session_state.refresh_token = None
                st.session_state.credentials_verified = False
                try:
                    supabase.auth.sign_out()
                except:
                    pass
                st.info("Effettua nuovamente il login per risolvere i problemi di credenziali.")
                st.rerun()
            
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
