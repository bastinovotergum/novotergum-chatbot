from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Importiere die Hauptfunktion aus deinem Chatbot-Code
from chatbot import run_chatbot  # Diese Funktion musst du in chatbot.py definieren

app = FastAPI()

# CORS freigeben – ggf. Domain eingrenzen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Oder z. B. ["https://novotergum.de"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# Eingabemodell
class ChatInput(BaseModel):
    message: str

# API-Endpunkt für das Chat-Widget
@app.post("/chat")
async def chat(input: ChatInput):
    try:
        antwort = run_chatbot(input.message)
        return {"reply": antwort}
    except Exception as e:
        return {"reply": f"❌ Fehler: {str(e)}"}
