# ChatGSC - Conversa con i dati di Google Search Console

## 🏗️ Struttura del Progetto

Il progetto è ora organizzato in moduli separati per una migliore manutenibilità e scalabilità:

```
chatgsc/
├── app.py                 # File principale dell'applicazione
├── gsc_direct.py         # Modalità Google Search Console Diretta
├── bigquery_mode.py      # Modalità BigQuery Avanzata  
├── config.py             # Configurazioni e utility
├── requirements.txt      # Dipendenze Python
└── README.md            # Documentazione
```

## 📁 Descrizione dei File

### `app.py` - File Principale
- **Funzione**: Entry point dell'applicazione
- **Responsabilità**:
  - Configurazione Streamlit e Supabase
  - Gestione autenticazione OAuth
  - Coordinamento tra le modalità
  - UI principale e sidebar
  - Footer e privacy policy

### `gsc_direct.py` - Modalità GSC Diretta
- **Funzione**: Interazione diretta con Google Search Console API
- **Caratteristiche**:
  - Fetch dati in tempo reale da GSC
  - Analisi AI su DataFrame
  - Configurazione semplificata
  - Domande preimpostate ottimizzate

### `bigquery_mode.py` - Modalità BigQuery
- **Funzione**: Analisi avanzata su dati GSC esportati in BigQuery
- **Caratteristiche**:
  - Generazione automatica SQL tramite AI
  - Query complesse su dati storici
  - Schema tabelle dinamico
  - Analisi potenti con aggregazioni

### `config.py` - Configurazioni
- **Funzione**: Configurazioni centrali e utility
- **Contenuto**:
  - Costanti globali
  - Modelli AI utilizzati
  - Domande preimpostate
  - Funzioni helper
  - Validazioni

## 🚀 Come Eseguire

### 1. Installazione Dipendenze
```bash
pip install -r requirements.txt
```

### 2. Configurazione Secrets
Crea il file `.streamlit/secrets.toml`:
```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
google_oauth_client_id = "your-client-id"
google_oauth_client_secret = "your-client-secret"
app_url = "https://your-app-url.streamlit.app"
```

### 3. Avvio Applicazione
```bash
streamlit run app.py
```

## 🔧 Configurazione

### Supabase Setup
1. Crea progetto su [Supabase](https://supabase.com)
2. Abilita Google OAuth Provider
3. Configura redirect URLs:
   - `https://your-app-url.streamlit.app`
4. Copia URL e anon key nei secrets

### Google Cloud Setup
1. Crea progetto su [Google Cloud Console](https://console.cloud.google.com)
2. Abilita API:
   - Google Search Console API
   - BigQuery API (per modalità avanzata)
   - Vertex AI API (per modalità avanzata)
3. Crea OAuth 2.0 Client ID
4. Aggiungi redirect URI di Supabase

## 📊 Modalità di Utilizzo

### 🔍 GSC Diretto
**Vantaggi**:
- ✅ Setup semplice
- ✅ Dati in tempo reale
- ✅ Non richiede BigQuery
- ✅ Configurazione rapida

**Limitazioni**:
- ⚠️ Limitato a 25.000 righe per query
- ⚠️ Solo ultimi 16 mesi di dati
- ⚠️ Dimensioni API predefinite

### 📊 BigQuery Avanzato
**Vantaggi**:
- ✅ Dati storici completi
- ✅ Query SQL complesse
- ✅ Joins tra tabelle
- ✅ Analisi avanzate

**Requisiti**:
- 🔧 Export GSC → BigQuery configurato
- 🔧 Progetto GCP con Vertex AI
- 🔧 Permessi BigQuery

## 🛠️ Architettura Tecnica

### Flusso Autenticazione
```
User → Google OAuth → Supabase → App
```

### Modalità GSC Diretta
```
User Question → GSC API → DataFrame → AI Analysis → Response
```

### Modalità BigQuery
```
User Question → AI → SQL → BigQuery → DataFrame → AI Summary → Response
```

## 🔐 Sicurezza

- **OAuth 2.0**: Autenticazione sicura senza password
- **Token temporanei**: Nessun dato persistente
- **HTTPS**: Comunicazioni crittografate
- **Scope limitati**: Accesso minimo necessario

## 📈 Features

### Comuni
- 🤖 Analisi AI avanzata
- 📊 Generazione grafici automatica
- 💬 Chat naturale
- 🔄 Domande preimpostate

### GSC Diretto
- 📅 Selezione periodo flessibile
- 📊 Dimensioni multiple (query, page, country, device)
- 🎯 Limite righe configurabile
- ⚡ Risposta immediata

### BigQuery
- 🔍 SQL generato automaticamente
- 📋 Schema tabelle dinamico
- 🕒 Analisi storiche complete
- 🔗 Query complesse con joins

## 🐛 Troubleshooting

### Errori Comuni

**"Authentication failed"**
- ✅ Verifica configurazione OAuth in Google Cloud
- ✅ Controlla redirect URI in Supabase
- ✅ Verifica secrets Streamlit

**"BigQuery permission denied"**
- ✅ Abilita BigQuery API
- ✅ Verifica permessi IAM del progetto
- ✅ Controlla nome progetto nei secrets

**"Vertex AI not available"**
- ✅ Abilita Vertex AI API
- ✅ Verifica region supportate
- ✅ Controlla quota progetto

### Logs e Debug
- 🔍 Streamlit Cloud: Manage app → Logs
- 🔍 Browser: F12 → Console per errori JS
- 🔍 Supabase: Dashboard → Logs per OAuth

## 📝 TODO / Roadmap

### V2.0 Features
- [ ] Cache intelligente per query frequenti
- [ ] Export risultati (CSV, PDF)
- [ ] Dashboard personalizzabili
- [ ] Alerting automatico
- [ ] Multi-sito support
- [ ] API pubblica

### Miglioramenti Tecnici
- [ ] Unit tests
- [ ] CI/CD pipeline
- [ ] Error tracking (Sentry)
- [ ] Performance monitoring
- [ ] Database per storico sessioni

## 🤝 Contribuire

1. Fork del repository
2. Crea feature branch
3. Commit delle modifiche
4. Push e pull request

## 📄 Licenza

Questo progetto è distribuito sotto licenza MIT.

## 🆘 Supporto

- **Email**: info@francisconardi
- **LinkedIn**: [Francisco Nardi](https://www.linkedin.com/in/francisco-nardi-212b338b/)
- **Issues**: GitHub Issues per bug e feature requests

---

Made with ❤️ by Francisco Nardi
