"""
Single shared entry point for every real LLM call in the app (both
agents use this — nothing else in the codebase talks to Groq directly).
Centralizing it here means: one place to swap models, one place to
handle errors/timeouts, one place to enforce "explanations must be
grounded in the facts we pass in, not invented."
"""
from __future__ import annotations

from groq import Groq

from app.config import settings

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to backend/.env (see .env.example)."
            )
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 600) -> str:
    """One-shot grounded completion."""
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


def chat_with_history(system_prompt: str, history: list[dict], temperature: float = 0.4, max_tokens: int = 500) -> str:
    """
    history: list of {"role": "user"|"assistant", "content": str}, most recent last.
    Used by the merchant assistant chat (Module 10 — Ask RevShield) to keep
    conversational context across turns.
    """
    client = _get_client()
    messages = [{"role": "system", "content": system_prompt}] + history
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()
