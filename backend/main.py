
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import httpx
from dotenv import load_dotenv
from pathlib import Path

# Ensure we load the .env that sits next to this file
load_dotenv(dotenv_path=Path(__file__).with_name('.env'))

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

app = FastAPI(title="Groq Chat Proxy")

# CORS - allow frontend dev server and any origin via env override
allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(',')
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    temperature: float | None = 0.7
    max_tokens: int | None = 512

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="Missing GROQ_API_KEY")
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": req.model,
        "messages": [m.model_dump() for m in req.messages],
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "stream": False
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(GROQ_API_URL, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            # OpenAI-compatible response structure
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            return {"content": content, "raw": data}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
