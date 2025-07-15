from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer, util
import xml.etree.ElementTree as ET
import requests
import os
import logging

app = FastAPI()

# CORS (z. B. für Perspective Funnel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot")

# Modell laden
logger.info("Lade Sprachmodell...")
model = SentenceTransformer("paraphrase-albert-small-v2")

# Standortdaten laden
STANDORT_XML_URL = "https://novotergum.de/wp-content/uploads/standorte-data.xml"

def lade_standorte():
    try:
        logger.info("Lade Standortdaten...")
        r = requests.get(STANDORT_XML_URL)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        daten = []

        for eintrag in root.findall("standort"):
            name = eintrag.findtext("title", default="")
            stadt = eintrag.findtext("stadt", default="")
            adresse = f"{eintrag.findtext('strasse', default='')} {eintrag.findtext('postleitzahl', default='')}".strip()
            telefon = eintrag.findtext("telefon", default="")
            maps = f"https://www.google.com/maps/search/?api=1&query={adresse.replace(' ', '+')},{stadt.replace(' ', '+')}"
            daten.append({
                "name": name,
                "stadt": stadt,
                "adresse": adresse,
                "telefon": telefon,
                "maps": maps
            })
        return daten
    except Exception as e:
        logger.error(f"[Fehler beim Laden der Standorte] {e}")
        return []

standorte = lade_standorte()

# FAQs laden
def lade_faq():
    faq_dir = "faq"
    daten = []
    if not os.path.exists(faq_dir):
        logger.warning("FAQ-Ordner fehlt.")
        return daten

    for datei in os.listdir(faq_dir):
        if datei.endswith(".txt"):
            with open(os.path.join(faq_dir, datei), "r", encoding="utf-8") as f:
                frage, antwort = "", ""
                for zeile in f:
                    if zeile.startswith("Frage:"):
                        frage = zeile.replace("Frage:", "").strip()
                    elif zeile.startswith("Antwort:"):
                        antwort = zeile.replace("Antwort:", "").strip()
                        if frage and antwort:
                            daten.append((frage, antwort))
                            frage, antwort = "", ""
    return daten

faq_data = lade_faq()
faq_fragen = [f[0] for f in faq_data]
faq_embeddings = model.encode(faq_fragen, convert_to_tensor=True) if faq_fragen else []

# Healthcheck
@app.get("/")
def status():
    return {"status": "NOVOTERGUM Chatbot API läuft"}

# Chat-Endpunkt
@app.get("/chat")
def chat(frage: str = Query(..., description="Nutzerfrage an den Chatbot")):
    try:
        # Standortlogik
        for s in standorte:
            if s["stadt"].lower() in frage.lower():
                return {
                    "typ": "standort",
                    "antwort": {
                        "name": s["name"],
                        "adresse": s["adresse"],
                        "telefon": s["telefon"],
                        "maps": s["maps"]
                    }
                }

        # FAQ-Logik
        if not faq_embeddings:
            return {"typ": "fehler", "antwort": "Keine FAQ-Daten verfügbar."}

        frage_embedding = model.encode(frage, convert_to_tensor=True)
        scores = util.cos_sim(frage_embedding, faq_embeddings)  # → Tensor mit Shape [1, N]
        scores = scores[0]  # macht daraus 1D-Tensor der Länge N

        best_idx = int(scores.argmax())
        best_score = float(scores[best_idx])

        if best_score > 0.6:
            return {
                "typ": "faq",
                "frage": faq_data[best_idx][0],
                "antwort": faq_data[best_idx][1],
                "score": round(best_score, 3)
            }

        # Kein Treffer
        return {"typ": "unbekannt", "antwort": "Ich konnte leider nichts Passendes finden."}

    except Exception as e:
        logger.exception("Fehler im Chat-Endpunkt")
        return {"typ": "fehler", "antwort": str(e)}
