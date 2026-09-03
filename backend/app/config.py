"""
Central configuration. Everything is read from environment variables
(loaded from a .env file in the backend/ directory) so no secrets ever
live in code.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24 * 7

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./revshield.db")
    CHROMA_DIR: str = os.getenv("CHROMA_DIR", "./chroma_db")


settings = Settings()

if not settings.GROQ_API_KEY:
    # We don't crash on import (so the API can still boot and the frontend
    # can show a clear "set your API key" message) — but every agent call
    # will fail loudly until this is set.
    print(
        "[revshield] WARNING: GROQ_API_KEY is not set. "
        "Copy backend/.env.example to backend/.env and add your key."
    )
