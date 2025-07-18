# ChatGSC - Conversa con i dati di Google Search Console

## 🏗️ Struttura del Progetto

Il progetto è ora organizzato in moduli separati per una migliore manutenibilità e scalabilità:

```
chatgsc/
├── app.py                 # File principale dell'applicazione
├── gsc_direct.py         # Modalità Google Search Console Diretta
├── bigquery_mode.py      # Modalità BigQuery Avanzata
├── requirements.txt      # Dipendenze Python
└── README.md            # Documentazione
```

## 📁 Descrizione dei File

### `app.py` - File Principale
- **Funzione**: Entry point dell'applicazione
- **Responsabilità**:
  - Configurazione Streamlit e OAuth
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


## 🚀 Come Eseguire

### 1. Installazione Dipendenze
```bash
pip install -r requirements.txt
```

### 2. Configurazione Secrets
Copia e rinomina `/.streamlit/secrets.toml.example` in `.streamlit/secrets.toml` e modifica i valori:
```toml
google_oauth_client_id = "your-google-client-id"
google_oauth_client_secret = "your-google-client-secret"
app_url = "https://your-app-url.streamlit.app"
```

### 3. Avvio Applicazione
```bash
streamlit run app.py
```

## 🔧 Configurazione

### Google Cloud Setup
1. Crea progetto su [Google Cloud Console](https://console.cloud.google.com)
2. Abilita API:
   - Google Search Console API
   - BigQuery API (per modalità avanzata)
   - Vertex AI API (per modalità avanzata)
3. Crea OAuth 2.0 Client ID
4. Aggiungi il redirect URI dell'app (es. `https://your-app-url.streamlit.app`)

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
User → Google OAuth → App
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
- ✅ Verifica redirect URI e secrets di Streamlit

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
