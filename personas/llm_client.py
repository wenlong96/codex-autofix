"""
LLM client abstraction.

Provider-agnostic interface so we can swap between Gemini and OpenAI via
a single env var change (LLM_PROVIDER=gemini|openai).

The persona code never sees vendor-specific API shapes. Add a new provider
by writing one ~30-line adapter class and registering it below.
"""

from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """Normalized response from any provider."""

    text: str
    raw: Any  # vendor-specific raw response, for debugging


class LLMClient(ABC):
    """One method to rule them all."""

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Send a single turn. Optional image attachment."""

    def complete_json(
        self,
        system: str,
        user: str,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        temperature: float = 0.4,
        max_tokens: int = 1024,
    ) -> dict:
        """Convenience: complete + parse JSON."""
        resp = self.complete(
            system=system,
            user=user,
            image_bytes=image_bytes,
            image_mime=image_mime,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = resp.text.strip()
        # Strip code fences if the model wrapped JSON in ```json ... ```
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip().rstrip("`").strip()
        return json.loads(text)


# ---------------------------------------------------------------------------
# Gemini adapter
# ---------------------------------------------------------------------------

class GeminiClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash-lite"):
        # Lazy import so OpenAI-only users don't need google-genai installed
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def complete(
        self,
        system: str,
        user: str,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        from google.genai import types

        parts: list[Any] = [user]
        if image_bytes is not None:
            parts.append(
                types.Part.from_bytes(data=image_bytes, mime_type=image_mime)
            )

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if json_mode:
            config.response_mime_type = "application/json"

        resp = self.client.models.generate_content(
            model=self.model,
            contents=parts,
            config=config,
        )
        return LLMResponse(text=resp.text or "", raw=resp)


# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------

class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def complete(
        self,
        system: str,
        user: str,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        # Build user content (text + optional image)
        if image_bytes is not None:
            b64 = base64.b64encode(image_bytes).decode()
            user_content: Any = [
                {"type": "text", "text": user},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_mime};base64,{b64}"},
                },
            ]
        else:
            user_content = user

        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = self.client.chat.completions.create(**kwargs)
        return LLMResponse(text=resp.choices[0].message.content or "", raw=resp)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm_client() -> LLMClient:
    """
    Return the configured client based on env vars.

    Required env:
        LLM_PROVIDER         "gemini" (default) or "openai"
        GEMINI_API_KEY       if provider == gemini
        OPENAI_API_KEY       if provider == openai

    Optional env:
        GEMINI_MODEL         default: gemini-2.5-flash-lite
        OPENAI_MODEL         default: gpt-4o-mini
    """
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()

    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Add it to your .env file."
            )
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
        return GeminiClient(api_key=key, model=model)

    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to your .env file."
            )
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        return OpenAIClient(api_key=key, model=model)

    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}. Use 'gemini' or 'openai'."
    )
