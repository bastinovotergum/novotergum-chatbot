from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer, util
import xml.etree.ElementTree as ET
import requests
import os
import logging
import re
from rapidfuzz import fuzz, process
from datetime import datetime, timedelta

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot")

model = SentenceTransformer("all-MiniLM-L6-v2")

STANDORT_XML_URL = "https://novotergum.de/wp-content/uploads/standorte-data.xml"
JOB_SITEMAP_URL = "https://novotergum.de/novotergum_job-sitemap.xml"

# ---------------------- HILFSFUNKTIONEN ----------------------
def normalisiere(text):
    return text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")

# ---------------------- STANDORTE ----------------------
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
            adresse = f"{eintrag.findtext('strasse', '')} {eintrag.findtext('postleitzahl', '')}".strip()
            telefon = eintrag.findtext("telefon", default="")
            primary_category = (eintrag.findtext("primary_category") or "").lower()
            maps = f"https://www.google.com/maps/search/?api=1&query={adresse.replace(' ', '+')},{stadt.replace(' ', '+')}"
            daten.append({
                "name": name,
                "stadt": stadt,
                "adresse": adresse,
                "telefon": telefon,
                "maps": maps,
                "primary_category": primary_category,
            })
        return daten
    except Exception as e:
        logger.error(f"[Fehler beim Laden der Standorte] {e}")
        return []

standorte = lade_standorte()

def finde_passenden_standort(frage):
    frage_lc = frage.lower()
    kandidaten = []
    for s in standorte:
        kombiniert = f"{s['stadt']} {s['name']} {s['adresse']}".lower()
        score = fuzz.partial_ratio(frage_lc, kombiniert)
        if score > 70:
            kandidaten.append((s, score))

    kandidaten.sort(key=lambda x: x[1], reverse=True)
    return kandidaten[0][0] if kandidaten else None

# ---------------------- JOBS ----------------------
job_urls_cache = {}
job_urls_last_loaded = datetime.min

def lade_job_urls():
    global job_urls_cache, job_urls_last_loaded
    if datetime.now() - job_urls_last_loaded < timedelta(hours=6):
        return job_urls_cache

    try:
        logger.info("Lade Job-Sitemap...")
        r = requests.get(JOB_SITEMAP_URL)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        neue_urls = {}
        for url_node in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
            loc = url_node.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None:
                url = loc.text.strip()
                slug = url.rstrip("/").split("/")[-1]
                if slug == "jobs":
                    continue
                teile = slug.split("-")
                if teile:
                    ort = teile[-1].lower()
                    neue_urls.setdefault(ort, []).append(url)
        job_urls_cache = neue_urls
        job_urls_last_loaded = datetime.now()
        return job_urls_cache
    except Exception as e:
        logger.error(f"[Fehler beim Laden der Job-URLs] {e}")
        return job_urls_cache

def finde_jobs_fuer_ort(frage):
    frage_lower = frage.lower()
    job_urls = lade_job_urls()
    orte = list(job_urls.keys())

    # Ort extrahieren
    bester_ort, score, _ = process.extractOne(frage_lower, orte, scorer=fuzz.partial_ratio)
    if score >= 80:
        urls = job_urls[bester_ort]
    else:
        urls = [u for jobliste in job_urls.values() for u in jobliste]

    # Berufsfilter direkt aus Frage ableiten
    berufsfilter = {
        "physio": ["physio", "physiotherapeut"],
        "ergo": ["ergo", "ergotherapie", "ergotherapeut"],
        "logo": ["logo", "logopaed", "sprachtherapeut"],
        "sport": ["sport", "trainer"],
        "rezeption": ["rezept", "empfang", "service"],
        "arzt": ["arzt", "mediziner"],
    }

    relevante_keys = [k for k, v in berufsfilter.items() if any(w in frage_lower for w in v)]
    if relevante_keys:
        urls = [
            u for u in urls
            if any(k in u.lower() for key in relevante_keys for k in berufsfilter[key])
        ]

    return urls

def extrahiere_jobtitel(url):
    slug = url.rstrip("/").split("/")[-1]
    teile = [t for t in slug.split("-") if not t.isdigit()]
    return " ".join(t.capitalize() for t in teile if t not in ["m", "w", "d"])

# ---------------------- FAQ ----------------------
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

# ---------------------- ENDPOINTS ----------------------
@app.get("/")
def status():
    return {"status": "OK"}

@app.get("/chat")
def chat(frage: str = Query(...)):
    try:
        frage_lc = frage.lower()

        # Standortlogik
        standort = finde_passenden_standort(frage)
        if any(w in frage_lc for w in ["adresse", "wo ist", "standort", "zentrum", "praxis"]):
            if standort:
                return {
                    "typ": "standort",
                    "antwort": standort
                }

        # FAQ
        if faq_embeddings is not None:
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

        # Jobs
        if any(w in frage_lc for w in ["job", "bewerbung", "karriere", "stellen"]):
            jobs = finde_jobs_fuer_ort(frage)
            return {
                "typ": "job",
                "anzahl": len(jobs),
                "jobs": [{"url": j, "titel": extrahiere_jobtitel(j)} for j in jobs[:5]]
            }

        return {"typ": "unbekannt", "antwort": "Ich konnte leider nichts Passendes finden."}

    except Exception as e:
        logger.exception("Fehler im Chat-Endpunkt")
        return {"typ": "fehler", "antwort": str(e)}
