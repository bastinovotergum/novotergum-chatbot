# NOVOTERGUM Chatbot

Ein interaktiver Streamlit-Chatbot für Bewerbungs- und Standortfragen bei NOVOTERGUM.  
Beantwortet automatisch Fragen aus einer kuratierten FAQ-Liste, erkennt Jobs und Standorte.

---

## 🧠 Features

- Semantische FAQ-Erkennung (mit Sentence Transformers)
- Standorterkennung mit XML-Daten
- Jobsuche auf Basis der NOVOTERGUM-Job-Sitemap
- Klar strukturierte Antwortlogik für Patienten, Bewerber und Ärzt:innen

---

## 🚀 Deployment

Das Projekt kann direkt über [Streamlit Cloud](https://share.streamlit.io/deploy) bereitgestellt werden.

---

## 📂 Voraussetzungen

- `chatbot.py`
- `faq/` Ordner mit `*.txt`-Dateien im Format:

Frage: Deine Frage hier
Antwort: Deine Antwort hier

- Optional: `standorte-test.xml` lokal im Projektordner oder öffentlich erreichbar (z. B. per URL)

---

## 🌐 Beispiel-URL

- Öffnungszeiten in Menden:  
  https://novotergum-chatbot-hxkkzdnnwaenchvfueber7.streamlit.app/?frage=Öffnungszeiten%20Menden

- Jobs in Düsseldorf:  
  https://novotergum-chatbot-hxkkzdnnwaenchvfueber7.streamlit.app/?frage=Jobs%20Düsseldorf
---

## 📄 Lizenz

MIT License
