from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer, util
import requests
import xml.etree.ElementTree as ET
from rapidfuzz import fuzz, process
from functools import lru_cache
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

standort_keywords = [
    "adresse", "wo ist", "standort", "zentrum", "praxis", "karte", "google maps",
    "telefon", "nummer", "anrufen", "sprechzeiten", "kontakt", "öffnungszeiten",
    "geöffnet", "offen"
]
job_keywords = ["job", "bewerbung", "karriere", "stellen", "stelle", "arbeiten", "arbeit", "position"]

berufsfilter = {
    "physio": [
        "physio", "physiotherapeut", "physiotherapie", "physiotherapeutin", "krankengymnast",
        "krankengymnastik", "kgg", "kg", "mt", "mld", "zns"
    ],
    "ergo": [
        "ergo", "ergotherapie", "ergotherapeut", "ergotherapeutin", "ergotherapeutische behandlung"
    ],
    "logo": [
        "logo", "logopäde", "logopädin", "logopäd", "logopaede", "logopaedie",
        "sprachtherapie", "sprachtherapeut", "sprachtherapeutin", "sprachheiltherapie"
    ],
    "kinder": [
        "kinderphysio", "kinderphysiotherapeut", "pädiatrie", "kindertherapie", "kind", "kinderbehandlung"
    ],
    "leitung": [
        "leitung", "bereichsleitung", "teamleitung", "fachliche leitung", "leitende", "standortleitung"
    ],
    "sport": [
        "sport", "trainer", "rehatrainer", "athletik", "sporttherapie", "personal trainer", "fitnesstrainer"
    ],
    "rezeption": [
        "rezeption", "rezept", "empfang", "service", "terminvergabe", "front office", "praxisorganisation"
    ],
    "arzt": [
        "arzt", "ärztin", "mediziner", "orthopäde", "facharzt", "unfallarzt", "arztpraxis"
    ]
}

def bestimme_fragetyp(frage_lc: str):
    def erste_position(keywords):
        pos = [frage_lc.find(w) for w in keywords if w in frage_lc]
        return min(pos) if pos else float('inf')

    pos_standort = erste_position(standort_keywords)
    pos_job = erste_position(job_keywords)

    if pos_standort < pos_job:
        return "standort"
    elif pos_job < pos_standort:
        return "job"
    else:
        return "unentschieden"

def lade_standorte():
    try:
        r = requests.get(STANDORT_XML_URL)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        standorte = []

        for s in root.findall("standort"):
            stadt_roh = s.findtext("stadt", "")
            stadt = re.sub(r"\s*\(.*?\)", "", stadt_roh).strip()
            adresse = f"{s.findtext('strasse', '')} {s.findtext('postleitzahl', '')}".strip()
            telefon = s.findtext("telefon", "")
            kategorie = s.findtext("primary_category", "").lower()
            title = s.findtext("title", "").strip()
            url = s.findtext("standort_url", "").strip()

            # Öffnungszeiten vollständig extrahieren
            zeiten_raw = []
            zeiten_text = []
            for h in s.findall(".//openingHoursSpecification/hours"):
                tag = h.findtext("dayOfWeek", "")
                von = h.findtext("opens", "")
                bis = h.findtext("closes", "")
                if tag and von and bis:
                    zeiten_raw.append({
                        "tag": tag,
                        "von": von,
                        "bis": bis
                    })
                    zeiten_text.append(f"{tag}: {von}–{bis}")

            # Google Maps Link
            maps = f"https://www.google.com/maps/search/?api=1&query={adresse.replace(' ', '+')},{stadt.replace(' ', '+')}"

            # Slugteile aus URL
            slugteile = []
            if url:
                slug_raw = url.rstrip("/").split("/")[-1]
                slugteile = slug_raw.replace("-", " ").split()

            # Aliases auf Basis von Stadt, Titel, Slug
            aliases = list(set([
                stadt.lower(),
                stadt.lower().replace("-", " "),
                title.lower(),
                title.lower().replace("-", " ")
            ] + slugteile))

            # Leere Strings filtern
            aliases = [a.strip() for a in aliases if a.strip()]

            standorte.append({
                "store_code": s.findtext("store_code", ""),
                "stadt": stadt_roh.strip(),
                "strasse": s.findtext("strasse", ""),
                "postleitzahl": s.findtext("postleitzahl", ""),
                "telefon": telefon,
                "adresse": adresse,
                "maps": maps,
                "standort_url": url,
                "opening_status": s.findtext("opening_status", ""),
                "region_code": s.findtext("region_code", ""),
                "language_code": s.findtext("language_code", ""),
                "title": title,
                "description": s.findtext("description", ""),
                "primary_category": kategorie,
                "geo": {
                    "latitude": s.findtext("geo/latitude", ""),
                    "longitude": s.findtext("geo/longitude", "")
                },
                "zeiten": " | ".join(zeiten_text) if zeiten_text else "Nicht verfügbar",
                "zeiten_raw": zeiten_raw,
                "title_lower": title.lower(),
                "slugteile": slugteile,
                "aliases": aliases
            })

        return standorte
    except Exception as e:
        logger.error(f"Fehler beim Laden der Standorte: {e}")
        return []

standorte = []  # global

@app.on_event("startup")
def init_standorte():
    global standorte
    standorte = lade_standorte()
    logger.info(f"{len(standorte)} Standorte erfolgreich geladen.")

def finde_passenden_standort(frage: str):
    frage_lc = frage.lower()
    frage_clean = frage_lc.replace("-", " ").replace(",", " ").strip()
    kandidaten = []

    for s in standorte:
        # Basistext für Fuzzy-Matching
        felder = [
            s.get("stadt", ""),
            s.get("adresse", ""),
            s.get("name", ""),
            s.get("primary_category", "")
        ]
        suchtext = " ".join(felder).lower().replace("-", " ")
        score = fuzz.token_set_ratio(frage_clean, suchtext)

        # Boosts
        boost = 0

        # 1. Titel-Kompletttreffer
        title = s.get("title", "")
        if all(w in title for w in frage_clean.split()):
            boost += 10

        # 2. Alias-Treffer
        aliases = s.get("aliases", [])
        if any(alias in frage_clean for alias in aliases):
            boost += 15

        # 3. Berufs-Keywords
        if "ergo" in frage_lc and "ergo" in suchtext:
            boost += 10
        if "physio" in frage_lc and "physio" in suchtext:
            boost += 10
        if "logo" in frage_lc and "logo" in suchtext:
            boost += 10

        # Score summieren
        score += boost

        if score > 70:
            kandidaten.append((s, score))

    kandidaten.sort(key=lambda x: x[1], reverse=True)
    return kandidaten[0][0] if kandidaten else None

@lru_cache(maxsize=1)
def lade_job_urls_cached():
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

def finde_jobs_fuer_ort(frage):
    frage_lower = frage.lower()
    job_urls = lade_job_urls_cached()
    orte = list(job_urls.keys())

    bester_ort, score, _ = process.extractOne(frage_lower, orte, scorer=fuzz.partial_ratio)
    if score >= 80:
        urls = job_urls[bester_ort]
    else:
        urls = [u for jobliste in job_urls.values() for u in jobliste]

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

@app.get("/chat")
def chat(frage: str = Query(...)):
    frage_lc = frage.lower()
    typ_prioritaet = bestimme_fragetyp(frage_lc)
    standort = finde_passenden_standort(frage)

    # 1. Öffnungszeiten explizit behandeln
    if any(kw in frage_lc for kw in ["öffnungszeiten", "wann geöffnet", "wann offen", "wie lange offen", "wann hat"]):
        if standort:
            return {
                "typ": "öffnungszeiten",
                "zentrum": standort.get("title"),
                "stadt": standort.get("stadt"),
                "zeiten": standort.get("zeiten_raw", []),
                "hinweis": "Standortdaten aus XML geladen"
            }
        else:
            return {
                "typ": "faq",
                "antwort": "Die Öffnungszeiten variieren je nach Zentrum. Bitte schau auf der jeweiligen [Standortseite](https://www.novotergum.de/standorte/) nach."
            }

    # 2. Jobs
    if typ_prioritaet == "job":
        jobs = finde_jobs_fuer_ort(frage)
        if jobs:
            return {
                "typ": "job",
                "anzahl": len(jobs),
                "jobs": [{"url": j, "titel": extrahiere_jobtitel(j)} for j in jobs[:5]],
            }

    # 3. Standort
    if typ_prioritaet == "standort" and standort:
        return {"typ": "standort", "antwort": standort}

    # 4. Fallback: trotzdem versuchen, ob ein Standort erkannt wurde
    if standort:
        return {"typ": "standort", "antwort": standort}

    # 5. FAQ-Matching
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

    return {"typ": "unbekannt", "antwort": "Ich konnte leider nichts Passendes finden."}
