from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer, util
import requests
import xml.etree.ElementTree as ET
from rapidfuzz import fuzz, process
import os
import re
import logging

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

# ---------- FAQ ----------
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
faq_questions = [f[0] for f in faq_data]
faq_embeddings = model.encode(faq_questions, convert_to_tensor=True) if faq_questions else None

# ---------- STANDORTE ----------
def lade_standorte():
    try:
        r = requests.get(STANDORT_XML_URL)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        standorte = []

        for s in root.findall("standort"):
            name = s.findtext("title", "")
            stadt = s.findtext("stadt", "")
            adresse = f"{s.findtext('strasse', '')} {s.findtext('postleitzahl', '')}".strip()
            telefon = s.findtext("telefon", "")
            kategorien = [cat.text.lower() for cat in s.findall("primary_category") if cat.text]
            maps = f"https://www.google.com/maps/search/?api=1&query={adresse.replace(' ', '+')},{stadt.replace(' ', '+')}"
            zeiten = []
            for h in s.findall(".//openingHoursSpecification/hours"):
                tag = h.findtext("dayOfWeek", "")
                von = h.findtext("opens", "")
                bis = h.findtext("closes", "")
                if tag and von and bis:
                    zeiten.append(f"{tag}: {von}–{bis}")
            standorte.append({
                "name": name,
                "stadt": stadt,
                "adresse": adresse,
                "telefon": telefon,
                "maps": maps,
                "zeiten": " | ".join(zeiten) if zeiten else "Nicht verfügbar",
                "primary_category": ", ".join(kategorien),
            })
        return standorte
    except Exception as e:
        logger.error(f"Fehler beim Laden der Standorte: {e}")
        return []

standorte = lade_standorte()

def finde_passenden_standort(frage: str):
    frage_lc = frage.lower()
    kandidaten = []

    for s in standorte:
        felder = [
            s.get("stadt", ""),
            s.get("adresse", ""),
            s.get("name", ""),
            s.get("primary_category", ""),
        ]
        suchtext = " ".join(felder).lower()
        score = fuzz.token_set_ratio(frage_lc, suchtext)

        if any(k in frage_lc and k in suchtext for k in ["ergo", "physio", "logo"]):
            score += 10

        if score > 70:
            kandidaten.append((s, score))

    kandidaten.sort(key=lambda x: x[1], reverse=True)
    return kandidaten[0][0] if kandidaten else None

# ---------- JOBS ----------
def lade_job_urls():
    try:
        r = requests.get(JOB_SITEMAP_URL)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        job_urls = {}
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
                    job_urls.setdefault(ort, []).append(url)
        return job_urls
    except Exception as e:
        logger.error(f"Fehler beim Laden der Job-URLs: {e}")
        return {}

job_urls = lade_job_urls()

def finde_jobs_fuer_ort(frage):
    frage_lower = frage.lower()
    job_urls = lade_job_urls()
    orte = list(job_urls.keys())

    bester_ort, score, _ = process.extractOne(frage_lower, orte, scorer=fuzz.partial_ratio)
    if score >= 80:
        urls = job_urls[bester_ort]
    else:
        urls = [u for jobliste in job_urls.values() for u in jobliste]

    berufsfilter = {
        "physio": ["physio", "physiotherapeut"],
        "ergo": ["ergo", "ergotherapie", "ergotherapeut"],
        "logo": ["logo", "logopaed", "sprachtherapeut", "logopäde"],
        "sport": ["sport", "trainer"],
        "rezeption": ["rezept", "empfang", "service"],
        "arzt": ["arzt", "mediziner"],
    }

    relevante_keys = [k for k, terms in berufsfilter.items() if any(term in frage_lower for term in terms)]

    if relevante_keys:
        urls = [
            u for u in urls
            if any(any(term in u.lower() for term in berufsfilter[k]) for k in relevante_keys)
        ]

    return urls

def extrahiere_jobtitel(url):
    slug = url.rstrip("/").split("/")[-1]
    teile = [t for t in slug.split("-") if not t.isdigit()]
    blacklist = {"m", "w", "d", "in"}
    return " ".join(t.capitalize() for t in teile if t not in blacklist)

# ---------- ENDPOINT ----------
@app.get("/")
def status():
    return {"status": "OK"}

@app.get("/chat")
def chat(frage: str = Query(...)):
    frage_lc = frage.lower()

    # Standortlogik
    if any(w in frage_lc for w in ["adresse", "wo ist", "standort", "zentrum", "praxis", "öffnungszeiten", "zeiten", "telefon"]):
        standort = finde_passenden_standort(frage)
        if standort:
            antwort = ""
            if "zeit" in frage_lc or "geöffnet" in frage_lc or "öffnungs" in frage_lc:
                antwort = f"🕓 Öffnungszeiten: {standort['zeiten']}"
            elif "telefon" in frage_lc:
                antwort = f"📞 {standort['telefon']}"
            elif "adresse" in frage_lc or "wo ist" in frage_lc:
                antwort = f"🏢 {standort['adresse']}, {standort['stadt']}"
            else:
                antwort = (
                    f"📍 {standort['name']}, {standort['stadt']}\n"
                    f"🏢 {standort['adresse']}\n"
                    f"📞 {standort['telefon']}\n"
                    f"🕓 {standort['zeiten']}\n"
                    f"🗺️ [Google Maps]({standort['maps']})"
                )
            return {"typ": "standort", "antwort": antwort}

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
                "score": round(best_score, 3),
            }

    # Jobs
    if any(w in frage_lc for w in ["job", "bewerbung", "karriere", "stellen"]):
        jobs = finde_jobs_fuer_ort(frage)
        return {
            "typ": "job",
            "anzahl": len(jobs),
            "jobs": [{"url": j, "titel": extrahiere_jobtitel(j)} for j in jobs[:5]],
        }

    return {"typ": "unbekannt", "antwort": "Ich konnte leider nichts Passendes finden."}
