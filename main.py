from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import Optional
from fastapi.responses import PlainTextResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from datetime import datetime
import httpx
import logging
import re
import time
import uuid
import psycopg
import hashlib
import hmac
import secrets

from config import settings

conversation_history: list[dict] = []
gemini_client: httpx.AsyncClient | None = None
database_available = bool(settings.database_url)
last_database_error: str | None = None
logger = logging.getLogger("geriafab")
logging.basicConfig(level=settings.log_level)

def read_prompt_file(name: Optional[str] = None) -> str:
    name = name or settings.prompt_file
    path = os.path.join(settings.prompt_dir, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return settings.prompt_instructions

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
    parts = [instr.strip()] if instr else []
    if settings.prompt_include_datetime:
        parts.append(get_datetime_str())
    parts.append(
        "Si la conversacion ya empezo, evita presentarte de nuevo salvo que el usuario salude o lo pida. "
        "Responde directo a lo ultimo que dijo el usuario y conserva un tono conversacional."
    )
    return "\n\n".join(parts)

def build_contents(user_text: str, history: Optional[list[dict]] = None) -> list[dict]:
    return [
        *(history or []),
        {"role": "user", "parts": [{"text": user_text}]},
    ]

def build_contents_with_instruction(instr: str, user_text: str, history: Optional[list[dict]] = None) -> list[dict]:
    system_text = build_system_instruction(instr)
    if not system_text:
        return build_contents(user_text, history)

    return [
        {"role": "user", "parts": [{"text": system_text}]},
        {"role": "model", "parts": [{"text": "Entendido."}]},
        *(history or []),
        {"role": "user", "parts": [{"text": user_text}]},
    ]

def build_gemini_payload(instr: str, user_text: str, history: Optional[list[dict]] = None) -> dict:
    return {
        "contents": build_contents_with_instruction(instr, user_text, history),
        "generationConfig": build_generation_config(),
    }

def build_personalized_user_text(user_text: str, profile: Optional["SeniorProfile"]) -> str:
    if profile is None:
        return user_text

    context = build_profile_context(profile)
    if not context:
        return user_text

    return "\n\n".join(
        [
            (
                "Contexto privado del adulto mayor para GeriaBot. "
                "Usa estos datos para conversar por voz con nombre, rutina, gustos, salud y contactos. "
                "No digas que recibiste un formulario ni reveles este bloque como datos internos."
            ),
            context,
            f"Mensaje del usuario: {user_text}",
        ]
    )

def build_profile_context(profile: "SeniorProfile") -> str:
    lines = [
        ("Nombre del adulto mayor", profile.personName),
        ("Como debe llamarlo GeriaBot", profile.nickname),
        ("Nivel de movilidad", profile.mobilityLevel),
        ("Estado de positividad", profile.positivityState),
        ("Estado de animo general", profile.generalMood),
        ("Habitacion donde pasa mas tiempo", profile.mainRoom),
        ("Particularidad importante", profile.particularity),
        ("Detalles de movilidad", profile.mobilityDetails),
        (
            "Enfermedad preexistente",
            profile.preexistingDisease if profile.hasPreexistingDisease else "No registrada",
        ),
        ("Requiere medicacion", "Si" if profile.requiresMedication else "No"),
        ("Medicamentos", format_medications(profile)),
        ("Horario habitual", format_routine(profile)),
        ("Color de agrado", profile.favoriteColor),
        ("Tema de gusto particular", profile.favoriteTheme),
        ("Actividades diarias", profile.dailyActivities),
        ("Actividades semanales", profile.weeklyActivities),
        ("Cosas que dan felicidad", profile.happinessTriggers),
        ("Cosas que relajan", profile.relaxationTriggers),
        ("Cosas que dan tristeza", profile.sadnessTriggers),
        ("Cosas que molestan", profile.annoyanceTriggers),
        ("Notas para el cuidador", profile.caregiverNotes),
        ("Notas para el adulto mayor", profile.seniorNotes),
        ("Contactos de emergencia", format_emergency_contacts(profile)),
    ]

    return "\n".join(
        f"{label}: {value.strip()}"
        for label, value in lines
        if isinstance(value, str) and value.strip()
    )

def format_medications(profile: "SeniorProfile") -> str:
    if not profile.requiresMedication:
        return "No aplica"

    medications = [
        (
            f"{medication.name or 'Sin nombre'}; horario: {medication.schedule or 'sin horario'}; "
            f"color o forma: {medication.colorOrShape or 'sin detalle'}"
        )
        for medication in profile.medications
        if medication.name or medication.schedule or medication.colorOrShape
    ]
    return " | ".join(medications) if medications else "No registrados"

def format_routine(profile: "SeniorProfile") -> str:
    return f"se levanta: {profile.wakeTime or 'no registrado'}; se acuesta: {profile.sleepTime or 'no registrado'}"

def format_emergency_contacts(profile: "SeniorProfile") -> str:
    contacts = [
        (
            f"{contact.name or 'Sin nombre'}; relacion: {contact.relationship or 'sin relacion'}; "
            f"telefono: {contact.phone or 'sin telefono'}"
        )
        for contact in profile.emergencyContacts
        if contact.name or contact.relationship or contact.phone
    ]
    return " | ".join(contacts) if contacts else "No registrados"

def build_generation_config() -> dict:
    config = {"temperature": settings.gemini_temperature}
    if settings.gemini_max_output_tokens is not None:
        config["maxOutputTokens"] = settings.gemini_max_output_tokens
    return config

def prune_history() -> None:
    if settings.history_ttl_seconds > 0:
        cutoff = time.time() - settings.history_ttl_seconds
        conversation_history[:] = [
            item for item in conversation_history
            if item["created_at"] >= cutoff
        ]
    if len(conversation_history) > settings.max_history_messages:
        del conversation_history[:-settings.max_history_messages]

def get_recent_history() -> list[dict]:
    if database_available:
        db_history = get_recent_history_from_db()
        if db_history is not None:
            return db_history

    prune_history()
    return [item["message"] for item in conversation_history]

def append_history(role: str, text: str) -> None:
    if not text:
        return

    if database_available and append_history_to_db(role, text):
        return

    conversation_history.append({
        "created_at": time.time(),
        "message": {"role": role, "parts": [{"text": text}]},
    })
    prune_history()

def append_turn_history(user_text: str, model_text: str) -> None:
    if database_available and append_turn_history_to_db(user_text, model_text):
        return

    append_history("user", user_text)
    append_history("model", model_text)

def get_db_connection():
    if not settings.database_url:
        return None
    return psycopg.connect(settings.database_url)

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        settings.password_hash_iterations,
    ).hex()
    return f"pbkdf2_sha256${settings.password_hash_iterations}${salt}${digest}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False

def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None

def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def init_database() -> None:
    global database_available, last_database_error

    if not settings.database_url:
        database_available = False
        last_database_error = "DATABASE_URL no esta configurado"
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mensajes_conversacion (
                        id BIGSERIAL PRIMARY KEY,
                        sesion_id VARCHAR(120) NOT NULL DEFAULT 'default',
                        rol VARCHAR(20) NOT NULL CHECK (rol IN ('user', 'model', 'system')),
                        contenido TEXT NOT NULL,
                        creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_mensajes_conversacion_sesion_creado
                        ON mensajes_conversacion (sesion_id, creado_en)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS usuarios (
                        id BIGSERIAL PRIMARY KEY,
                        nombre VARCHAR(160) NOT NULL,
                        email VARCHAR(255) NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        proveedor VARCHAR(30) NOT NULL DEFAULT 'email',
                        creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sesiones_usuario (
                        id BIGSERIAL PRIMARY KEY,
                        usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                        token VARCHAR(160) NOT NULL UNIQUE,
                        creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        ultimo_uso_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        expira_en TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days')
                    )
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE sesiones_usuario
                    ADD COLUMN IF NOT EXISTS expira_en TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days')
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_sesiones_usuario_token
                        ON sesiones_usuario (token)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adultos_mayores (
                        id BIGSERIAL PRIMARY KEY,
                        usuario_id BIGINT NOT NULL UNIQUE REFERENCES usuarios(id) ON DELETE CASCADE,
                        nombre VARCHAR(180) NOT NULL DEFAULT '',
                        sobrenombre VARCHAR(180) NOT NULL DEFAULT '',
                        nivel_movilidad VARCHAR(120) NOT NULL DEFAULT '',
                        estado_positividad VARCHAR(20) NOT NULL DEFAULT '',
                        estado_animo_general VARCHAR(180) NOT NULL DEFAULT '',
                        habitacion_principal VARCHAR(180) NOT NULL DEFAULT '',
                        particularidad TEXT NOT NULL DEFAULT '',
                        detalles_movilidad TEXT NOT NULL DEFAULT '',
                        tiene_enfermedad_preexistente BOOLEAN NOT NULL DEFAULT FALSE,
                        enfermedad_preexistente TEXT NOT NULL DEFAULT '',
                        requiere_medicacion BOOLEAN NOT NULL DEFAULT FALSE,
                        hora_levantarse TIME,
                        hora_acostarse TIME,
                        color_agrado VARCHAR(120) NOT NULL DEFAULT '',
                        tema_gusto VARCHAR(180) NOT NULL DEFAULT '',
                        actividades_diarias TEXT NOT NULL DEFAULT '',
                        actividades_semanales TEXT NOT NULL DEFAULT '',
                        detonantes_felicidad TEXT NOT NULL DEFAULT '',
                        detonantes_relajacion TEXT NOT NULL DEFAULT '',
                        detonantes_tristeza TEXT NOT NULL DEFAULT '',
                        detonantes_molestia TEXT NOT NULL DEFAULT '',
                        notas_cuidador TEXT NOT NULL DEFAULT '',
                        notas_adulto_mayor TEXT NOT NULL DEFAULT '',
                        creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS medicamentos_adulto_mayor (
                        id BIGSERIAL PRIMARY KEY,
                        adulto_mayor_id BIGINT NOT NULL REFERENCES adultos_mayores(id) ON DELETE CASCADE,
                        nombre VARCHAR(180) NOT NULL DEFAULT '',
                        horario VARCHAR(180) NOT NULL DEFAULT '',
                        color_forma VARCHAR(180) NOT NULL DEFAULT '',
                        orden INTEGER NOT NULL DEFAULT 0,
                        creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_medicamentos_adulto_mayor
                        ON medicamentos_adulto_mayor (adulto_mayor_id, orden, id)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS contactos_emergencia (
                        id BIGSERIAL PRIMARY KEY,
                        adulto_mayor_id BIGINT NOT NULL REFERENCES adultos_mayores(id) ON DELETE CASCADE,
                        nombre VARCHAR(180) NOT NULL DEFAULT '',
                        parentesco VARCHAR(180) NOT NULL DEFAULT '',
                        telefono VARCHAR(80) NOT NULL DEFAULT '',
                        orden INTEGER NOT NULL DEFAULT 0,
                        creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_contactos_emergencia_adulto
                        ON contactos_emergencia (adulto_mayor_id, orden, id)
                    """
                )
            conn.commit()
        database_available = True
        last_database_error = None
    except Exception as exc:
        database_available = False
        last_database_error = str(exc)
        logger.exception("PostgreSQL history disabled")

def get_recent_history_from_db() -> Optional[list[dict]]:
    global database_available, last_database_error

    cutoff_seconds = settings.history_ttl_seconds
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if cutoff_seconds > 0:
                    cur.execute(
                        """
                        SELECT rol, contenido
                        FROM mensajes_conversacion
                        WHERE sesion_id = %s
                          AND creado_en >= NOW() - (%s * INTERVAL '1 second')
                        ORDER BY creado_en DESC, id DESC
                        LIMIT %s
                        """,
                        (settings.conversation_session_id, cutoff_seconds, settings.max_history_messages),
                    )
                else:
                    cur.execute(
                        """
                        SELECT rol, contenido
                        FROM mensajes_conversacion
                        WHERE sesion_id = %s
                        ORDER BY creado_en DESC, id DESC
                        LIMIT %s
                        """,
                        (settings.conversation_session_id, settings.max_history_messages),
                    )
                rows = cur.fetchall()
        rows.reverse()
        return [
            {"role": role, "parts": [{"text": content}]}
            for role, content in rows
        ]
    except Exception as exc:
        database_available = False
        last_database_error = str(exc)
        logger.exception("PostgreSQL history read failed")
        return None

def append_history_to_db(role: str, text: str) -> bool:
    global database_available, last_database_error

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mensajes_conversacion (sesion_id, rol, contenido)
                    VALUES (%s, %s, %s)
                    """,
                    (settings.conversation_session_id, role, text),
                )
            conn.commit()
        return True
    except Exception as exc:
        database_available = False
        last_database_error = str(exc)
        logger.exception("PostgreSQL history write failed")
        return False

def append_turn_history_to_db(user_text: str, model_text: str) -> bool:
    global database_available, last_database_error

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO mensajes_conversacion (sesion_id, rol, contenido)
                    VALUES (%s, %s, %s)
                    """,
                    [
                        (settings.conversation_session_id, "user", user_text),
                        (settings.conversation_session_id, "model", model_text),
                    ],
                )
            conn.commit()
        return True
    except Exception as exc:
        database_available = False
        last_database_error = str(exc)
        logger.exception("PostgreSQL turn history write failed")
        return False

def strip_repeated_greeting(text: str, history: Optional[list[dict]] = None) -> str:
    return text

def normalize_voice_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"([!?.,])\1{2,}", r"\1", text)
    text = re.sub(r"\b(\w+)(\s+\1\b){2,}", r"\1", text, flags=re.IGNORECASE)
    return text.strip()

def is_simple_greeting(text: str) -> bool:
    return bool(re.match(r"^\s*(hola|buenos dias|buenas tardes|buenas noches|buen dia)\s*[!.?]*\s*$", text, flags=re.IGNORECASE))

def is_voice_noise(text: str) -> bool:
    if not text:
        return True
    return any(re.match(pattern, text, flags=re.IGNORECASE) for pattern in settings.voice_noise_patterns)

def make_error_response(message: str, status_code: int, exc: Exception | None = None) -> PlainTextResponse:
    error_id = uuid.uuid4().hex[:8]
    if exc is not None:
        logger.exception("%s [%s]", message, error_id)
    else:
        logger.warning("%s [%s]", message, error_id)
    return PlainTextResponse(f"{message}\nerror_id: {error_id}", status_code=status_code)

def gemini_error_message(response: httpx.Response, body: object) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("status")
            if detail:
                return f"Gemini respondio con error {response.status_code}: {detail}"
    return f"Gemini respondio con error {response.status_code}: {response.text[:500]}"

def write_prompt_file(name: str, text: str) -> bool:
    try:
        os.makedirs(settings.prompt_dir, exist_ok=True)
        path = os.path.join(settings.prompt_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception:
        return False

app = FastAPI()

@app.on_event("startup")
async def startup_event() -> None:
    global gemini_client
    init_database()
    gemini_client = httpx.AsyncClient(timeout=settings.gemini_timeout)

@app.on_event("shutdown")
async def shutdown_event() -> None:
    if gemini_client is not None:
        await gemini_client.aclose()

async def post_to_gemini(url: str, payload: dict, headers: dict) -> httpx.Response:
    if gemini_client is None:
        async with httpx.AsyncClient(timeout=settings.gemini_timeout) as client:
            return await client.post(url, json=payload, headers=headers)

    return await gemini_client.post(url, json=payload, headers=headers)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class EmergencyContact(BaseModel):
    name: str = ""
    relationship: str = ""
    phone: str = ""

class Medication(BaseModel):
    name: str = ""
    schedule: str = ""
    colorOrShape: str = ""

class SeniorProfile(BaseModel):
    personName: str = ""
    nickname: str = ""
    mobilityLevel: str = ""
    positivityState: str = ""
    generalMood: str = ""
    particularity: str = ""
    mobilityDetails: str = ""
    hasPreexistingDisease: bool = False
    preexistingDisease: str = ""
    requiresMedication: bool = False
    medications: list[Medication] = Field(default_factory=list)
    wakeTime: str = ""
    sleepTime: str = ""
    mainRoom: str = ""
    favoriteColor: str = ""
    favoriteTheme: str = ""
    dailyActivities: str = ""
    weeklyActivities: str = ""
    happinessTriggers: str = ""
    relaxationTriggers: str = ""
    sadnessTriggers: str = ""
    annoyanceTriggers: str = ""
    caregiverNotes: str = ""
    seniorNotes: str = ""
    emergencyContacts: list[EmergencyContact] = Field(default_factory=list)

class Prompt(BaseModel):
    prompt: str
    profile: Optional[SeniorProfile] = None

class AuthRegister(BaseModel):
    name: str
    email: str
    password: str

class AuthLogin(BaseModel):
    email: str
    password: str

class AuthGoogle(BaseModel):
    credential: str

class ProfilePayload(BaseModel):
    profile: SeniorProfile

def serialize_profile(profile: SeniorProfile) -> dict:
    if hasattr(profile, "model_dump"):
        return profile.model_dump()
    return profile.dict()

def get_user_by_email(email: str) -> Optional[dict]:
    if not database_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, nombre, email, password_hash, proveedor
                FROM usuarios
                WHERE email = %s
                """,
                (email.strip().lower(),),
            )
            row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "password_hash": row[3],
        "provider": row[4],
    }

def create_user(name: str, email: str, password: str, provider: str = "email") -> dict:
    if not database_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")

    normalized_email = email.strip().lower()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usuarios (nombre, email, password_hash, proveedor)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, nombre, email, proveedor
                    """,
                    (name.strip(), normalized_email, hash_password(password), provider),
                )
                row = cur.fetchone()
            conn.commit()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="El correo ya esta registrado")

    return {"id": row[0], "name": row[1], "email": row[2], "provider": row[3]}

def create_or_get_google_user(name: str, email: str) -> dict:
    existing_user = get_user_by_email(email)
    if existing_user:
        return existing_user
    return create_user(name, email, secrets.token_urlsafe(32), "google")

def verify_google_credential(credential: str) -> dict:
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google Login no esta configurado")

    try:
        claims = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Credencial de Google invalida") from exc

    email = str(claims.get("email", "")).strip().lower()
    email_verified = bool(claims.get("email_verified"))
    if not email or not email_verified:
        raise HTTPException(status_code=401, detail="Correo de Google no verificado")

    return {
        "name": str(claims.get("name") or email.split("@", 1)[0]).strip(),
        "email": email,
    }

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = hash_session_token(token)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM sesiones_usuario
                WHERE usuario_id = %s OR expira_en <= NOW()
                """,
                (user_id,),
            )
            cur.execute(
                """
                INSERT INTO sesiones_usuario (usuario_id, token, expira_en)
                VALUES (%s, %s, NOW() + (%s * INTERVAL '1 second'))
                """,
                (user_id, token_hash, settings.session_ttl_seconds),
            )
        conn.commit()
    return token

def get_user_by_token(token: Optional[str]) -> Optional[dict]:
    if not token or not database_available:
        return None
    token_hash = hash_session_token(token)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sesiones_usuario WHERE expira_en <= NOW()")
                cur.execute(
                    """
                    SELECT u.id, u.nombre, u.email, u.proveedor
                    FROM sesiones_usuario s
                    JOIN usuarios u ON u.id = s.usuario_id
                    WHERE s.token = %s
                      AND s.expira_en > NOW()
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE sesiones_usuario
                        SET ultimo_uso_en = NOW()
                        WHERE token = %s
                        """,
                        (token_hash,),
                    )
            conn.commit()
    except Exception as exc:
        logger.exception("Session lookup failed")
        raise HTTPException(status_code=500, detail="No se pudo validar la sesion") from exc

    if not row:
        return None

    return {"id": row[0], "name": row[1], "email": row[2], "provider": row[3]}

def require_user(authorization: Optional[str]) -> dict:
    user = get_user_by_token(extract_bearer_token(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="Sesion invalida o expirada")
    return user

def revoke_session(token: Optional[str]) -> None:
    if not token or not database_available:
        return
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM sesiones_usuario WHERE token = %s",
                    (hash_session_token(token),),
                )
            conn.commit()
    except Exception as exc:
        logger.exception("Session revoke failed")
        raise HTTPException(status_code=500, detail="No se pudo cerrar la sesion") from exc

def clean_text(value: Optional[str]) -> str:
    return (value or "").strip()

def clean_time(value: Optional[str]) -> Optional[str]:
    value = clean_text(value)
    return value or None

def format_db_time(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]

def save_profile_for_user(user_id: int, profile: SeniorProfile) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO adultos_mayores (
                    usuario_id,
                    nombre,
                    sobrenombre,
                    nivel_movilidad,
                    estado_positividad,
                    estado_animo_general,
                    habitacion_principal,
                    particularidad,
                    detalles_movilidad,
                    tiene_enfermedad_preexistente,
                    enfermedad_preexistente,
                    requiere_medicacion,
                    hora_levantarse,
                    hora_acostarse,
                    color_agrado,
                    tema_gusto,
                    actividades_diarias,
                    actividades_semanales,
                    detonantes_felicidad,
                    detonantes_relajacion,
                    detonantes_tristeza,
                    detonantes_molestia,
                    notas_cuidador,
                    notas_adulto_mayor
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::time, %s::time, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (usuario_id)
                DO UPDATE SET
                    nombre = EXCLUDED.nombre,
                    sobrenombre = EXCLUDED.sobrenombre,
                    nivel_movilidad = EXCLUDED.nivel_movilidad,
                    estado_positividad = EXCLUDED.estado_positividad,
                    estado_animo_general = EXCLUDED.estado_animo_general,
                    habitacion_principal = EXCLUDED.habitacion_principal,
                    particularidad = EXCLUDED.particularidad,
                    detalles_movilidad = EXCLUDED.detalles_movilidad,
                    tiene_enfermedad_preexistente = EXCLUDED.tiene_enfermedad_preexistente,
                    enfermedad_preexistente = EXCLUDED.enfermedad_preexistente,
                    requiere_medicacion = EXCLUDED.requiere_medicacion,
                    hora_levantarse = EXCLUDED.hora_levantarse,
                    hora_acostarse = EXCLUDED.hora_acostarse,
                    color_agrado = EXCLUDED.color_agrado,
                    tema_gusto = EXCLUDED.tema_gusto,
                    actividades_diarias = EXCLUDED.actividades_diarias,
                    actividades_semanales = EXCLUDED.actividades_semanales,
                    detonantes_felicidad = EXCLUDED.detonantes_felicidad,
                    detonantes_relajacion = EXCLUDED.detonantes_relajacion,
                    detonantes_tristeza = EXCLUDED.detonantes_tristeza,
                    detonantes_molestia = EXCLUDED.detonantes_molestia,
                    notas_cuidador = EXCLUDED.notas_cuidador,
                    notas_adulto_mayor = EXCLUDED.notas_adulto_mayor,
                    actualizado_en = NOW()
                RETURNING id
                """,
                (
                    user_id,
                    clean_text(profile.personName),
                    clean_text(profile.nickname),
                    clean_text(profile.mobilityLevel),
                    clean_text(profile.positivityState),
                    clean_text(profile.generalMood),
                    clean_text(profile.mainRoom),
                    clean_text(profile.particularity),
                    clean_text(profile.mobilityDetails),
                    profile.hasPreexistingDisease,
                    clean_text(profile.preexistingDisease),
                    profile.requiresMedication,
                    clean_time(profile.wakeTime),
                    clean_time(profile.sleepTime),
                    clean_text(profile.favoriteColor),
                    clean_text(profile.favoriteTheme),
                    clean_text(profile.dailyActivities),
                    clean_text(profile.weeklyActivities),
                    clean_text(profile.happinessTriggers),
                    clean_text(profile.relaxationTriggers),
                    clean_text(profile.sadnessTriggers),
                    clean_text(profile.annoyanceTriggers),
                    clean_text(profile.caregiverNotes),
                    clean_text(profile.seniorNotes),
                ),
            )
            adulto_mayor_id = cur.fetchone()[0]
            cur.execute(
                "DELETE FROM medicamentos_adulto_mayor WHERE adulto_mayor_id = %s",
                (adulto_mayor_id,),
            )
            for index, medication in enumerate(profile.medications):
                if not (medication.name or medication.schedule or medication.colorOrShape):
                    continue
                cur.execute(
                    """
                    INSERT INTO medicamentos_adulto_mayor (
                        adulto_mayor_id, nombre, horario, color_forma, orden
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        adulto_mayor_id,
                        clean_text(medication.name),
                        clean_text(medication.schedule),
                        clean_text(medication.colorOrShape),
                        index,
                    ),
                )
            cur.execute(
                "DELETE FROM contactos_emergencia WHERE adulto_mayor_id = %s",
                (adulto_mayor_id,),
            )
            for index, contact in enumerate(profile.emergencyContacts):
                if not (contact.name or contact.relationship or contact.phone):
                    continue
                cur.execute(
                    """
                    INSERT INTO contactos_emergencia (
                        adulto_mayor_id, nombre, parentesco, telefono, orden
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        adulto_mayor_id,
                        clean_text(contact.name),
                        clean_text(contact.relationship),
                        clean_text(contact.phone),
                        index,
                    ),
                )
        conn.commit()

def load_profile_for_user(user_id: int) -> Optional[SeniorProfile]:
    if not database_available:
        return None

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    nombre,
                    sobrenombre,
                    nivel_movilidad,
                    estado_positividad,
                    estado_animo_general,
                    habitacion_principal,
                    particularidad,
                    detalles_movilidad,
                    tiene_enfermedad_preexistente,
                    enfermedad_preexistente,
                    requiere_medicacion,
                    hora_levantarse,
                    hora_acostarse,
                    color_agrado,
                    tema_gusto,
                    actividades_diarias,
                    actividades_semanales,
                    detonantes_felicidad,
                    detonantes_relajacion,
                    detonantes_tristeza,
                    detonantes_molestia,
                    notas_cuidador,
                    notas_adulto_mayor
                FROM adultos_mayores
                WHERE usuario_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            adulto_mayor_id = row[0]
            cur.execute(
                """
                SELECT nombre, horario, color_forma
                FROM medicamentos_adulto_mayor
                WHERE adulto_mayor_id = %s
                ORDER BY orden, id
                """,
                (adulto_mayor_id,),
            )
            medications = [
                Medication(name=name, schedule=schedule, colorOrShape=color_shape)
                for name, schedule, color_shape in cur.fetchall()
            ]
            cur.execute(
                """
                SELECT nombre, parentesco, telefono
                FROM contactos_emergencia
                WHERE adulto_mayor_id = %s
                ORDER BY orden, id
                """,
                (adulto_mayor_id,),
            )
            emergency_contacts = [
                EmergencyContact(name=name, relationship=relationship, phone=phone)
                for name, relationship, phone in cur.fetchall()
            ]

    return SeniorProfile(
        personName=row[1],
        nickname=row[2],
        mobilityLevel=row[3],
        positivityState=row[4],
        generalMood=row[5],
        mainRoom=row[6],
        particularity=row[7],
        mobilityDetails=row[8],
        hasPreexistingDisease=row[9],
        preexistingDisease=row[10],
        requiresMedication=row[11],
        wakeTime=format_db_time(row[12]),
        sleepTime=format_db_time(row[13]),
        favoriteColor=row[14],
        favoriteTheme=row[15],
        dailyActivities=row[16],
        weeklyActivities=row[17],
        happinessTriggers=row[18],
        relaxationTriggers=row[19],
        sadnessTriggers=row[20],
        annoyanceTriggers=row[21],
        caregiverNotes=row[22],
        seniorNotes=row[23],
        medications=medications,
        emergencyContacts=emergency_contacts,
    )

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
    return {"status": "ok", "database_available": database_available}

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "database_available": database_available,
        "database_error": last_database_error,
        "gemini_url_configured": bool(settings.gemini_api_url),
        "gemini_key_configured": bool(settings.gemini_api_key),
        "max_output_tokens_limited": settings.gemini_max_output_tokens is not None,
    }

@app.post("/api/auth/register")
async def register(payload: AuthRegister):
    name = payload.name.strip()
    email = payload.email.strip().lower()
    password = payload.password

    if not name or not email or not password:
        raise HTTPException(status_code=400, detail="Completa nombre, correo y contrasena")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="La contrasena debe tener al menos 6 caracteres")

    user = create_user(name, email, password)
    token = create_session(user["id"])
    return {"token": token, "user": user}

@app.post("/api/auth/login")
async def login(payload: AuthLogin):
    email = payload.email.strip().lower()
    password = payload.password

    if not email or not password:
        raise HTTPException(status_code=400, detail="Ingresa correo y contrasena")

    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Correo o contrasena incorrectos")

    token = create_session(user["id"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "provider": user["provider"],
        },
    }

@app.post("/api/auth/google")
async def google_login(payload: AuthGoogle):
    google_user = verify_google_credential(payload.credential)
    user = create_or_get_google_user(google_user["name"], google_user["email"])
    token = create_session(user["id"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "provider": user["provider"],
        },
    }

@app.get("/api/auth/me")
async def me(authorization: Optional[str] = Header(None)):
    return {"user": require_user(authorization)}

@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    revoke_session(extract_bearer_token(authorization))
    return {"ok": True}

@app.get("/api/profile")
async def get_profile(authorization: Optional[str] = Header(None)):
    user = require_user(authorization)
    profile = load_profile_for_user(user["id"])
    return {"profile": serialize_profile(profile) if profile else None}

@app.post("/api/profile")
async def save_profile(payload: ProfilePayload, authorization: Optional[str] = Header(None)):
    user = require_user(authorization)
    save_profile_for_user(user["id"], payload.profile)
    return {"ok": True, "profile": serialize_profile(payload.profile)}

@app.get("/api/test", response_class=PlainTextResponse)
async def test():
    url = settings.gemini_api_url
    key = settings.gemini_api_key
    instr = read_prompt_file()

    if not url:
        return make_error_response("GEMINI_API_URL no esta configurado en .env", 400)
    if not key:
        return make_error_response("GEMINI_API_KEY no esta configurado en .env", 400)

    payload = build_gemini_payload(instr, "Hola Gemini")

    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": key
    }

    try:
        response = await post_to_gemini(url, payload, headers)
    except httpx.TimeoutException as exc:
        return make_error_response("Gemini tardo demasiado en responder", 504, exc)
    except httpx.HTTPError as exc:
        return make_error_response("No se pudo conectar con Gemini", 502, exc)
    except Exception as exc:
        return make_error_response("Error inesperado llamando a Gemini", 500, exc)

    try:
        j = response.json()
    except Exception:
        if response.is_error:
            return make_error_response(
                f"Gemini respondio con error {response.status_code}: {response.text[:500]}",
                response.status_code,
            )
        return PlainTextResponse(response.text or f"status: {response.status_code}", status_code=response.status_code)

    if response.is_error:
        return make_error_response(gemini_error_message(response, j), response.status_code)

    text = extract_text(j)
    if not text:
        return make_error_response("Gemini no devolvio texto util", 502)
    return PlainTextResponse(text)

@app.post("/api/gemini", response_class=PlainTextResponse)
async def gemini(p: Prompt, authorization: Optional[str] = Header(None)):
    url = settings.gemini_api_url
    key = settings.gemini_api_key
    instr = read_prompt_file()

    if not url:
        return make_error_response("GEMINI_API_URL no esta configurado en .env", 400)
    if not key:
        return make_error_response("GEMINI_API_KEY no esta configurado en .env", 400)

    user_text = normalize_voice_text(p.prompt)
    if is_voice_noise(user_text):
        return make_error_response("No recibi un mensaje de voz claro. Intenta hablar de nuevo.", 400)

    profile = p.profile
    user = get_user_by_token(extract_bearer_token(authorization))
    if profile is None and user:
        profile = load_profile_for_user(user["id"])

    personalized_user_text = build_personalized_user_text(user_text, profile)
    recent_history = [] if is_simple_greeting(user_text) else get_recent_history()
    payload = build_gemini_payload(instr, personalized_user_text, recent_history)

    headers = {"Content-Type": "application/json", "X-goog-api-key": key}

    try:
        response = await post_to_gemini(url, payload, headers)
    except httpx.TimeoutException as exc:
        return make_error_response("Gemini tardo demasiado en responder", 504, exc)
    except httpx.HTTPError as exc:
        return make_error_response("No se pudo conectar con Gemini", 502, exc)
    except Exception as exc:
        return make_error_response("Error inesperado llamando a Gemini", 500, exc)

    try:
        j = response.json()
    except Exception:
        if response.is_error:
            return make_error_response(
                f"Gemini respondio con error {response.status_code}: {response.text[:500]}",
                response.status_code,
            )
        return PlainTextResponse(response.text or f"status: {response.status_code}", status_code=response.status_code)

    if response.is_error:
        return make_error_response(gemini_error_message(response, j), response.status_code)

    text = strip_repeated_greeting(extract_text(j), recent_history)
    if not text:
        return make_error_response("Gemini no devolvio texto util", 502)

    append_turn_history(user_text, text)
    return PlainTextResponse(text)


# Prompt management endpoints: view and update prompt files
class PromptUpdate(BaseModel):
    text: str


@app.get("/api/prompt")
async def get_default_prompt():
    content = read_prompt_file()
    return {"file": settings.prompt_file, "text": content}


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
