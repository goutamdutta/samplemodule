
from fastapi import FastAPI, HTTPException
from fastapi import UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import httpx
from dotenv import load_dotenv
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
from typing import Optional
from io import BytesIO
import tempfile
import subprocess

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


class CrawlRequest(BaseModel):
    start_url: str
    max_pages: int = 50
    same_domain_only: bool = True
    timeout_seconds: int = 15
    user_agent: Optional[str] = "GroqChatbotCrawler/1.0 (+https://example.local)"

class CrawledPage(BaseModel):
    url: str
    title: str | None = None
    status: int | None = None
    num_links: int = 0
    content_type: str | None = None

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


def _normalize_link(base_url: str, href: str) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    # Drop mailto:, javascript:, tel: etc.
    if any(href.lower().startswith(s) for s in ("mailto:", "javascript:", "tel:", "data:")):
        return None
    absolute = urljoin(base_url, href)
    # Remove fragment
    absolute, _ = urldefrag(absolute)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    return absolute


@app.post("/api/crawl")
async def crawl(req: CrawlRequest):
    start = req.start_url
    parsed_start = urlparse(start)
    if parsed_start.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="start_url must be http or https")

    to_visit: list[str] = [start]
    visited: set[str] = set()
    results: list[CrawledPage] = []

    headers = {"User-Agent": req.user_agent or "GroqChatbotCrawler/1.0"}
    timeout = httpx.Timeout(req.timeout_seconds)

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        while to_visit and len(visited) < req.max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                resp = await client.get(url)
                content_type = resp.headers.get("Content-Type", "")
                is_html = content_type.startswith("text/html") or "html" in content_type
                title = None
                num_links = 0

                if is_html:
                    soup = BeautifulSoup(resp.text, "lxml")
                    title_tag = soup.find("title")
                    title = title_tag.text.strip() if title_tag else None
                    # Extract links
                    domain = parsed_start.netloc
                    for a in soup.find_all("a"):
                        href = a.get("href")
                        normalized = _normalize_link(url, href)
                        if not normalized:
                            continue
                        if req.same_domain_only and urlparse(normalized).netloc != domain:
                            continue
                        if normalized not in visited and normalized not in to_visit and len(visited) + len(to_visit) < req.max_pages:
                            to_visit.append(normalized)
                            num_links += 1

                results.append(CrawledPage(
                    url=url,
                    title=title,
                    status=resp.status_code,
                    num_links=num_links,
                    content_type=content_type if content_type else None
                ))
            except httpx.HTTPError as e:
                results.append(CrawledPage(url=url, title=None, status=None, num_links=0, content_type=None))
                continue

    return {"count": len(results), "pages": [r.model_dump() for r in results]}


def _extract_text_from_txt(data: bytes) -> str:
    try:
        return data.decode('utf-8', errors='ignore')
    except Exception:
        return ""


def _extract_text_from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
        texts: list[str] = []
        for page in reader.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(t.strip() for t in texts if t)
    except Exception as e:
        return ""


def _extract_text_from_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
        document = docx.Document(BytesIO(data))
        paragraphs = [p.text for p in document.paragraphs if p.text]
        return "\n".join(paragraphs)
    except Exception:
        return ""


def _extract_text_from_doc(data: bytes) -> str:
    # Uses system 'antiword' to convert .doc to text
    try:
        with tempfile.NamedTemporaryFile(suffix=".doc", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            proc = subprocess.run(["antiword", tmp.name], capture_output=True, check=False)
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout.decode('utf-8', errors='ignore')
            # Fallback: try latin-1
            if proc.stdout:
                return proc.stdout.decode('latin-1', errors='ignore')
            return ""
    except FileNotFoundError:
        # antiword not installed
        return ""
    except Exception:
        return ""


@app.post("/api/extract-text")
async def extract_text(file: UploadFile | None = File(None), files: list[UploadFile] | None = File(None)):
    uploads: list[UploadFile] = []
    if file is not None:
        uploads.append(file)
    if files:
        uploads.extend(files)
    if not uploads:
        raise HTTPException(status_code=400, detail="No file(s) provided. Use 'file' or 'files'.")

    results: list[dict] = []
    for up in uploads:
        try:
            name = up.filename or "upload"
            ext = Path(name).suffix.lower()
            data = await up.read()
            text = ""
            if ext == ".txt":
                text = _extract_text_from_txt(data)
            elif ext == ".pdf":
                text = _extract_text_from_pdf(data)
            elif ext == ".docx":
                text = _extract_text_from_docx(data)
            elif ext == ".doc":
                text = _extract_text_from_doc(data)
            else:
                results.append({"filename": name, "supported": False, "error": f"Unsupported extension: {ext}"})
                continue

            results.append({
                "filename": name,
                "supported": True,
                "characters": len(text),
                "text": text
            })
        except Exception as e:
            results.append({"filename": getattr(up, 'filename', 'upload'), "supported": False, "error": str(e)})

    return {"count": len(results), "results": results}
