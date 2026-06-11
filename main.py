from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from typing import Optional
from fastapi.responses import PlainTextResponse
from datetime import datetime
import zoneinfo
import httpx
import re
import time
load_dotenv()

# Prompt files directory (default: ./prompts)
BASE_DIR = os.path.dirname(__file__)
PROMPT_DIR = os.getenv("PROMPT_DIR", os.path.join(BASE_DIR, "prompts"))
PROMPT_FILE = os.getenv("PROMPT_FILE", "default.txt")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "40"))
HISTORY_TTL_SECONDS = int(os.getenv("HISTORY_TTL_SECONDS", "1800"))
GEMINI_TIMEOUT = httpx.Timeout(
    connect=float(os.getenv("GEMINI_CONNECT_TIMEOUT", "10")),
    read=float(os.getenv("GEMINI_READ_TIMEOUT", "30")),
    write=float(os.getenv("GEMINI_WRITE_TIMEOUT", "30")),
    pool=float(os.getenv("GEMINI_POOL_TIMEOUT", "30")),
)

conversation_history: list[dict] = []
gemini_client: httpx.AsyncClient | None = None

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

def build_system_instruction(instr: str) -> str:
    include_dt = os.getenv("PROMPT_INCLUDE_DATETIME", "1") != "0"
    parts = [instr.strip()] if instr else []
    if include_dt:
        parts.append(get_datetime_str())
    parts.append(
        "No saludes de nuevo si la conversacion ya empezo. "
        "Responde directo a lo ultimo que dijo el usuario."
    )
    return "\n\n".join(parts)

def build_contents(user_text: str, history: Optional[list[dict]] = None) -> list[dict]:
    return [
        *(history or []),
        {"role": "user", "parts": [{"text": user_text}]},
    ]

def build_generation_config() -> dict:
    return {
        "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.5")),
        "maxOutputTokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "512")),
    }

def prune_history() -> None:
    cutoff = time.time() - HISTORY_TTL_SECONDS
    conversation_history[:] = [
        item for item in conversation_history
        if item["created_at"] >= cutoff
    ]
    if len(conversation_history) > MAX_HISTORY_MESSAGES:
        del conversation_history[:-MAX_HISTORY_MESSAGES]

def get_recent_history() -> list[dict]:
    prune_history()
    return [item["message"] for item in conversation_history]

def append_history(role: str, text: str) -> None:
    if not text:
        return

    conversation_history.append({
        "created_at": time.time(),
        "message": {"role": role, "parts": [{"text": text}]},
    })
    prune_history()

def strip_repeated_greeting(text: str) -> str:
    if not get_recent_history():
        return text

    cleaned = re.sub(
        r"^\s*(hola|buenos dias|buenas tardes|buenas noches)[,!.\s]*(soy geriabot[,!.\s]*)?",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).lstrip()

    if not cleaned:
        return "Te escucho."
    if cleaned != text:
        return cleaned[:1].upper() + cleaned[1:]
    return text

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

@app.on_event("startup")
async def startup_event() -> None:
    global gemini_client
    gemini_client = httpx.AsyncClient(timeout=GEMINI_TIMEOUT)

@app.on_event("shutdown")
async def shutdown_event() -> None:
    if gemini_client is not None:
        await gemini_client.aclose()

async def post_to_gemini(url: str, payload: dict, headers: dict) -> httpx.Response:
    if gemini_client is None:
        async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
            return await client.post(url, json=payload, headers=headers)

    return await gemini_client.post(url, json=payload, headers=headers)

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
                            texts = [
                                str(part["text"])
                                for part in content["parts"]
                                if isinstance(part, dict) and "text" in part
                            ]
                            if texts:
                                return "".join(texts)
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

    payload = {
        "system_instruction": {"parts": [{"text": build_system_instruction(instr)}]},
        "contents": build_contents("Hola Gemini"),
        "generationConfig": build_generation_config(),
    }

    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": key
    }

    response = await post_to_gemini(url, payload, headers)

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

    user_text = p.prompt.strip()
    payload = {
        "system_instruction": {"parts": [{"text": build_system_instruction(instr)}]},
        "contents": build_contents(user_text, get_recent_history()),
        "generationConfig": build_generation_config(),
    }

    headers = {"Content-Type": "application/json", "X-goog-api-key": key}

    try:
        response = await post_to_gemini(url, payload, headers)
    except httpx.ReadTimeout:
        return PlainTextResponse("Gemini tardo demasiado en responder", status_code=504)
    except Exception as e:
        return PlainTextResponse(str(e), status_code=500)

    try:
        j = response.json()
    except Exception:
        return PlainTextResponse(response.text or f"status: {response.status_code}", status_code=response.status_code)

    text = strip_repeated_greeting(extract_text(j))
    append_history("user", user_text)
    append_history("model", text)
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
