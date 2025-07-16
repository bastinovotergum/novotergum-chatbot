import streamlit as st
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer, util
import xml.etree.ElementTree as ET
import requests
import os
import logging
import re
from rapidfuzz import fuzz, process

# --- Initialisierung ---
try:
    query_params = st.query_params
    frage_von_url = query_params.get("frage", [""])[0]
except Exception:
    frage_von_url = ""

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@st.cache_resource
def lade_modell():
    return SentenceTransformer('all-MiniLM-L6-v2')

model = lade_modell()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot")

# --- Hilfsfunktionen ---
def frage_betrifft_standort(user_input):
    stichworte = [" in ", " bei ", "nähe", "wo ist", "standort", "zentrum", "praxis", "adresse", "map", "google maps"]
    return any(w in user_input.lower() for w in stichworte)

def frage_betrifft_job(user_input):
    job_stichworte = ["job", "jobs", "stelle", "stellen", "bewerbung", "bewerben", "karriere", "jobangebot", "jobangebote", "stellenangebot", "stellenangebote", "ausschreibung"]
    return any(w in user_input.lower() for w in job_stichworte)

def normalisiere(text):
    return text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")

# --- Standortdaten laden ---
STANDORT_XML_URL = "https://novotergum.de/wp-content/uploads/standorte-data.xml"
@st.cache_resource(show_spinner=False)
def lade_standorte():
    try:
        r = requests.get(STANDORT_XML_URL)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        daten = []

        for eintrag in root.findall("standort"):
            name = eintrag.findtext("title", default="")
            stadt = eintrag.findtext("stadt", default="")
            adresse = f"{eintrag.findtext('strasse', '')} {eintrag.findtext('postleitzahl', '')}".strip()
            telefon = eintrag.findtext("telefon", default="")
            url = eintrag.findtext("standort_url", default="")
            status = eintrag.findtext("opening_status", default="")
            region = eintrag.findtext("region_code", default="")
            beschreibung = eintrag.findtext("description", default="")
            titel = eintrag.findtext("title", default="")
            primary_category = (eintrag.findtext("primary_category") or "").lower()

            maps = f"https://www.google.com/maps/search/?api=1&query={adresse.replace(' ', '+')},{stadt.replace(' ', '+')}"

            zeiten_liste = []
            wochentage_deutsch = {"Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch", "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag", "Sunday": "Sonntag"}
            for hours in eintrag.findall(".//openingHoursSpecification/hours"):
                tag = hours.findtext("dayOfWeek", "")
                von = hours.findtext("opens", "")
                bis = hours.findtext("closes", "")
                if tag and von and bis:
                    tag_de = wochentage_deutsch.get(tag, tag)
                    zeiten_liste.append(f"{tag_de}: {von}–{bis}")

            zeiten = " | ".join(zeiten_liste) if zeiten_liste else "Nicht verfügbar"
            suchbegriffe = set(re.split(r"[\s\-]+", f"{name} {adresse} {stadt} {titel}".lower()))

            daten.append({
                "name": name,
                "stadt": stadt,
                "adresse": adresse,
                "telefon": telefon,
                "url": url,
                "status": status,
                "region": region,
                "beschreibung": beschreibung,
                "titel": titel,
                "zeiten": zeiten,
                "suchbegriffe": suchbegriffe,
                "primary_category": primary_category,
                "maps": maps
            })

        return daten
    except Exception as e:
        logger.error(f"[Fehler beim Laden der Standorte] {e}")
        return []

standorte_data = lade_standorte()

def finde_passenden_standort(user_input):
    user_input_lower = user_input.lower()
    kandidaten = []
    for eintrag in standorte_data:
        score = max(
            fuzz.partial_ratio(user_input_lower, eintrag["stadt"].lower()),
            fuzz.partial_ratio(user_input_lower, eintrag["name"].lower()),
            fuzz.partial_ratio(user_input_lower, eintrag.get("primary_category", ""))
        )
        if score > 75:
            kandidaten.append((eintrag, score))
    kandidaten.sort(key=lambda x: x[1], reverse=True)
    return kandidaten[0][0] if kandidaten else None

# --- Job-Sitemap ---
JOB_SITEMAP_URL = "https://novotergum.de/novotergum_job-sitemap.xml"
@st.cache_data(show_spinner=False)
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
                if slug == "jobs": continue
                teile = slug.split("-")
                if teile:
                    ort = teile[-1].lower()
                    job_urls.setdefault(ort, []).append(url)
        return job_urls
    except Exception as e:
        logger.error(f"[Fehler beim Laden der Job-URLs] {e}")
        return {}

job_urls = lade_job_urls()

def finde_jobs_fuer_ort(frage):
    frage_lower = frage.lower()
    orte = list(job_urls.keys())
    bester_ort, score, _ = process.extractOne(frage_lower, orte, scorer=fuzz.partial_ratio)
    if score >= 80:
        return job_urls[bester_ort]
    return [u for jobliste in job_urls.values() for u in jobliste]

def filtere_jobs_nach_beruf(job_urls, frage):
    frage_norm = normalisiere(frage)
    relevante_berufe = {
        "physiotherapeut": ["physiotherapeut", "physiotherapeutin", "physiotherapie", "physio", "kinderphysiotherapeut", "mt", "kgg"],
        "logopäde": ["logopäde", "logopädin", "logopaedie", "logopädie", "sprachtherapie"],
        "ergotherapeut": ["ergotherapeut", "ergotherapeutin", "ergotherapie", "ergo"],
        "rezeption": ["rezeption", "empfang"],
        "leitung": ["leitung", "zentrumsmanager", "fachleitung"],
    }
    gesuchte_begriffe = set()
    for begriffsliste in relevante_berufe.values():
        for b in begriffsliste:
            if b in frage_norm:
                gesuchte_begriffe.update(begriffsliste)
    if not gesuchte_begriffe:
        return job_urls
    def url_passt(url):
        slug = normalisiere(url.rstrip("/").split("/")[-1])
        return any(b in slug for b in gesuchte_begriffe)
    return [url for url in job_urls if url_passt(url)]

def extrahiere_jobtitel(url):
    slug = url.rstrip("/").split("/")[-1]
    teile = slug.split("-")
    blacklist = {"m", "w", "d", "in", "fuer", "für", "job"}
    highlight = {"physiotherapeut": "Physiotherapeut", "leitung": "Leitung", "empfang": "Empfang", "rezeption": "Rezeption"}
    titel = [highlight.get(t, t.capitalize()) for t in teile if t not in blacklist]
    return " ".join(titel)

# --- FAQ ---
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

# --- API Endpoints ---
@app.get("/")
def status():
    return {"status": "OK"}

@app.get("/chat")
def chat(frage: str = Query(...)):
    try:
        frage_lc = frage.lower()
        standort = finde_passenden_standort(frage)
        if any(w in frage_lc for w in ["adresse", "wo ist", "standort", "zentrum", "praxis"]):
            if standort:
                return {"typ": "standort", "antwort": standort}

        if faq_embeddings is not None:
            frage_embedding = model.encode(frage, convert_to_tensor=True)
            scores = util.cos_sim(frage_embedding, faq_embeddings)
            best_idx = scores[0].argmax().item()
            best_score = scores[0][best_idx].item()
            if best_score > 0.6:
                return {"typ": "faq", "frage": faq_data[best_idx][0], "antwort": faq_data[best_idx][1], "score": round(best_score, 3)}

        if any(w in frage_lc for w in ["job", "bewerbung", "karriere", "stellen"]):
            jobs = finde_jobs_fuer_ort(frage)
            return {"typ": "job", "anzahl": len(jobs), "jobs": [{"url": j, "titel": extrahiere_jobtitel(j)} for j in jobs[:5]]}

        return {"typ": "unbekannt", "antwort": "Ich konnte leider nichts Passendes finden."}

    except Exception as e:
        logger.exception("Fehler im Chat-Endpunkt")
        return {"typ": "fehler", "antwort": str(e)}
