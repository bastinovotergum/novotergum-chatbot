# chat_logic.py
import os
import re
import requests
import xml.etree.ElementTree as ET
from sentence_transformers import SentenceTransformer, util
from rapidfuzz import fuzz, process

model = SentenceTransformer("all-MiniLM-L6-v2")

# --- FAQ laden ---
def lade_faq_data(pfad="faq"):
    faq_data = []
    for filename in os.listdir(pfad):
        filepath = os.path.join(pfad, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            frage, antwort = "", ""
            for line in f:
                if line.startswith("Frage:"):
                    frage = line.replace("Frage:", "").strip()
                elif line.startswith("Antwort:"):
                    antwort = line.replace("Antwort:", "").strip()
                    if frage and antwort:
                        faq_data.append((frage, antwort))
                        frage, antwort = "", ""
    return faq_data

faq_data = lade_faq_data()
faq_questions = [q for q, _ in faq_data]
faq_embeddings = model.encode(faq_questions, convert_to_tensor=True) if faq_data else None

# --- Dummy-Standorte und Jobs (als Platzhalter) ---
def lade_standorte(xml_path):
    return []  # Hier echte XML-Ladefunktion rein

def lade_job_urls():
    return {}  # Hier echte Sitemap-Ladefunktion rein

# --- Intent-Erkennung ---
def frage_betrifft_job(text):
    return any(w in text.lower() for w in ["job", "bewerbung", "karriere"])

def frage_hat_standort_intent(text):
    return any(w in text.lower() for w in ["standort", "adresse", "zentrum"])

# --- Antwortlogik ---
def run_chatbot(message: str, standorte: list, job_urls: dict) -> dict:
    # Standortantwort bei Standortfrage
    if frage_hat_standort_intent(message):
        # Standorte durchsuchen (Dummy)
        return {
            "typ": "standort",
            "antwort": "Standort-Antwort (hier Logik implementieren)",
            "score": 1.0
        }

    # FAQ-Antwort bei hohem Score
    if faq_embeddings is not None:
        frage_embedding = model.encode(message, convert_to_tensor=True)
        scores = util.cos_sim(frage_embedding, faq_embeddings)
        best_match_idx = scores.argmax().item()
        best_score = scores[0][best_match_idx].item()

        if best_score > 0.6:
            return {
                "typ": "faq",
                "frage": faq_data[best_match_idx][0],
                "antwort": faq_data[best_match_idx][1],
                "score": round(best_score, 2)
            }

    # Jobantwort
    if frage_betrifft_job(message):
        return {
            "typ": "job",
            "antwort": "Jobs-Antwort (hier Logik implementieren)",
            "score": 1.0
        }

    return {
        "typ": "fallback",
        "antwort": "Ich konnte leider keine passende Antwort finden.",
        "score": 0.0
    }
