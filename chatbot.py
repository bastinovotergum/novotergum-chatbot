import streamlit as st
import os
import re
import requests
import xml.etree.ElementTree as ET
from rapidfuzz import process, fuzz
from sentence_transformers import SentenceTransformer, util

try:
    query_params = st.query_params
    frage_von_url = query_params.get("frage", [""])[0]
except Exception:
    frage_von_url = ""

# --- Initialisierung ---
@st.cache_resource
def lade_modell():
    return SentenceTransformer('all-MiniLM-L6-v2')

model = lade_modell()

# --- Hilfsfunktion: Frage betrifft Standort? ---
def frage_betrifft_standort(user_input):
    stichworte = [" in ", " bei ", "nähe", "wo ist", "standort", "zentrum", "praxis", "adresse", "map", "google maps"]
    return any(w in user_input.lower() for w in stichworte)

# --- Hilfsfunktion: Frage betrifft Job? ---
def frage_betrifft_job(user_input):
    job_stichworte = [
        "job", "jobs", "stelle", "stellen", "bewerbung", "bewerben", "karriere", 
        "jobangebot", "jobangebote", "stellenangebot", "stellenangebote", "ausschreibung"
    ]
    return any(w in user_input.lower() for w in job_stichworte)

# --- Öffnungszeiten formatieren ---
def format_oeffnungszeiten(opening_node):
    if opening_node is None:
        return "Keine Öffnungszeiten gefunden"
    tage = []
    for hours in opening_node.findall("hours"):
        tag = hours.findtext("dayOfWeek", "").strip()
        open_time = hours.findtext("opens", "").strip()
        close_time = hours.findtext("closes", "").strip()
        if tag and open_time and close_time:
            tage.append(f"{tag}: {open_time}–{close_time}")
    return " | ".join(tage)

# --- Standortdaten laden ---
@st.cache_resource(show_spinner=False)
def lade_standorte(xml_path):

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        standorte = []

        for eintrag in root.findall("standort"):
            name = eintrag.findtext("title", default="")
            primary_category = eintrag.findtext("primary_category", default="").lower()
            stadt = eintrag.findtext("stadt", default="")
            adresse = eintrag.findtext("strasse", default="") + " " + eintrag.findtext("postleitzahl", default="")
            telefon = eintrag.findtext("telefon", default="")
            url = eintrag.findtext("standort_url", default="")
            status = eintrag.findtext("opening_status", default="")
            region = eintrag.findtext("region_code", default="")
            beschreibung = eintrag.findtext("description", default="")
            titel = eintrag.findtext("title", default="")

            maps_url = f"https://www.google.com/maps/search/?api=1&query={adresse.replace(' ', '+')},{stadt.replace(' ', '+')}"

            # Öffnungszeiten extrahieren
        wochentage_deutsch = {
            "Monday": "Montag",
            "Tuesday": "Dienstag",
            "Wednesday": "Mittwoch",
            "Thursday": "Donnerstag",
            "Friday": "Freitag",
            "Saturday": "Samstag",
            "Sunday": "Sonntag"
        }
        zeiten_liste = []
            
        for hours in eintrag.findall(".//openingHoursSpecification/hours"):
            tag = hours.findtext("dayOfWeek", "")
            von = hours.findtext("opens", "")
            bis = hours.findtext("closes", "")
            if tag and von and bis:
                tag_de = wochentage_deutsch.get(tag, tag)  # fallback auf Original
                zeiten_liste.append(f"{tag_de}: {von}–{bis}")
            
        zeiten = " | ".join(zeiten_liste) if zeiten_liste else "Nicht verfügbar"

            # Begriffe für Standort-Matching extrahieren
            alle_texte = f"{name} {adresse} {stadt} {titel}".lower()
            suchbegriffe = set(re.split(r"[\s\-]+", alle_texte))

            category = (eintrag.findtext("primary_category") or "").strip()

            standorte.append({
                "name": name,
                "stadt": stadt,
                "adresse": adresse,
                "telefon": telefon,
                "url": url,
                "status": status,
                "region": region,
                "primary_category": primary_category,
                "beschreibung": beschreibung,
                "titel": titel,
                "zeiten": zeiten,
                "suchbegriffe": suchbegriffe,
                "maps": maps_url   # <--- hinzugefügt
            })

        return standorte

    except Exception as e:
        print(f"[Fehler beim Laden der Standorte] {e}")
        return []


# --- Job-Sitemap laden ---
@st.cache_data(show_spinner=False)
def lade_job_urls():
    sitemap_url = "https://novotergum.de/novotergum_job-sitemap.xml"
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        job_urls = {}

        for url_node in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
            loc = url_node.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None:
                url = loc.text.strip()
                slug = url.rstrip("/").split("/")[-1]
                
                # Skip Hauptseite /jobs/
                if slug == "jobs":
                    continue

                teile = slug.split("-")
                if teile:
                    ort = teile[-1].lower()
                    job_urls.setdefault(ort, []).append(url)
        return job_urls
    except Exception as e:
        print("[Fehler beim Laden der Job-URLs]", e)
        return {}

# --- Hilfsfunktion: Normalisierung (für Umlaute etc.) ---
def normalisiere(text):
    return text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")

# --- Job-Filter basierend auf Beruf und Frage ---
def filtere_jobs_nach_beruf(job_urls, frage):
    frage_norm = normalisiere(frage)

    relevante_berufe = {
        "physiotherapeut": ["physiotherapeut", "physiotherapeutin", "physiotherapie", "physio", "kinderphysiotherapeut", "kinderphysiotherapeutin", "mt", "kgg", "training", "sport"],
        "logopäde": ["logopäde", "logopädin", "logopaedie", "logopädie", "sprachtherapie"],
        "ergotherapeut": ["ergotherapeut", "ergotherapeutin", "ergotherapie", "ergo"],
        "rezeption": ["rezeption", "empfang", "rezeptionist", "rezeptionistin"],
        "leitung": ["leitung", "zentrumsmanager", "bereichsleitung", "fachleitung"],
        "verwaltung": ["verwaltung", "admin", "assistenz", "buchhaltung", "office", "teamassistenz"],
    }

    gesuchte_begriffe = set()
    for begriffsliste in relevante_berufe.values():
        for b in begriffsliste:
            if normalisiere(b) in frage_norm:
                gesuchte_begriffe.update(normalisiere(w) for w in begriffsliste)

    # Wenn keine Begriffe erkannt → alle URLs zurückgeben
    if not gesuchte_begriffe:
        return job_urls

    def url_passt(url):
        slug = normalisiere(url.rstrip("/").split("/")[-1])
        return any(b in slug for b in gesuchte_begriffe)

    return [url for url in job_urls if url_passt(url)]

def finde_kategorie_in_frage(user_input):
    frage_norm = normalisiere(user_input)
    if "ergo" in frage_norm:
        return "Ergotherapeut"
    elif "physio" in frage_norm or "krankengymnast" in frage_norm:
        return "Physiotherapiezentrum"
    elif "logo" in frage_norm or "sprachtherapie" in frage_norm:
        return "Logopädie"
    return None
    
# --- Standort-Suche mit Fuzzy-Matching (Stadt-Prio) ---
def finde_passenden_standort(user_input):
    user_input_lower = user_input.lower()

    kandidaten = []
    for eintrag in standorte_data:
        name = eintrag["name"].lower()
        stadt = eintrag["stadt"].lower()
        titel = eintrag.get("titel", "").lower()
        kategorie = eintrag.get("beschreibung", "").lower()  # alternativ: extrahiere <primary_category>
        kategorie = eintrag.get("primary_category", "").lower()

        score_name = fuzz.partial_ratio(user_input_lower, name)
        score_stadt = fuzz.partial_ratio(user_input_lower, stadt)
        score_titel = fuzz.partial_ratio(user_input_lower, titel)
        score_kategorie = fuzz.partial_ratio(user_input_lower, kategorie)

        # Grundscore
        score_gesamt = max(score_name, score_stadt, score_titel, score_kategorie)

        # Bonus bei kombinierten Treffern
        if score_name > 70 and score_stadt > 70:
            score_gesamt += 10

        # Bonus für exakte Berufsbezeichnung
        if "ergo" in user_input_lower and "ergo" in kategorie:
            score_gesamt += 15
        elif "physio" in user_input_lower and "physio" in kategorie:
            score_gesamt += 15
        elif "logo" in user_input_lower and "logo" in kategorie:
            score_gesamt += 15

        kandidaten.append((eintrag, score_gesamt))

    kandidaten.sort(key=lambda x: x[1], reverse=True)

    if kandidaten and kandidaten[0][1] >= 80:
        return kandidaten[0][0]

    return None
    
# --- Job-Suche mit Fallback ---
def finde_jobs_fuer_ort(frage):
    frage_lower = frage.lower()
    orte = list(job_urls.keys())
    bester_ort, score, _ = process.extractOne(frage_lower, orte, scorer=fuzz.partial_ratio)

    if score >= 80:
        return job_urls[bester_ort]

    # Kein konkreter Ort → zeige alle Jobs
    alle_jobs = []
    for jobliste in job_urls.values():
        alle_jobs.extend(jobliste)
    return alle_jobs

# --- Jobtitel aus URL extrahieren ---
def extrahiere_jobtitel(url):
    import re

    slug = url.rstrip("/").split("/")[-1]
    teile = slug.split("-")

    blacklist = {
        "m", "w", "d", "in", "fuer", "für", "der", "die", "und", "mit",
        "hausbesuche", "team", "std", "stunden", "woche", "monat", "jahr",
        "ab", "sofort", "nach", "vereinbarung", "job", "karriere",
        "bis", "zu", "haus", "heimbesuche"
    }

    highlight = {
        "azubi": "(Azubi)",
        "auszubildender": "(Azubi)",
        "leitung": "Leitung",
        "fachliche": "Fachliche Leitung",
        "empfang": "Empfang",
        "rezeption": "Rezeption",
        "rezeptionist": "Rezeptionist",
        "physiotherapeut": "Physiotherapeut",
        "kinderphysiotherapeut": "Kinderphysiotherapeut",
        "osteopath": "Osteopath",
        "massagetherapeut": "Massagetherapeut",
        "lymphdrainage": "Lymphdrainage",
        "ergotherapeut": "Ergotherapeut",
        "logopaede": "Logopäde",
        "logopaedie": "Logopädie",
        "verwaltung": "Verwaltung",
        "assistenz": "Assistenz",
        "teamassistenz": "Teamassistenz",
        "zentrumsmanager": "Zentrumsmanager",
        "recruiting": "Recruiting",
        "werkstudent": "Werkstudent",
        "data": "Datenanalyse",
        "ki": "KI",
        "innovation": "Innovation",
        "buchhaltung": "Buchhaltung",
        "marketing": "Marketing",
        "training": "Training",
        "sport": "Sport",
        "controller": "Controller",
        "pmi": "PMI Manager",
        "office": "Office Management",
        "administration": "Administration",
        "hausbesuche": "Hausbesuche",
        "heim": "Heimbesuche",
        "remote": "Remote",
        "hybrid": "Hybrid",
        "minijob": "Minijob",
        "teilzeit": "Teilzeit",
        "vollzeit": "Vollzeit",
    }

    # IDs & Füllwörter entfernen
    teile = [t for t in teile if not t.isdigit() and t.lower() not in blacklist]

    titelteile = []
    ortsteile = []

    for teil in teile:
        teil_lc = teil.lower()
        if teil_lc in highlight:
            titelteile.append(highlight[teil_lc])
        elif re.match(r"^[a-zäöüß]+$", teil_lc):
            # potentieller Ortsteil (z. B. "krefeld", "ford", "werke")
            ortsteile.append(teil.capitalize())
        else:
            titelteile.append(teil.capitalize())

    jobtitel = " – ".join(titelteile).strip(" –")

    if ortsteile:
        ort = " ".join(ortsteile)
        return f"**{jobtitel}** (m/w/d) in **{ort}**"
    else:
        return f"**{jobtitel}** (m/w/d)"

# --- FAQ-Daten laden ---
faq_dir = "faq"
faq_data = []

for filename in os.listdir(faq_dir):
    filepath = os.path.join(faq_dir, filename)
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

if faq_data:
    faq_questions = [q for q, _ in faq_data]
    faq_embeddings = model.encode(faq_questions, convert_to_tensor=True)
else:
    faq_questions, faq_embeddings = [], None

# --- Daten laden ---
standorte_data = lade_standorte("standorte-test.xml")
job_urls = lade_job_urls()

# --- Streamlit UI ---
st.set_page_config(page_title="NOVOTERGUM Chatbot")
st.title("NOVOTERGUM Chatbot 😊")
st.caption("Letztes Update: 2025-07-13")

params = st.query_params
vorgegebene_frage = params.get("frage", "")
frage = st.text_input("Stelle deine Frage:", value=vorgegebene_frage)


# --- Standort-Ausgabeformat ---
def format_standort(eintrag):
    return (
        f"📍 **{eintrag['adresse']}**\n"
        f"📞 [{eintrag['telefon']}](tel:{eintrag['telefon'].replace(' ', '')})\n"
        f"🕒 {eintrag['zeiten']}\n"
        f"[🌍 Google Maps öffnen]({eintrag['maps']})"
    )

# --- Vorab: Standortantwort bei klarer Standort-Intention ---
def frage_hat_standort_intent(frage: str) -> bool:
    standort_stichworte = [
        "öffnungszeiten", "wie lange geöffnet", "wann geöffnet", "wann offen",
        "adresse", "anschrift", "lage", "standort", "zentrum", "praxis", 
        "wo finde ich", "wo ist", "karte", "google maps", "anfahrt", "anfahrtsbeschreibung", 
        "nummer", "sprechzeiten", "besuchszeiten", "map", "maps-link",
        "termin", "termine", "terminvereinbarung", "termin machen", "termin buchen"
    ]
    frage_lc = frage.lower()
    return any(kw in frage_lc for kw in standort_stichworte)

if frage_hat_standort_intent(frage):
    standort = finde_passenden_standort(frage)
    if standort:
        st.markdown("**Antwort:**")
        st.markdown(format_standort(standort))
        st.stop()

# --- Beantwortung ---
if frage:
    if faq_embeddings is not None:
        frage_embedding = model.encode(frage, convert_to_tensor=True)
        scores = util.cos_sim(frage_embedding, faq_embeddings)
        best_match_idx = scores.argmax().item()
        best_score = scores[0][best_match_idx].item()

        if best_score > 0.6:
            antwort = faq_data[best_match_idx][1]
            faq_frage = faq_data[best_match_idx][0]
            if "gehalt" in frage.lower() and "gehalt" not in faq_frage.lower():
                pass  # ignorieren
            else:
                st.markdown("**Antwort:** " + antwort)
                st.stop()
        else:
            st.markdown("❓ Ich habe keine exakte Antwort gefunden. Meintest du vielleicht:")
            top_k = 3
            top_scores, top_indices = scores.topk(top_k)

            for idx, score in zip(top_indices[0], top_scores[0]):
                vorgeschlagene_frage = faq_data[idx.item()][0]
                if st.button(vorgeschlagene_frage, key=f"vorschlag_{idx.item()}"):
                    st.query_params.update({"frage": vorgeschlagene_frage})
                    st.rerun()
jobs = []
if frage_betrifft_job(frage):
    alle_jobs = finde_jobs_fuer_ort(frage)
    jobs = filtere_jobs_nach_beruf(alle_jobs, frage)

standort = finde_passenden_standort(frage)

if jobs:
    if frage_hat_standort_intent(frage) and standort:
        st.markdown("**Standort:**")
        st.markdown(format_standort(standort))

    st.markdown("**Offene Stellenangebote:**")
    for job in jobs:
        titel = extrahiere_jobtitel(job)
        st.markdown(f"- [{titel}]({job})")

    st.stop()

if standort:
    st.markdown("**Antwort:**")
    st.markdown(format_standort(standort))
    st.stop()

st.warning("Ich konnte leider keine passende Antwort finden.")
