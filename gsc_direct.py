import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import openai

class GSCDirectMode:
    """Classe per gestire la modalità Google Search Console Diretta"""
    
    def __init__(self, session_state, get_gsc_sites_func):
        self.session_state = session_state
        self.get_gsc_sites = get_gsc_sites_func

        self.OPENAI_MODEL = "o4-mini"
        self.openai_api_key = st.secrets.get("openai_api_key", None)
        if self.openai_api_key:
            # Create an OpenAI client using the new 1.x interface
            self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
        else:
            self.openai_client = None

    def _get_fixed_range(self, option: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Restituisce la coppia (start, end) per un intervallo predefinito."""
        end = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
        if option == "Ultimi 28 giorni":
            start = end - pd.Timedelta(days=27)
        elif option == "Ultimi 3 mesi":
            start = end - pd.DateOffset(months=3) + pd.Timedelta(days=1)
        elif option == "Ultimi 6 mesi":
            start = end - pd.DateOffset(months=6) + pd.Timedelta(days=1)
        elif option == "Ultimi 12 mesi":
            start = end - pd.DateOffset(months=12) + pd.Timedelta(days=1)
        elif option == "Ultimi 16 mesi":
            start = end - pd.DateOffset(months=16) + pd.Timedelta(days=1)
        else:  # personalizzato
            start = end - pd.Timedelta(days=30)
        return start, end

    def _get_compare_ranges(self, option: str) -> tuple[tuple[str, str], tuple[str, str]]:
        """Determina le date per la modalità confronto."""
        end = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
        if option == "MoM 28gg":
            start = end - pd.Timedelta(days=27)
            prev_end = start - pd.Timedelta(days=1)
            prev_start = prev_end - pd.Timedelta(days=27)
        elif option == "MoM 3 mesi":
            start = end - pd.DateOffset(months=3) + pd.Timedelta(days=1)
            prev_end = start - pd.Timedelta(days=1)
            prev_start = prev_end - pd.DateOffset(months=3) + pd.Timedelta(days=1)
        elif option == "MoM 6 mesi":
            start = end - pd.DateOffset(months=6) + pd.Timedelta(days=1)
            prev_end = start - pd.Timedelta(days=1)
            prev_start = prev_end - pd.DateOffset(months=6) + pd.Timedelta(days=1)
        elif option == "YoY 28gg":
            start = end - pd.Timedelta(days=27)
            prev_start = start - pd.DateOffset(years=1)
            prev_end = end - pd.DateOffset(years=1)
        elif option == "YoY 3 mesi":
            start = end - pd.DateOffset(months=3) + pd.Timedelta(days=1)
            prev_start = start - pd.DateOffset(years=1)
            prev_end = end - pd.DateOffset(years=1)
        elif option == "YoY 6 mesi":
            start = end - pd.DateOffset(months=6) + pd.Timedelta(days=1)
            prev_start = start - pd.DateOffset(years=1)
            prev_end = end - pd.DateOffset(years=1)
        else:
            start = end - pd.Timedelta(days=27)
            prev_end = start - pd.Timedelta(days=27)
            prev_start = prev_end - pd.Timedelta(days=27)
        return ((start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')),
                (prev_start.strftime('%Y-%m-%d'), prev_end.strftime('%Y-%m-%d')))

    def fetch_comparison_data(
        self,
        site_url: str,
        start: str,
        end: str,
        prev_start: str,
        prev_end: str,
        dimensions: list[str],
        row_limit: int
    ) -> pd.DataFrame | None:
        """Recupera due periodi e li combina con una colonna 'period'."""
        df_current = self.fetch_gsc_data(site_url, start, end, dimensions, row_limit)
        df_prev = self.fetch_gsc_data(site_url, prev_start, prev_end, dimensions, row_limit)
        if df_current is None or df_prev is None:
            return None
        df_current['period'] = 'current'
        df_prev['period'] = 'previous'
        return pd.concat([df_current, df_prev], ignore_index=True)

    
    def refresh_credentials(self):
        """Aggiorna i token OAuth se necessario"""
        try:
            from google.auth.transport.requests import Request
            
            credentials = Credentials(
                token=self.session_state.access_token,
                refresh_token=self.session_state.refresh_token,
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
                self.session_state.access_token = credentials.token
                self.session_state.refresh_token = credentials.refresh_token
            
            return credentials
            
        except Exception as e:
            st.error(f"Errore nel refresh delle credenziali: {e}")
            # Forza re-login
            self.session_state.authenticated = False
            st.rerun()
            return None

    def fetch_gsc_data(self, site_url: str, start_date: str, end_date: str, dimensions=['query'], row_limit=1000):
        """Recupera dati direttamente da Google Search Console API"""
        if not self.session_state.get('authenticated', False):
            st.error("🤖💬 Utente non autenticato")
            return None
        
        try:
            # Ottieni credenziali aggiornate
            credentials = self.refresh_credentials()
            if not credentials:
                return None
            
            # Costruisci il servizio GSC
            service = build('searchconsole', 'v1', credentials=credentials)
            
            # Prepara la richiesta
            request = {
                'startDate': start_date,
                'endDate': end_date,
                'dimensions': dimensions,
                'rowLimit': row_limit,
                'aggregationType': 'auto'
            }
            
            # Esegui la query
            response = service.searchanalytics().query(siteUrl=site_url, body=request).execute()
            
            # Converti in DataFrame
            if 'rows' in response:
                data = []
                for row in response['rows']:
                    row_data = {}
                    
                    # Aggiungi le dimensioni
                    if 'keys' in row:
                        for i, dimension in enumerate(dimensions):
                            row_data[dimension] = row['keys'][i] if i < len(row['keys']) else None
                    
                    # Aggiungi le metriche
                    row_data['clicks'] = row.get('clicks', 0)
                    row_data['impressions'] = row.get('impressions', 0)
                    row_data['ctr'] = row.get('ctr', 0.0)
                    row_data['position'] = row.get('position', 0.0)
                    
                    data.append(row_data)
                
                df = pd.DataFrame(data)
                return df
            else:
                st.info("🤖💬 Nessun dato trovato per il periodo specificato")
                return pd.DataFrame()
                
        except Exception as e:
            error_msg = str(e)
            if 'invalid_grant' in error_msg or 'Bad Request' in error_msg:
                st.error("🔑 Sessione scaduta. Per favore, effettua nuovamente il login.")
                self.session_state.authenticated = False
                if st.button("🔄 Vai al Login", key="gsc_login_redirect"):
                    st.rerun()
            else:
                st.error(f"🤖💬 Errore nel recupero dati GSC: {e}")
            return None

    def generate_dataframe_analysis(self, question: str, df: pd.DataFrame, project_id: str = None) -> str | None:
        """Genera analisi AI su DataFrame invece che SQL"""
        if df.empty:
            return "Non ci sono dati da analizzare."
        

        # Se la chiave OpenAI non è disponibile, restituiamo un'analisi di base
        if not self.openai_api_key:

            return self._generate_basic_analysis(question, df)

        try:
            
            # Prepara informazioni sul DataFrame
            df_info = {
                'columns': list(df.columns),
                'shape': df.shape,
                'sample_data': df.head(10).to_string(index=False),
                'data_types': df.dtypes.to_dict()
            }
            
            prompt_parts = [
                "Sei un esperto analista di dati di Google Search Console. Ti viene fornito un DataFrame con dati GSC e una domanda dell'utente.",
                f"Domanda dell'utente: \"{question}\"",
                f"\nInformazioni sul DataFrame:",
                f"- Colonne disponibili: {df_info['columns']}",
                f"- Numero di righe: {df_info['shape'][0]}",
                f"- Tipi di dati: {df_info['data_types']}",
                f"\nCampione di dati (prime 10 righe):",
                df_info['sample_data'],
                "\nAnalizza i dati e rispondi alla domanda dell'utente in modo chiaro e conciso.",
                "Metti in grassetto (usando **testo**) le metriche e i dati più importanti.",
                "Se necessario, calcola aggregazioni, trend o confronti basati sui dati forniti."
            ]
            
            full_prompt = "\n".join(prompt_parts)
            response = self.openai_client.chat.completions.create(
                model=self.OPENAI_MODEL,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=1,
                # Some providers expect the parameter name 'max_completion_tokens'
                # instead of 'max_tokens'. Using the more compatible parameter
                # avoids API errors like:
                # "Unsupported parameter: 'max_tokens' is not supported with this model."
                max_completion_tokens=1024,
            )

            answer = response.choices[0].message.content.strip()

            if not answer:
                return self._generate_basic_analysis(question, df)
            return answer

        except Exception as e:
            st.warning(f"Errore nell'analisi AI avanzata: {e}. Uso analisi di base.")
            return self._generate_basic_analysis(question, df)

    def _generate_basic_analysis(self, question: str, df: pd.DataFrame) -> str:
        """Genera un'analisi di base quando Vertex AI non è disponibile"""
        try:
            analysis_parts = []
            
            # Informazioni generali
            analysis_parts.append(f"**Analisi dati GSC per: \"{question}\"**\n")
            analysis_parts.append(f"📊 **Dataset**: {len(df)} righe, {len(df.columns)} colonne\n")
            
            # Metriche totali se disponibili
            if 'clicks' in df.columns:
                total_clicks = df['clicks'].sum()
                analysis_parts.append(f"🔢 **Clic totali**: {total_clicks:,}")
            
            if 'impressions' in df.columns:
                total_impressions = df['impressions'].sum()
                analysis_parts.append(f"👁️ **Impressioni totali**: {total_impressions:,}")
            
            if 'ctr' in df.columns and len(df) > 0:
                avg_ctr = df['ctr'].mean()
                analysis_parts.append(f"📈 **CTR medio**: {avg_ctr:.2%}")
            
            if 'position' in df.columns and len(df) > 0:
                avg_position = df['position'].mean()
                analysis_parts.append(f"📍 **Posizione media**: {avg_position:.1f}")
            
            # Top performers se abbiamo query
            if 'query' in df.columns and 'clicks' in df.columns:
                top_queries = df.nlargest(5, 'clicks')[['query', 'clicks', 'impressions']]
                analysis_parts.append(f"\n🏆 **Top 5 Query per Clic**:")
                for _, row in top_queries.iterrows():
                    analysis_parts.append(f"- **{row['query']}**: {row['clicks']} clic, {row['impressions']} impressioni")
            
            return "\n".join(analysis_parts)
            
        except Exception as e:
            return f"Analisi completata su {len(df)} righe di dati GSC. Errore nel dettaglio: {e}"

    def generate_chart_code_with_llm(self, question: str, df: pd.DataFrame, project_id: str = None) -> str | None:
        """Genera codice Python Matplotlib per visualizzare i dati"""
        if df.empty:
            st.info("🤖💬 Nessun dato disponibile per generare un grafico.")
            return None

        # Se la chiave OpenAI non è disponibile, generiamo codice di base
        if not self.openai_api_key:

            return self._generate_basic_chart_code(df)

        try:

            if len(df) > 10:
                data_sample = df.sample(min(10, len(df))).to_string(index=False)
            else:
                data_sample = df.to_string(index=False)
            
            column_details = []
            for col in df.columns:
                col_type = str(df[col].dtype)
                column_details.append(f"- Colonna '{col}' (tipo: {col_type})")
            column_info = "\n".join(column_details)

            chart_prompt = f"""
Genera codice Python usando Matplotlib per visualizzare questi dati:

Domanda: "{question}"
Tipo dati: Dati Google Search Console

Colonne disponibili:
{column_info}

Campione dati:
{data_sample}

Il codice deve:
1. Usare il DataFrame 'df' (già disponibile)
2. Creare figura con `fig, ax = plt.subplots(figsize=(10, 6))`
3. Scegliere il grafico più appropriato per dati GSC
4. Includere titolo e etichette
5. Assegnare la figura alla variabile 'fig'
6. NON includere plt.show()

Restituisci SOLO il codice Python.
"""
            response = self.openai_client.chat.completions.create(
                model=self.OPENAI_MODEL,
                messages=[{"role": "user", "content": chart_prompt}],
                temperature=1,
                # Use 'max_completion_tokens' for wider compatibility with
                # models that do not accept the 'max_tokens' parameter.
                max_completion_tokens=512,
            )

            code_content = response.choices[0].message.content.strip()
            if not code_content:
                return self._generate_basic_chart_code(df)

            if code_content.startswith("```python"):
                code_content = code_content[len("```python"):].strip()
            if code_content.endswith("```"):
                code_content = code_content[:-len("```")].strip()

            return code_content
        except Exception as e:
            st.warning(f"Errore nella generazione avanzata del grafico: {e}. Uso grafico di base.")
            return self._generate_basic_chart_code(df)

    def _generate_basic_chart_code(self, df: pd.DataFrame) -> str:
        """Genera codice per un grafico di base"""
        if 'clicks' in df.columns and 'query' in df.columns:
            return """
# Grafico a barre per top query per clic
top_data = df.nlargest(10, 'clicks')
fig, ax = plt.subplots(figsize=(12, 6))
bars = ax.barh(range(len(top_data)), top_data['clicks'])
ax.set_yticks(range(len(top_data)))
ax.set_yticklabels(top_data['query'], fontsize=10)
ax.set_xlabel('Clic')
ax.set_title('Top 10 Query per Clic')
ax.invert_yaxis()
plt.tight_layout()
"""
        elif 'impressions' in df.columns and 'page' in df.columns:
            return """
# Grafico a barre per top pagine per impressioni
top_data = df.nlargest(10, 'impressions')
fig, ax = plt.subplots(figsize=(12, 6))
bars = ax.barh(range(len(top_data)), top_data['impressions'])
ax.set_yticks(range(len(top_data)))
labels = [url if len(url) <= 50 else url[:47] + '...' for url in top_data['page']]
ax.set_yticklabels(labels, fontsize=8)
ax.set_xlabel('Impressioni')
ax.set_title('Top 10 Pagine per Impressioni')
ax.invert_yaxis()
plt.tight_layout()
"""
        else:
            return """
# Grafico generico delle metriche disponibili
numeric_cols = df.select_dtypes(include=['int64', 'float64']).columns
if len(numeric_cols) > 0:
    fig, ax = plt.subplots(figsize=(10, 6))
    df[numeric_cols[:4]].sum().plot(kind='bar', ax=ax)
    ax.set_title('Riepilogo Metriche GSC')
    ax.set_ylabel('Valori')
    plt.xticks(rotation=45)
    plt.tight_layout()
else:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.text(0.5, 0.5, 'Nessun dato numerico disponibile per il grafico', 
            ha='center', va='center', transform=ax.transAxes, fontsize=16)
    ax.set_title('Dati GSC')
"""

    def render_sidebar_config(self):
        """Renderizza la configurazione nella sidebar"""
        st.markdown("### 🌐 Configurazione GSC")
        
        # Debug info se necessario
        if not self.session_state.get('credentials_verified', False):
            st.warning("⚠️ Credenziali non ancora verificate. Il primo accesso potrebbe richiedere un momento.")
        
        # Carica siti GSC se non già fatto
        if not self.session_state.get('gsc_sites_data', []):
            with st.spinner("Caricando i tuoi siti GSC..."):
                sites_data = self.get_gsc_sites()
                self.session_state.gsc_sites_data = sites_data
        
        # Selezione sito GSC
        if self.session_state.get('gsc_sites_data', []):
            site_options = [f"{site['url']} ({site['permission']})" for site in self.session_state.gsc_sites_data]
            selected_site_display = st.selectbox(
                "🌐 Seleziona Sito GSC",
                options=site_options,
                key="site_selector_gsc"
            )
            
            # Estrai l'URL pulito
            if selected_site_display:
                selected_site_url = selected_site_display.split(' (')[0]
                self.session_state.selected_site = selected_site_url
                
                # Configurazione periodo dati
                date_option = st.selectbox(
                    "⏱️ Intervallo Date",
                    [
                        "Personalizzato",
                        "Ultimi 28 giorni",
                        "Ultimi 3 mesi",
                        "Ultimi 6 mesi",
                        "Ultimi 12 mesi",
                        "Ultimi 16 mesi",
                    ],
                    key="gsc_date_option",
                )
                if date_option == "Personalizzato":
                    col1, col2 = st.columns(2)
                    with col1:
                        start_date = st.date_input(
                            "📅 Data Inizio",
                            value=pd.Timestamp.now() - pd.Timedelta(days=30),
                            key="gsc_start_date",
                        )
                    with col2:
                        end_date = st.date_input(
                            "📅 Data Fine",
                            value=pd.Timestamp.now() - pd.Timedelta(days=1),
                            key="gsc_end_date",
                        )
                else:
                    start_date, end_date = self._get_fixed_range(date_option)
                    st.info(f"Intervallo selezionato: {date_option}")
                
                # Dimensioni da includere
                dimensions = st.multiselect(
                    "📊 Dimensioni",
                    options=['query', 'page', 'country', 'device', 'searchAppearance'],
                    default=['query'],
                    key="gsc_dimensions"
                )
                
                row_limit = st.number_input(
                    "📈 Limite Righe",
                    min_value=100,
                    max_value=25000,
                    value=1000,
                    step=100,
                    key="gsc_row_limit"
                )

                compare_mode = st.checkbox("🔄 Modalità Confronto", key="gsc_compare_mode")
                if compare_mode:
                    compare_type = st.selectbox(
                        "Tipo di confronto",
                        [
                            "MoM 28gg",
                            "MoM 3 mesi",
                            "MoM 6 mesi",
                            "YoY 28gg",
                            "YoY 3 mesi",
                            "YoY 6 mesi",
                        ],
                        key="gsc_compare_type",
                    )
                    (curr_range, prev_range) = self._get_compare_ranges(compare_type)
                    start_date, end_date = pd.to_datetime(curr_range[0]), pd.to_datetime(curr_range[1])
                    compare_start, compare_end = prev_range
                else:
                    compare_type = None
                    compare_start = compare_end = None
                
                self.session_state.gsc_config = {
                    'site_url': selected_site_url,
                    'start_date': start_date.strftime('%Y-%m-%d'),
                    'end_date': end_date.strftime('%Y-%m-%d'),
                    'dimensions': dimensions,
                    'row_limit': row_limit,
                    'compare_mode': compare_mode,
                    'compare_type': compare_type,
                    'compare_start': compare_start,
                    'compare_end': compare_end,
                }
                
                self.session_state.config_applied_successfully = True
                st.success("🟢 Configurazione GSC attiva")
                return True
        else:
            st.warning("Nessun sito GSC trovato per il tuo account")
            return False

    def render(self):
        """Renderizza l'interfaccia principale della modalità GSC Diretta"""
        
        # Configura nella sidebar (chiamata dal main app)
        with st.sidebar:
            config_ok = self.render_sidebar_config()

        if not config_ok:
            st.markdown("""
            ## ⚙️ Configurazione GSC Richiesta
            
            Completa la configurazione nella sidebar per iniziare a utilizzare la modalità GSC Diretta.
            
            ### Questa modalità ti permette di:
            - 📊 Accedere ai dati GSC in tempo reale
            - 🔍 Analizzare performance senza BigQuery
            - 💬 Fare domande naturali sui tuoi dati
            - 📈 Generare grafici automaticamente
            """)
            return

        # Chat interface
        with st.form(key='gsc_query_form'):
            user_question_input = st.text_area(
                "La tua domanda sui dati GSC:", 
                height=100, 
                placeholder="Es. Quali sono le mie top 10 query per clic?",
                key="gsc_user_question" 
            )
            submit_button_main = st.form_submit_button(label="Analizza con GSC 🔍")

        # Domande preimpostate per GSC
        st.write("Oppure prova una di queste domande rapide:")
        preset_questions_data = [
            ("Top Query", "Quali sono le 10 query con più clic?"),
            ("Performance Totale", "Qual è la performance totale (clic, impressioni, CTR, posizione media)?"),
            ("Query CTR Alto", "Quali query hanno il CTR più alto (con almeno 100 impressioni)?"),
            ("Query Pos. Bassa", "Quali query hanno posizione media sopra 10 ma con molte impressioni?"),
            ("Pagine Top", "Quali sono le 10 pagine con più impressioni?"),
            ("Device Analysis", "Come si distribuiscono i clic per dispositivo?"),
            ("Paesi Top", "Da quali paesi arrivano più clic?"),
            ("Search Appearance", "Come si distribuiscono i clic per tipo di risultato?")
        ]

        cols = st.columns(4)
        for i, (label, question_text) in enumerate(preset_questions_data):
            col_idx = i % 4
            if cols[col_idx].button(label, key=f"gsc_preset_q_{i}"):
                user_question_input = question_text
                submit_button_main = True

        # Processamento domanda
        if submit_button_main and user_question_input:
            if not self.session_state.get('gsc_config'):
                st.error("🤖💬 Per favore, completa la configurazione GSC nella sidebar.")
                return
            
            config = self.session_state.gsc_config
            
            # Fetch dati da GSC
            with st.spinner(f"🤖💬 Recuperando dati da Google Search Console per: \"{user_question_input}\""):
                if config.get('compare_mode'):
                    gsc_data = self.fetch_comparison_data(
                        config['site_url'],
                        config['start_date'],
                        config['end_date'],
                        config['compare_start'],
                        config['compare_end'],
                        config['dimensions'],
                        config['row_limit']
                    )
                else:
                    gsc_data = self.fetch_gsc_data(
                        config['site_url'],
                        config['start_date'],
                        config['end_date'],
                        config['dimensions'],
                        config['row_limit']
                    )
                self.session_state.gsc_data = gsc_data

            if gsc_data is not None and not gsc_data.empty:
                with st.expander("🔍 Dati GSC Recuperati", expanded=False):
                    st.subheader("Dataset GSC:")
                    st.write(f"**Sito:** {config['site_url']}")
                    if config.get('compare_mode'):
                        st.write(
                            f"**Periodo attuale:** {config['start_date']} - {config['end_date']}"
                        )
                        st.write(
                            f"**Periodo confronto:** {config['compare_start']} - {config['compare_end']}"
                        )
                    else:
                        st.write(f"**Periodo:** {config['start_date']} - {config['end_date']}")
                    st.write(f"**Dimensioni:** {', '.join(config['dimensions'])}")
                    st.write(f"**Righe:** {len(gsc_data)}")
                    st.dataframe(gsc_data.head(200))
                
                # Genera analisi AI
                with st.spinner("🤖💬 Sto analizzando i dati con l'AI..."):
                    analysis_project = self.session_state.get('selected_project_id', None)
                    analysis_summary = self.generate_dataframe_analysis(
                        user_question_input,
                        gsc_data,
                        analysis_project
                    )
                
                if analysis_summary:
                    with st.chat_message("ai", avatar="🤖"):
                        st.markdown(analysis_summary)

                # Sezione grafico
                if self.session_state.get('enable_chart_generation', False):
                    st.markdown("---")
                    st.subheader("📊 Visualizzazione Grafica (Beta)")
                    with st.spinner("🤖💬 Sto generando il codice per il grafico..."):
                        analysis_project = self.session_state.get('selected_project_id', None)
                        chart_code = self.generate_chart_code_with_llm(
                            user_question_input, 
                            gsc_data,
                            analysis_project
                        )
                        
                        if chart_code:
                            try:
                                exec_scope = {
                                    "plt": plt, 
                                    "pd": pd, 
                                    "df": gsc_data.copy(),
                                    "fig": None
                                }
                                exec(chart_code, exec_scope)
                                fig_generated = exec_scope.get("fig")

                                if fig_generated is not None:
                                    st.pyplot(fig_generated)
                                else:
                                    st.warning("🤖💬 L'AI ha generato codice, ma non è stato possibile creare un grafico.")
                            except Exception as e:
                                st.error(f"🤖💬 Errore durante l'esecuzione del codice del grafico: {e}")
                        else:
                            st.warning("🤖💬 Non è stato possibile generare il codice per il grafico.")
            elif gsc_data is not None:
                st.info("🤖💬 Nessun dato trovato per i parametri specificati.")
            else:
                st.error("🤖💬 Errore nel recupero dei dati da Google Search Console.")
