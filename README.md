# NOVOTERGUM Chatbot

Ein interaktiver Chatbot für Bewerbungs- und Standortfragen bei NOVOTERGUM.  
Erkennt Bewerbungsanliegen, Standorte, Berufsgruppen und gibt passende Antworten auf häufige Fragen – eingebunden über Streamlit oder als Web-Widget.

---

## 🧠 Features

- ✅ Semantische FAQ-Erkennung (Sentence Transformers)
- ✅ Standorterkennung mit XML-Daten (inkl. Google Maps Link & Öffnungszeiten)
- ✅ Berufserkennung & passende Joblinks (aus Job-Sitemap generiert)
- ✅ Kontextsensitives Fuzzy-Matching für Orte, Berufsbezeichnungen & Kategorien
- ✅ Chat-Widget-Integration für die NOVOTERGUM Website
- ✅ API-Endpunkt für Einbindung in externe Webseiten (z. B. Bewerbungsfunnel, Intercom, BotFront)

---

## 🧩 Komponenten

| Komponente            | Beschreibung |
|-----------------------|--------------|
| `chatbot.py`          | Streamlit-App mit kompletter UI-Logik |
| `chat_backend.py`     | FastAPI-Backend mit `/chat`-Endpunkt zur API-Nutzung |
| `faq/`                | Ordner mit kuratierten Fragen & Antworten (jeweils `.txt`) |
| `standorte-test.xml`  | XML-Feed aller NOVOTERGUM-Zentren (Adresse, Öffnungszeiten etc.) |

---

## 💬 Beispielanfragen (Direkt-Links)

| Thema                    | Link |
|--------------------------|------|
| Öffnungszeiten Menden    | [Link](https://novotergum-chatbot.streamlit.app/?frage=Öffnungszeiten%20Menden) |
| Jobs in Düsseldorf       | [Link](https://novotergum-chatbot.streamlit.app/?frage=Jobs%20Düsseldorf) |
| Bewerbungsprozess        | [Link](https://novotergum-chatbot.streamlit.app/?frage=Wie%20läuft%20der%20Bewerbungsprozess%20ab?) |

---

## 🚀 Deployment-Optionen

### 🔹 1. Streamlit Cloud

Einfach über [https://share.streamlit.io](https://share.streamlit.io) deployen  
→ Nutze dafür `chatbot.py` als Einstiegspunkt.

### 🔹 2. FastAPI + Render (empfohlen für Widget-Einbindung)

Nutze `chat_backend.py` als API-Server (POST `/chat`).  
Kann via [https://render.com](https://render.com) kostenlos gehostet werden.  
Siehe `render.yaml` für Konfiguration.

**Startbefehl z. B.:**

```bash
uvicorn chat_backend:app --host 0.0.0.0 --port 10000
