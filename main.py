from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from typing import Optional
from fastapi.responses import PlainTextResponse
from datetime import datetime
import zoneinfo
load_dotenv()

# Prompt files directory (default: ./prompts)
BASE_DIR = os.path.dirname(__file__)
PROMPT_DIR = os.getenv("PROMPT_DIR", os.path.join(BASE_DIR, "prompts"))
PROMPT_FILE = os.getenv("PROMPT_FILE", "default.txt")

def read_prompt_file(name: Optional[str] = None) -> str:
    name = name or PROMPT_FILE
    path = os.path.join(PROMPT_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return os.getenv("PROMPT_INSTRUCTIONS", "")

def get_datetime_str() -> str:
    try:
        now = datetime.now().astimezone()
        iso = now.isoformat()
        human = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        # If timezone name empty, show offset
        if not human.strip().endswith(now.tzname() or ""):
            tz = now.tzname() or now.utcoffset()
            human = now.strftime("%Y-%m-%d %H:%M:%S") + f" {tz}"
        return f"Fecha y hora actuales: {human} (ISO: {iso})"
    except Exception:
        return "Fecha y hora desconocida"

def write_prompt_file(name: str, text: str) -> bool:
    try:
        os.makedirs(PROMPT_DIR, exist_ok=True)
        path = os.path.join(PROMPT_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception:
        return False

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Prompt(BaseModel):
    prompt: str

def extract_text(obj):
    if obj is None:
        return ""
    if isinstance(obj, str):
        # If string looks like JSON, try to parse and extract
        s = obj.strip()
        if (s.startswith('{') or s.startswith('[')):
            try:
                import json as _json
                parsed = _json.loads(s)
                return extract_text(parsed)
            except Exception:
                return obj
        return obj
    if isinstance(obj, dict):
        for k in ("output", "text", "content", "reply", "message", "outputText"):
            if k in obj and isinstance(obj[k], (str, int, float)):
                return str(obj[k])
        for k in ("candidates", "choices", "outputs"):
            if k in obj and isinstance(obj[k], list) and len(obj[k]) > 0:
                first = obj[k][0]
                if isinstance(first, (str, int, float)):
                    return str(first)
                if isinstance(first, dict):
                    # Handle Gemini-style candidate content -> parts -> text
                    if "content" in first:
                        content = first["content"]
                        # content may be dict with 'parts' or a list
                        if isinstance(content, dict) and "parts" in content and isinstance(content["parts"], list) and len(content["parts"])>0:
                            p0 = content["parts"][0]
                            if isinstance(p0, dict) and "text" in p0:
                                return str(p0["text"])
                        if isinstance(content, list) and len(content) > 0:
                            c0 = content[0]
                            if isinstance(c0, dict) and "text" in c0:
                                return str(c0["text"])
                    for kk in ("text", "output", "message"):
                        if kk in first and isinstance(first[kk], (str, int, float)):
                            return str(first[kk])
        if "result" in obj:
            return extract_text(obj["result"])
        import json as _json
        return _json.dumps(obj, ensure_ascii=False)
    try:
        return str(obj)
    except Exception:
        return ""

@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/api/test", response_class=PlainTextResponse)
async def test():
    url = os.getenv("GEMINI_API_URL")
    key = os.getenv("GEMINI_API_KEY")
    instr = read_prompt_file()

    if not url:
        return PlainTextResponse("GEMINI_API_URL not configured. Set GEMINI_API_URL in .env.", status_code=400)

    include_dt = os.getenv("PROMPT_INCLUDE_DATETIME", "1") != "0"
    prefix = instr + "\n\n" if instr else ""
    if include_dt:
        prefix += get_datetime_str() + "\n\n"
    prompt_text = prefix + "Hola Gemini"
    payload = {"contents": [{"parts": [{"text": prompt_text}] }]}

    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": key
    }

    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)

    try:
        j = response.json()
    except Exception:
        return PlainTextResponse(response.text or f"status: {response.status_code}", status_code=response.status_code)

    text = extract_text(j)
    return PlainTextResponse(text)

@app.post("/api/gemini", response_class=PlainTextResponse)
async def gemini(p: Prompt):
    url = os.getenv("GEMINI_API_URL")
    key = os.getenv("GEMINI_API_KEY")
    instr = read_prompt_file()

    if not url:
        return PlainTextResponse("GEMINI_API_URL not configured. Set GEMINI_API_URL in .env.", status_code=400)

    include_dt = os.getenv("PROMPT_INCLUDE_DATETIME", "1") != "0"
    prefix = instr + "\n\n" if instr else ""
    if include_dt:
        prefix += get_datetime_str() + "\n\n"
    prompt_text = prefix + p.prompt
    payload = {"contents": [{"parts": [{"text": prompt_text}] }]}

    headers = {"Content-Type": "application/json", "X-goog-api-key": key}

    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)

    try:
        j = response.json()
    except Exception:
        return PlainTextResponse(response.text or f"status: {response.status_code}", status_code=response.status_code)

    text = extract_text(j)
    return PlainTextResponse(text)


# Prompt management endpoints: view and update prompt files
class PromptUpdate(BaseModel):
    text: str


@app.get("/api/prompt")
async def get_default_prompt():
    content = read_prompt_file()
    return {"file": PROMPT_FILE, "text": content}


@app.get("/api/prompt/{name}")
async def get_prompt(name: str):
    content = read_prompt_file(name)
    if not content:
        return {"ok": False, "error": "not found"}
    return {"file": name, "text": content}


@app.post("/api/prompt/{name}")
async def set_prompt(name: str, p: PromptUpdate):
    ok = write_prompt_file(name, p.text)
    return {"ok": ok, "file": name}
