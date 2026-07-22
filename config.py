import os
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv


load_dotenv()


BASE_DIR = os.path.dirname(__file__)
DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "https://geriafab-frontend.vercel.app",
)
DEFAULT_VOICE_NOISE_PATTERNS = (
    r"^\s*(eh+|em+|mmm+|um+|uh+|este)\s*$",
    r"^\s*string\s*$",
    r"^\s*(no se escucho|no se escucha|audio vacio|sin audio)\s*$",
    r"^\s*(subtitulos por la comunidad|gracias por ver|thank you for watching)\s*$",
)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def _get_csv(name: str, default_values: tuple[str, ...]) -> list[str]:
    raw_value = os.getenv(name, ",".join(default_values))
    return [value.strip() for value in raw_value.split(",") if value.strip()]


def _get_optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value or value == "0":
        return None
    return int(value)


@dataclass(frozen=True)
class Settings:
    prompt_dir: str = field(default_factory=lambda: os.getenv("PROMPT_DIR", os.path.join(BASE_DIR, "prompts")))
    prompt_file: str = field(default_factory=lambda: os.getenv("PROMPT_FILE", "default.txt"))
    prompt_instructions: str = field(default_factory=lambda: os.getenv("PROMPT_INSTRUCTIONS", ""))
    prompt_include_datetime: bool = field(default_factory=lambda: _get_bool("PROMPT_INCLUDE_DATETIME", True))

    max_history_messages: int = field(default_factory=lambda: int(os.getenv("MAX_HISTORY_MESSAGES", "12")))
    history_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("HISTORY_TTL_SECONDS", "0")))
    conversation_session_id: str = field(default_factory=lambda: os.getenv("CONVERSATION_SESSION_ID", "default"))

    database_url: str | None = field(default_factory=lambda: os.getenv("DATABASE_URL"))
    google_client_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_ID", "").strip())
    cors_allowed_origins: list[str] = field(default_factory=lambda: _get_csv("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS))

    gemini_api_url: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_URL"))
    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    gemini_temperature: float = field(default_factory=lambda: float(os.getenv("GEMINI_TEMPERATURE", "0.5")))
    gemini_max_output_tokens: int | None = field(default_factory=lambda: _get_optional_int("GEMINI_MAX_OUTPUT_TOKENS"))
    gemini_timeout: httpx.Timeout = field(
        default_factory=lambda: httpx.Timeout(
            connect=float(os.getenv("GEMINI_CONNECT_TIMEOUT", "10")),
            read=float(os.getenv("GEMINI_READ_TIMEOUT", "30")),
            write=float(os.getenv("GEMINI_WRITE_TIMEOUT", "30")),
            pool=float(os.getenv("GEMINI_POOL_TIMEOUT", "30")),
        )
    )

    youtube_api_key: str = field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY", "").strip())

    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    password_hash_iterations: int = field(default_factory=lambda: int(os.getenv("PASSWORD_HASH_ITERATIONS", "310000")))
    session_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 3650))))
    voice_noise_patterns: tuple[str, ...] = DEFAULT_VOICE_NOISE_PATTERNS


settings = Settings()
