import streamlit as st
import os
import time
import atexit
import requests
import json
from urllib.parse import urlencode, urlparse, parse_qs
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Import delle modalità
from gsc_direct import GSCDirectMode
from bigquery_mode import BigQueryMode

# --- Helper per compatibilità query params ---
def get_query_params() -> dict:
    """Ritorna i query params compatibilmente con le vecchie versioni di Streamlit."""
    if hasattr(st, "query_params"):
        return st.query_params
    return st.experimental_get_query_params()

def clear_query_params() -> None:
    """Pulisce i query params in modo compatibile."""
    if hasattr(st, "query_params"):
        st.query_params.clear()
    else:
        st.experimental_set_query_params()

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

# URL dell'applicazione per i redirect OAuth
APP_URL = st.secrets.get("app_url", "https://chatgsc.streamlit.app")

# Inizializza client Supabase
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase: Client = init_supabase()

# --- Gestione Autenticazione OAuth ---
def setup_service_account(uploaded_file):
    """Configura l'autenticazione usando Service Account"""
    try:
        # Leggi il file JSON
        service_account_info = json.loads(uploaded_file.getvalue().decode('utf-8'))
        
        # Verifica che sia un Service Account valido
        if 'type' not in service_account_info or service_account_info['type'] != 'service_account':
            st.error("❌ Il file caricato non è un Service Account valido")
            return
        
        # Salva temporaneamente le credenziali
        import tempfile
        import json
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        json.dump(service_account_info, temp_file)
        temp_file.close()
        
        # Configura le credenziali
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_file.name
        st.session_state.temp_credentials_file = temp_file.name
        
        # Test immediato
        try:
            from google.oauth2 import service_account
            
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/webmasters.readonly']
            )
            
            service = build('searchconsole', 'v1', credentials=credentials)
            sites_response = service.sites().list().execute()
            sites = sites_response.get('siteEntry', [])
            
            if sites:
                st.success(f"🎉 Service Account configurato! Trovati {len(sites)} siti GSC.")
                st.success(f"📧 Service Account email: {service_account_info.get('client_email')}")
                
                # Salva lo stato
                st.session_state.authenticated = True
                st.session_state.credentials_verified = True
                st.session_state.user_email = service_account_info.get('client_email')
                st.session_state.auth_method = 'service_account'
                
                # Lista siti trovati
                st.markdown("**Siti GSC accessibili:**")
                for site in sites:
                    st.markdown(f"- {site['siteUrl']} ({site['permissionLevel']})")
                
                st.rerun()
                
            else:
                st.warning("⚠️ Service Account configurato ma nessun sito GSC accessibile.")
                st.info("💡 Aggiungi il Service Account come utente nelle proprietà GSC che vuoi analizzare.")
                
        except Exception as e:
            st.error(f"❌ Errore nel test Service Account: {e}")
            st.info("Verifica che il Service Account sia stato aggiunto come utente in Google Search Console.")
            
    except Exception as e:
        st.error(f"❌ Errore nel setup Service Account: {e}")

def test_manual_credentials(client_id, client_secret, access_token):
    """Testa credenziali inserite manualmente"""
    try:
        from google.oauth2.credentials import Credentials
        
        credentials = Credentials(
            token=access_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=['https://www.googleapis.com/auth/webmasters.readonly']
        )
        
        service = build('searchconsole', 'v1', credentials=credentials)
        response = service.sites().list().execute()
        
        sites = response.get('siteEntry', [])
        st.success(f"✅ Credenziali manuali OK! Trovati {len(sites)} siti GSC.")
        
        # Salva le credenziali funzionanti
        st.session_state.access_token = access_token
        st.session_state.authenticated = True
        st.session_state.credentials_verified = True
        
        return True
        
    except Exception as e:
        st.error(f"❌ Test credenziali manuali fallito: {e}")
        return False

def extract_and_use_code(return_url):
    """Estrae il codice OAuth dall'URL di ritorno e lo scambia con i token"""
    try:
        from urllib.parse import urlparse, parse_qs
        
        # Estrai il code dall'URL
        parsed = urlparse(return_url)
        query_params = parse_qs(parsed.query)
        
        if 'code' not in query_params:
            st.error("❌ Nessun codice di autorizzazione trovato nell'URL")
            return False
            
        auth_code = query_params['code'][0]
        st.info(f"🔍 Codice estratto: {auth_code[:20]}...")
        
        # Scambia il codice con i token
        token_url = "https://oauth2.googleapis.com/token"
        
        data = {
            'client_id': st.secrets.get("google_oauth_client_id"),
            'client_secret': st.secrets.get("google_oauth_client_secret"),
            'code': auth_code,
            'grant_type': 'authorization_code',
            'redirect_uri': APP_URL
        }
        
        response = requests.post(token_url, data=data)
        
        if response.status_code == 200:
            tokens = response.json()
            
            st.success("✅ Scambio codice → token completato!")
            st.json(tokens)  # Mostra i token per debug
            
            # Salva i token
            st.session_state.access_token = tokens.get('access_token')
            st.session_state.refresh_token = tokens.get('refresh_token')
            st.session_state.authenticated = True
            
            # Test immediato
            if test_google_credentials():
                st.success("🎉 Credenziali Google funzionanti! GSC accessibile.")
                st.session_state.credentials_verified = True
                st.rerun()
            else:
                st.error("❌ Token ottenuti ma GSC non accessibile")
                
        else:
            st.error(f"❌ Errore scambio token: {response.status_code}")
            st.code(response.text)
            
    except Exception as e:
        st.error(f"❌ Errore nell'estrazione del codice: {e}")

def exchange_direct_oauth_code(auth_code):
    """Scambia il codice OAuth direttamente con Google per ottenere i token"""
    try:
        token_url = "https://oauth2.googleapis.com/token"
        
        data = {
            'client_id': st.secrets.get("google_oauth_client_id"),
            'client_secret': st.secrets.get("google_oauth_client_secret"),
            'code': auth_code,
            'grant_type': 'authorization_code',
            'redirect_uri': APP_URL
        }
        
        response = requests.post(token_url, data=data)
        
        if response.status_code == 200:
            tokens = response.json()
            
            # Salva i token Google
            st.session_state.access_token = tokens.get('access_token')
            st.session_state.refresh_token = tokens.get('refresh_token')
            st.session_state.authenticated = True
            
            # Test credenziali
            if test_google_credentials():
                st.success("✅ OAuth diretto completato! Credenziali Google funzionanti.")
                st.session_state.credentials_verified = True
                st.rerun()
            else:
                st.error("❌ Token ottenuti ma test GSC fallito")
        else:
            st.error(f"❌ Errore nello scambio del codice: {response.status_code} - {response.text}")
            
    except Exception as e:
        st.error(f"❌ Errore nello scambio OAuth diretto: {e}")

def get_google_provider_token():
    """Ottiene il token Google direttamente dal provider Supabase"""
    try:
        # Ottieni la sessione corrente
        session = supabase.auth.get_session()
        if not session:
            return None, None
            
        # Usa l'API Supabase per ottenere i provider tokens
        headers = {
            'apikey': SUPABASE_ANON_KEY,
            'Authorization': f'Bearer {session.access_token}',
            'Content-Type': 'application/json'
        }
        
        # Endpoint per ottenere i provider tokens (non sempre disponibile pubblicamente)
        response = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers=headers
        )
        
        if response.status_code == 200:
            user_data = response.json()
            
            # Cerca nelle identities il provider Google
            identities = user_data.get('identities', [])
            for identity in identities:
                if identity.get('provider') == 'google':
                    # Cerca i token nel metadata o nell'identity
                    provider_token = identity.get('access_token')
                    provider_refresh_token = identity.get('refresh_token')
                    
                    if provider_token:
                        return provider_token, provider_refresh_token
        
        return None, None
        
    except Exception as e:
        st.error(f"Errore nell'ottenere i token Google: {e}")
        return None, None

def handle_oauth_callback():
    """Gestisce il callback OAuth e completa l'autenticazione"""
    query_params = get_query_params()
    
    if 'code' in query_params:
        auth_code = query_params['code']
        st.info("🔄 Completamento autenticazione in corso...")
        
        try:
            response = supabase.auth.exchange_code_for_session({
                "auth_code": auth_code
            })
            
            if response.session and response.session.access_token:
                # Salva dati di sessione base
                st.session_state.authenticated = True
                st.session_state.user_email = response.session.user.email if response.session.user else "Unknown"
                st.session_state.supabase_token = response.session.access_token
                
                # Prova a ottenere i token Google specifici
                google_token, google_refresh = get_google_provider_token()
                
                if google_token:
                    st.session_state.access_token = google_token
                    st.session_state.refresh_token = google_refresh
                    st.success("✅ Token Google ottenuti correttamente!")
                else:
                    # Fallback ai token Supabase
                    st.session_state.access_token = response.session.access_token
                    st.session_state.refresh_token = response.session.refresh_token
                    st.warning("⚠️ Usando token Supabase come fallback")
                
                # Test credenziali
                test_success = test_google_credentials()
                
                # Pulisci URL e stato
                clear_query_params()
                if hasattr(st.session_state, 'auth_url'):
                    del st.session_state.auth_url
                
                if test_success:
                    st.success("✅ Login e verifica credenziali Google completati!")
                    st.session_state.credentials_verified = True
                else:
                    st.warning("⚠️ Login completato ma credenziali Google non funzionano")
                    st.session_state.credentials_verified = False
                
                time.sleep(1)
                st.rerun()
            else:
                st.error("❌ Errore durante il completamento del login: Sessione non valida")
                clear_query_params()
                
        except Exception as e:
            st.error(f"❌ Errore nel callback OAuth: {e}")
            # In caso di errore, pulisci tutto
            clear_query_params()
            st.session_state.authenticated = False
            if hasattr(st.session_state, 'auth_url'):
                del st.session_state.auth_url
    
    elif 'error' in query_params:
        error_description = query_params.get('error_description', 'Errore sconosciuto')
        st.error(f"❌ Errore di autenticazione: {error_description}")
        clear_query_params()
        if hasattr(st.session_state, 'auth_url'):
            del st.session_state.auth_url

def test_google_credentials():
    """Testa se le credenziali Google funzionano"""
    try:
        credentials = Credentials(
            token=st.session_state.access_token,
            refresh_token=st.session_state.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets.get("google_oauth_client_id"),
            client_secret=st.secrets.get("google_oauth_client_secret"),
            scopes=['https://www.googleapis.com/auth/webmasters.readonly']
        )
        
        service = build('searchconsole', 'v1', credentials=credentials)
        test_response = service.sites().list().execute()
        return True
        
    except Exception as e:
        st.error(f"Test credenziali Google fallito: {e}")
        return False

def handle_oauth_login():
    """Gestisce il login OAuth con Google tramite Supabase"""
    try:
        redirect_url = APP_URL
        
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
        # Verifica se stiamo usando Service Account
        if st.session_state.get('auth_method') == 'service_account':
            # Usa Service Account credentials
            if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                from google.oauth2 import service_account
                
                credentials = service_account.Credentials.from_service_account_file(
                    os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
                    scopes=['https://www.googleapis.com/auth/webmasters.readonly']
                )
                
                service = build('searchconsole', 'v1', credentials=credentials)
                sites_response = service.sites().list().execute()
                sites = sites_response.get('siteEntry', [])
                
                return [{'url': site['siteUrl'], 'permission': site['permissionLevel']} for site in sites]
        
        # Altrimenti usa OAuth (codice esistente)
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
            st.info("1. Usa 'Service Account' (soluzione definitiva)")
            st.info("2. Clicca 'Diagnostica Completa OAuth'")
            st.info("3. Prova 'OAuth Manuale'")
            
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
        'auth_method': 'oauth',  # 'oauth' o 'service_account'
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
                
                Il problema può essere dovuto a:
                
                **1. Configurazione Supabase → Google:**
                - Authentication → Providers → Google
                - Assicurati che "Enable Google provider" sia ON
                - Verifica Client ID e Client Secret corretti
                - Copia il "Callback URL" e aggiungilo in Google Cloud Console
                
                **2. Google Cloud Console:**
                - API & Services → Credentials
                - OAuth 2.0 Client deve avere Supabase callback URL
                - Google Search Console API deve essere abilitata
                
                **3. Provider Token Access:**
                - Supabase potrebbe non esporre i token Google
                - In questo caso, usa "OAuth Diretto Google" sopra
                
                **4. Scope OAuth in Supabase:**
                ```
                openid email profile https://www.googleapis.com/auth/webmasters.readonly
                ```
                """)
            
            
        else:
            # Utente autenticato
            auth_method = st.session_state.get('auth_method', 'oauth')
            auth_method_display = "🔐 Service Account" if auth_method == 'service_account' else "🔑 OAuth"
            
            st.markdown(f"""
            <div class="user-info">
                <h4>👤 Utente Connesso</h4>
                <p><strong>Email:</strong> {st.session_state.user_email}</p>
                <p><strong>Metodo:</strong> {auth_method_display}</p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🚪 Logout", key="logout_button"):
                logout()
            
            # Diagnostica completa OAuth
            if st.button("🔬 Diagnostica Completa OAuth", key="full_diagnostic"):
                st.markdown("### 🔍 Diagnosi Dettagliata del Problema OAuth")
                
                with st.expander("📋 Checklist Configurazione", expanded=True):
                    st.markdown("**Verifica questi punti in ordine:**")
                    
                    st.markdown("**1. Google Cloud Console - API & Services → Credentials:**")
                    st.code(f"""
Client ID attuale: {st.secrets.get('google_oauth_client_id', 'NON CONFIGURATO')}
""")
                    st.markdown("✅ Deve corrispondere esattamente al Client ID nel tuo progetto Google")
                    
                    st.markdown("**2. Authorized redirect URIs nel Google Cloud Console:**")
                    st.markdown("Questi URI DEVONO essere configurati:")
                    st.code(f"""
{APP_URL}
https://yitqdfdkeljllaplfgar.supabase.co/auth/v1/callback
""")
                    
                    st.markdown("**3. API abilitate in Google Cloud Console:**")
                    st.markdown("- ✅ Google Search Console API")
                    st.markdown("- ✅ Google+ API (legacy, ma a volte necessaria)")
                    
                    st.markdown("**4. Configurazione Supabase:**")
                    st.markdown("Dashboard → Authentication → Providers → Google:")
                    st.code(f"""
Client ID: {st.secrets.get('google_oauth_client_id', 'NON CONFIGURATO')}
Client Secret: {'CONFIGURATO' if st.secrets.get('google_oauth_client_secret') else 'NON CONFIGURATO'}
Additional Scopes: openid email profile https://www.googleapis.com/auth/webmasters.readonly
""")
                
                with st.expander("🛠️ Test Manuale Credenziali", expanded=False):
                    st.markdown("**Testa le tue credenziali manualmente:**")
                    
                    manual_client_id = st.text_input("Inserisci Google Client ID:", key="manual_client_id")
                    manual_client_secret = st.text_input("Inserisci Google Client Secret:", type="password", key="manual_client_secret")
                    manual_access_token = st.text_input("Inserisci Access Token (se disponibile):", key="manual_access_token")
                    
                    if st.button("🧪 Testa Credenziali Manuali", key="test_manual_creds"):
                        if manual_client_id and manual_client_secret and manual_access_token:
                            test_manual_credentials(manual_client_id, manual_client_secret, manual_access_token)
                        else:
                            st.warning("Compila tutti i campi per il test")
            
            # Metodo alternativo: Generazione URL manuale
            if st.button("🔧 Genera URL OAuth Manuale", key="manual_oauth_url"):
                st.markdown("### 🔗 OAuth Manuale - Procedura Step by Step")
                
                # URL OAuth pulito
                base_url = "https://accounts.google.com/o/oauth2/v2/auth"
                client_id = st.secrets.get("google_oauth_client_id")
                
                params = {
                    'client_id': client_id,
                    'redirect_uri': APP_URL,
                    'scope': 'https://www.googleapis.com/auth/webmasters.readonly',
                    'response_type': 'code',
                    'access_type': 'offline',
                    'prompt': 'consent',
                    'include_granted_scopes': 'true'
                }
                
                manual_url = f"{base_url}?{urlencode(params)}"
                
                st.markdown("**Procedura:**")
                st.markdown("1. 🔗 Clicca il link qui sotto")
                st.markdown("2. 🔐 Autorizza l'accesso a Google Search Console")
                st.markdown("3. 📋 Copia TUTTO l'URL della pagina di ritorno")
                st.markdown("4. 📝 Incollalo nel campo sottostante")
                
                st.link_button("🚀 Autorizza con Google (Manuale)", manual_url)
                
                return_url = st.text_area(
                    "Incolla qui l'URL completo della pagina di ritorno:",
                    placeholder=f"{APP_URL}?code=4/0AcvDMrA...",
                    key="return_url_manual"
                )
                
                if st.button("🔄 Estrai e Usa Codice", key="extract_code") and return_url:
                    extract_and_use_code(return_url)
            
            # Soluzione Service Account (alternativa robusta)
            if st.button("🔐 Usa Service Account (Soluzione Definitiva)", key="service_account_option"):
                st.markdown("### 🎯 Soluzione Service Account - 100% Affidabile")
                
                st.markdown("""
                **Perché Service Account?**
                - ✅ Nessun token scaduto
                - ✅ Nessun problema OAuth
                - ✅ Perfetto per applicazioni server-side
                - ✅ Configurazione una volta sola
                """)
                
                st.markdown("**Setup richiesto:**")
                st.markdown("1. 🔧 Google Cloud Console → API & Services → Credentials")
                st.markdown("2. 📋 Create Credentials → Service Account")
                st.markdown("3. 🔑 Crea chiave JSON per il Service Account")
                st.markdown("4. 🌐 Aggiungi il Service Account in Google Search Console:")
                st.markdown("   - Vai alle tue proprietà GSC")
                st.markdown("   - Settings → Users and permissions")
                st.markdown("   - Add user → Inserisci l'email del Service Account")
                st.markdown("   - Permessi: Owner o Full")
                
                uploaded_sa_file = st.file_uploader(
                    "Carica il file JSON del Service Account:",
                    type="json",
                    key="service_account_file"
                )
                
                if uploaded_sa_file:
                    if st.button("🚀 Configura Service Account", key="setup_service_account"):
                        setup_service_account(uploaded_sa_file)
                
                st.markdown("**Vantaggi:**")
                st.markdown("- 🔒 Autenticazione permanente")
                st.markdown("- ⚡ Nessun login richiesto")
                st.markdown("- 🎯 Accesso diretto alle API Google")
                st.markdown("- 💯 Risolve definitivamente 'invalid_grant'")
                
                st.info("💡 **Nota**: Il Service Account deve essere aggiunto come utente in Google Search Console per ogni proprietà che vuoi analizzare.")
            
            # Pulsante per approccio OAuth diretto
            if st.button("🌐 Prova OAuth Diretto Google", key="direct_oauth"):
                st.info("🔧 **OAuth Diretto**: Questa opzione bypassa Supabase e usa OAuth Google diretto")
                
                # Genera URL OAuth diretto
                google_oauth_url = "https://accounts.google.com/o/oauth2/v2/auth"
                params = {
                    'client_id': st.secrets.get("google_oauth_client_id"),
                    'redirect_uri': APP_URL,
                    'scope': 'openid email profile https://www.googleapis.com/auth/webmasters.readonly',
                    'response_type': 'code',
                    'access_type': 'offline',
                    'prompt': 'consent'
                }
                
                direct_oauth_url = f"{google_oauth_url}?{urlencode(params)}"
                
                st.markdown("**Istruzioni:**")
                st.markdown("1. Clicca il link sotto")
                st.markdown("2. Autorizza l'accesso a Google Search Console")
                st.markdown("3. Copia il 'code' dall'URL di ritorno")
                st.markdown("4. Incollalo nel campo qui sotto")
                
                st.link_button("🚀 Vai a Google OAuth", direct_oauth_url)
                
                auth_code_input = st.text_input("Incolla il codice di autorizzazione qui:", key="manual_auth_code")
                
                if st.button("🔑 Scambia Codice con Token", key="exchange_code") and auth_code_input:
                    exchange_direct_oauth_code(auth_code_input)
            
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
