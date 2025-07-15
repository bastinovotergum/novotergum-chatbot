import streamlit as st
import requests

st.set_page_config(page_title="NOVOTERGUM Chatbot")
st.title("NOVOTERGUM Chatbot")

frage = st.text_input("Was möchtest du wissen?", "")

if frage:
    try:
        r = requests.get("https://novotergum-chatbot-production.up.railway.app/chat", params={"frage": frage})
        r.raise_for_status()
        data = r.json()

        if data["typ"] == "faq":
            st.markdown(f"**Antwort:** {data['antwort']}")
        elif data["typ"] == "standort":
            s = data["antwort"]
            st.markdown(f"📍 **{s['adresse']}**\n📞 [{s['telefon']}](tel:{s['telefon']})\n[🌍 Google Maps]({s['maps']})")
        else:
            st.warning(data["antwort"])
    except Exception as e:
        st.error(f"Fehler: {e}")
