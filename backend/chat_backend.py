from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer, util
from rapidfuzz import process, fuzz
import xml.etree.ElementTree as ET
import requests
import os
import logging

app = FastAPI()

# CORS
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

# Standort-Intent erkennen
def hat_standort_intent(frage: str):
    standort_keywords = [
        "adresse", "wo ist", "wo finde ich", "praxis", "zentrum", "öffnungszeiten",
        "wann geöffnet", "telefon", "nummer", "kontakt", "anfahrt", "google maps", "map"
    ]
    return any(kw in frage.lower() for kw in standort_keywords)

# Fuzzy-Matching für Standorte
def finde_passenden_standort(frage: str):
    frage_lc = frage.lower()
    kandidaten = []

    for s in standorte:
        name = s["name"].lower()
        stadt = s["stadt"].lower()
        score_name = fuzz.partial_ratio(frage_lc, name)
        score_stadt = fuzz.partial_ratio(frage_lc, stadt)
        score = max(score_name, score_stadt)
        kandidaten.append((s, score))

    kandidaten.sort(key=lambda x: x[1], reverse=True)
    if kandidaten and kandidaten[0][1] >= 75:
        return kandidaten[0][0]
    return None

# FAQ laden
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
faq_embeddings = model.encode(faq_fragen, convert_to_tensor=True) if faq_fragen else None

# Job-URLs laden
def lade_job_urls():
    try:
        sitemap_url = "https://novotergum.de/novotergum_job-sitemap.xml"
        logger.info(f"Lade Job-Sitemap von {sitemap_url}...")
        r = requests.get(sitemap_url)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        urls = [url.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc") for url in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url")]
        return [u for u in urls if u]
    except Exception as e:
        logger.error(f"[Fehler beim Laden der Job-URLs] {e}")
        return []

job_urls = lade_job_urls()

# Healthcheck
@app.get("/")
def status():
    return {"status": "NOVOTERGUM Chatbot API läuft"}

# Chat-Endpunkt
@app.get("/chat")
def chat(frage: str = Query(..., description="Nutzerfrage an den Chatbot")):
    try:
        # 1. Standortlogik (Intent + Fuzzy)
        if hat_standort_intent(frage):
            standort = finde_passenden_standort(frage)
            if standort:
                return {
                    "typ": "standort",
                    "antwort": {
                        "name": standort["name"],
                        "adresse": standort["adresse"],
                        "telefon": standort["telefon"],
                        "maps": standort["maps"]
                    }
                }

        # 2. FAQ
        if faq_embeddings is None or faq_embeddings.shape[0] == 0:
            return {"typ": "fehler", "antwort": "Keine FAQ-Daten verfügbar."}

        frage_embedding = model.encode(frage, convert_to_tensor=True)
        scores = util.cos_sim(frage_embedding, faq_embeddings)
        best_idx = scores[0].argmax().item()
        best_score = scores[0][best_idx].item()

        if best_score > 0.6:
            return {
                "typ": "faq",
                "frage": faq_data[best_idx][0],
                "antwort": faq_data[best_idx][1],
                "score": round(best_score, 3)
            }

        return {"typ": "unbekannt", "antwort": "Ich konnte leider nichts Passendes finden."}

    except Exception as e:
        logger.exception("Fehler im Chat-Endpunkt")
        return {"typ": "fehler", "antwort": str(e)}
