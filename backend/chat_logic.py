import streamlit as st
from chat_backend_api import run_chatbot, lade_standorte, lade_job_urls

# --- Standorte & Jobs einmal laden ---
standorte = lade_standorte("standorte-test.xml")
job_urls = lade_job_urls()

# --- UI Konfiguration ---
st.set_page_config(page_title="NOVOTERGUM Chatbot")
st.title("NOVOTERGUM Chatbot 😊")
st.caption("Letztes Update: 2025-07-13")

# --- Frage aus URL oder UI ---
params = st.query_params
vorgegebene_frage = params.get("frage", "")
frage = st.text_input("Stelle deine Frage:", value=vorgegebene_frage)

# --- Antwort generieren ---
if frage:
    antwort = run_chatbot(frage, standorte, job_urls)
    st.markdown("**Antwort:**")
    st.markdown(antwort)
else:
    st.info("Bitte gib eine Frage ein.")
