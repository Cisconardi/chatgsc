import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
import tempfile
import json
from google.cloud import bigquery
import openai
from google.oauth2.credentials import Credentials

class BigQueryMode:
    """Classe per gestire la modalità BigQuery Avanzata"""
    
    def __init__(self, session_state):
        self.session_state = session_state
        self.OPENAI_MODEL = "o4-mini"
        self.openai_api_key = st.secrets.get("openai_api_key", None)
        if self.openai_api_key:
            self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
        else:
            self.openai_client = None
    
    def setup_gcp_credentials_from_oauth(self):
        """Configura le credenziali GCP usando il token OAuth"""
        if not self.session_state.get('authenticated', False):
            return False
        
        try:
            # Crea credenziali Google Cloud usando il token OAuth
            credentials = Credentials(
                token=self.session_state.access_token,
                refresh_token=self.session_state.refresh_token,
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
                'refresh_token': self.session_state.refresh_token,
            }
            
            json.dump(creds_info, temp_file)
            temp_file.close()
            
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_file.name
            self.session_state.temp_credentials_file = temp_file.name
            
            return True
            
        except Exception as e:
            st.error(f"Errore nella configurazione delle credenziali GCP: {e}")
            return False

    def get_table_schema_for_prompt(self, project_id: str, dataset_id: str, table_names_str: str) -> str | None:
        """Recupera lo schema delle tabelle BigQuery per il prompt"""
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

    def generate_sql_from_question(self, project_id: str, location: str, model_name: str, question: str, table_schema_prompt: str, few_shot_examples_str: str) -> str | None:
        """Genera query SQL da domanda in linguaggio naturale"""
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"): 
            st.error("🤖💬 Le credenziali GCP non sono state configurate.")
            return None
        if not all([project_id, location, model_name, question, table_schema_prompt]):
            st.error("🤖💬 Mancano alcuni parametri per la generazione SQL.")
            return None

        try:
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
            if not self.openai_client:
                st.error("Chiave OpenAI mancante.")
                return None
            response = self.openai_client.chat.completions.create(
                model=self.OPENAI_MODEL,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.1,
                max_completion_tokens=1024,
            )

            if not response.choices or not response.choices[0].message.content:
                st.error("🤖💬 Il modello non ha restituito una risposta valida.")
                return None
            sql_query = response.choices[0].message.content.strip()
            if "ERRORE:" in sql_query:
                st.error(f"🤖💬 Il modello ha indicato un errore: {sql_query}")
                return None
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
            return sql_query
        except Exception as e:
            st.error(f"🤖💬 Errore durante la chiamata a OpenAI: {e}")
            return None

    def execute_bigquery_query(self, project_id: str, sql_query: str) -> pd.DataFrame | None:
        """Esegue query su BigQuery"""
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

    def summarize_results_with_llm(self, project_id: str, location: str, model_name: str, results_df: pd.DataFrame, original_question: str) -> str | None:
        """Genera riassunto dei risultati con LLM"""
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            st.error("🤖💬 Le credenziali GCP non sono state configurate.")
            return None
        if results_df.empty:
            return "Non ci sono dati da riassumere." 
        if not all([project_id, location, model_name]):
            st.error("🤖💬 Mancano alcuni parametri per la generazione del riassunto.")
            return None
        try:
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
            if not self.openai_client:
                st.error("Chiave OpenAI mancante.")
                return None
            response = self.openai_client.chat.completions.create(
                model=self.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_completion_tokens=512,
            )
            if not response.choices or not response.choices[0].message.content:
                st.warning("Il modello non ha restituito un riassunto valido.")
                return "Non è stato possibile generare un riassunto."
            return response.choices[0].message.content.strip()
        except Exception as e:
            st.error(f"Errore durante la generazione del riassunto con OpenAI: {e}")
            return "Errore nella generazione del riassunto."

    def generate_chart_code_with_llm(self, project_id: str, location: str, model_name: str, original_question: str, sql_query: str, query_results_df: pd.DataFrame) -> str | None:
        """Genera codice Python Matplotlib per visualizzare i dati"""
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            st.error("🤖💬 Credenziali GCP non configurate.")
            return None
        if query_results_df.empty:
            st.info("🤖💬 Nessun dato disponibile per generare un grafico.")
            return None
        
        try:
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
            if not self.openai_client:
                st.error("Chiave OpenAI mancante.")
                return None
            response = self.openai_client.chat.completions.create(
                model=self.OPENAI_MODEL,
                messages=[{"role": "user", "content": chart_prompt}],
                temperature=1,
                max_completion_tokens=512,
            )

            if response.choices and response.choices[0].message.content:
                code_content = response.choices[0].message.content.strip()
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

    def render_sidebar_config(self):
        """Renderizza la configurazione BigQuery nella sidebar"""
        st.markdown("### 📊 Configurazione BigQuery")
        
        # Configurazione progetto GCP
        gcp_project_id = st.text_input(
            "🔧 ID Progetto Google Cloud",
            value=self.session_state.get('selected_project_id', ''),
            help="Progetto GCP dove sono i dati BigQuery",
            key="bq_project_id"
        )
        
        gcp_location = st.text_input(
            "🌍 Location GCP",
            value=self.session_state.get('gcp_location', 'europe-west1'),
            help="Regione del progetto (es. europe-west1)",
            key="bq_location"
        )
        
        bq_dataset_id = st.text_input(
            "📊 ID Dataset BigQuery",
            value=self.session_state.get('bq_dataset_id', ''),
            help="Dataset con le tabelle GSC",
            key="bq_dataset"
        )
        
        bq_table_names_str = st.text_area(
            "📋 Nomi Tabelle GSC",
            value=self.session_state.get('bq_table_names_str', 'searchdata_url_impression,searchdata_site_impression'),
            help="Tabelle GSC separate da virgola",
            key="bq_tables"
        )
        
        # Applica configurazione BigQuery
        if st.button("✅ Applica Configurazione BigQuery", key="apply_config_bq"):
            if all([gcp_project_id, gcp_location, bq_dataset_id, bq_table_names_str]):
                if self.setup_gcp_credentials_from_oauth():
                    self.session_state.selected_project_id = gcp_project_id
                    self.session_state.gcp_location = gcp_location
                    self.session_state.bq_dataset_id = bq_dataset_id
                    self.session_state.bq_table_names_str = bq_table_names_str
                    self.session_state.config_applied_successfully = True
                    
                    # Carica schema tabelle
                    with st.spinner("Caricando schema tabelle..."):
                        self.session_state.table_schema_for_prompt = self.get_table_schema_for_prompt(
                            gcp_project_id, bq_dataset_id, bq_table_names_str
                        )
                    
                    if self.session_state.table_schema_for_prompt:
                        st.success("✅ Configurazione BigQuery applicata!")
                        st.rerun()
                    else:
                        st.error("❌ Errore nel caricamento dello schema")
                        self.session_state.config_applied_successfully = False
                else:
                    st.error("❌ Errore nella configurazione delle credenziali")
            else:
                st.error("❌ Compila tutti i campi richiesti")
        
        if self.session_state.get('config_applied_successfully', False) and self.session_state.get('analysis_mode') == "📊 BigQuery (Avanzato)":
            st.success("🟢 Configurazione BigQuery attiva")
            
            # Mostra schema in expander per debug
            if self.session_state.get('table_schema_for_prompt'):
                with st.expander("🔍 Schema Tabelle (Debug)", expanded=False):
                    st.code(self.session_state.table_schema_for_prompt, language='text')
            
            return True
        
        return False

    def render(self):
        """Renderizza l'interfaccia principale della modalità BigQuery"""
        
        # Configura nella sidebar
        with st.sidebar:
            config_ok = self.render_sidebar_config()

        if not config_ok:
            st.markdown("""
            ## ⚙️ Configurazione BigQuery Richiesta
            
            Completa la configurazione nella sidebar per iniziare a utilizzare la modalità BigQuery.
            
            ### Cosa ti serve:
            - **Progetto Google Cloud** con BigQuery attivato
            - **Dataset BigQuery** con dati GSC esportati
            - **API key OpenAI**
            - **Permessi appropriati** per leggere BigQuery
            
            ### Questa modalità ti permette di:
            - 🔍 Query SQL avanzate sui dati storici GSC
            - 📊 Analisi complesse con joins e aggregazioni
            - 🤖 Generazione automatica di SQL tramite AI
            - 📈 Visualizzazioni potenti dei risultati
            
            ### Setup richiesto:
            1. **Esporta dati GSC** → BigQuery (vedi [guida Google](https://support.google.com/webmasters/answer/12918484))
            2. **Configura progetto GCP** con API abilitate
            3. **Applica configurazione** nella sidebar
            """)
            return

        # Chat interface
        with st.form(key='bq_query_form'):
            user_question_input = st.text_area(
                "La tua domanda sui dati BigQuery:", 
                height=100, 
                placeholder="Es. Quante impressioni ho ricevuto la scorsa settimana per le query che contengono 'AI'?",
                key="bq_user_question" 
            )
            submit_button_main = st.form_submit_button(label="Genera SQL e Analizza 🔍")

        # Domande preimpostate per BigQuery
        st.write("Oppure prova una di queste domande rapide:")
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
            if cols[col_idx].button(label, key=f"bq_preset_q_{i}"):
                user_question_input = question_text
                submit_button_main = True

        # Processamento domanda
        if submit_button_main and user_question_input:
            if not self.session_state.get('config_applied_successfully', False):
                st.error("🤖💬 Per favore, completa e applica la configurazione BigQuery nella sidebar.")
                return
            elif not self.session_state.get('table_schema_for_prompt'): 
                st.error("🤖💬 Lo schema delle tabelle non è disponibile. Verifica la configurazione BigQuery.")
                return
            
            # Reset risultati precedenti
            self.session_state.sql_query = ""
            self.session_state.query_results = None
            self.session_state.results_summary = ""
            
            # Genera SQL
            with st.spinner(f"🤖💬 Sto generando la query SQL per: \"{user_question_input}\""):
                sql_query = self.generate_sql_from_question(
                    self.session_state.selected_project_id, 
                    self.session_state.get('gcp_location', 'europe-west1'), 
                    self.OPENAI_MODEL,
                    user_question_input,
                    self.session_state.table_schema_for_prompt, 
                    ""
                )

            if sql_query:
                with st.expander("🔍 Dettagli Tecnici", expanded=False):
                    st.subheader("Query SQL Generata:")
                    st.code(sql_query, language='sql')
                
                    # Esegui query
                    query_results = self.execute_bigquery_query(self.session_state.selected_project_id, sql_query)

                    if query_results is not None:
                        st.subheader("Risultati Grezzi (Prime 200 righe):")
                        if query_results.empty:
                            st.info("La query non ha restituito risultati.")
                        else:
                            st.dataframe(query_results.head(200))
                
                if query_results is not None and not query_results.empty:
                    # Genera riassunto
                    with st.spinner("🤖💬 Sto generando un riassunto dei risultati..."):
                        results_summary = self.summarize_results_with_llm(
                            self.session_state.selected_project_id, 
                            self.session_state.get('gcp_location', 'europe-west1'), 
                            self.OPENAI_MODEL,
                            query_results, 
                            user_question_input
                        )
                    
                    if results_summary and results_summary != "Non ci sono dati da riassumere.":
                        with st.chat_message("ai", avatar="🤖"):
                            st.markdown(results_summary) 
                    else: 
                        st.warning("🤖💬 Non è stato possibile generare un riassunto, ma la query ha prodotto risultati.")

                    # Sezione generazione grafico
                    if self.session_state.get('enable_chart_generation', False):
                        st.markdown("---")
                        st.subheader("📊 Visualizzazione Grafica (Beta)")
                        with st.spinner("🤖💬 Sto generando il codice per il grafico..."):
                            chart_code = self.generate_chart_code_with_llm(
                                self.session_state.selected_project_id, 
                                self.session_state.get('gcp_location', 'europe-west1'), 
                                self.OPENAI_MODEL,
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
                                        st.warning("🤖💬 L'AI ha generato codice, ma non è stato possibile creare un grafico.")
                                        with st.expander("Codice grafico generato (Debug)"):
                                            st.code(chart_code, language="python")
                                except Exception as e:
                                    st.error(f"🤖💬 Errore durante l'esecuzione del codice del grafico: {e}")
                                    with st.expander("Codice grafico generato (con errore)"):
                                        st.code(chart_code, language="python")
                            else:
                                st.warning("🤖💬 Non è stato possibile generare il codice per il grafico.")
                elif query_results is not None:
                    st.info("🤖💬 La query non ha restituito risultati.")
                else:
                    st.error("🤖💬 Errore nell'esecuzione della query BigQuery.")
            else:
                st.error("Non è stato possibile generare una query SQL per la tua domanda.")
