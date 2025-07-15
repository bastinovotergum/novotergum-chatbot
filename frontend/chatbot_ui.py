import streamlit as st
import requests

# Backend-URL eintragen (z. B. von Railway)
BACKEND_URL = "https://novotergum-chatbot-production.up.railway.app"

st.set_page_config(page_title="NOVOTERGUM Chatbot")
st.title("NOVOTERGUM Chatbot 🤖")
st.caption("Frage etwas zu Standorten, Bewerbungen oder häufigen Fragen.")

frage = st.text_input("Deine Frage:")

if frage:
    try:
        with st.spinner("Denke nach..."):
            r = requests.get(f"{BACKEND_URL}/chat", params={"frage": frage})
            r.raise_for_status()
            daten = r.json()

        typ = daten.get("typ")
        if typ == "standort":
            antw = daten["antwort"]
            st.markdown("### 📍 Standort")
            st.markdown(f"**{antw['name']}**")
            st.markdown(f"📍 {antw['adresse']}")
            st.markdown(f"📞 [{antw['telefon']}](tel:{antw['telefon'].replace(' ', '')})")
            st.markdown(f"[🗺️ Google Maps öffnen]({antw['maps']})")

        elif typ == "faq":
            st.markdown("### 💡 Antwort")
            st.markdown(f"**{daten['frage']}**")
            st.markdown(daten["antwort"])

        elif typ == "unbekannt":
            st.warning(daten["antwort"])

        elif typ == "fehler":
            st.error("Fehler: " + daten["antwort"])

    except Exception as e:
        st.error(f"Fehler beim Abrufen der Antwort: {e}")
