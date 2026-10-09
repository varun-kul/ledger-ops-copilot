"""
LLM client for the copilot's answer generation. Four backends behind one
interface, tried in priority order by get_llm_client():

  1. OllamaClient  -- local, free forever, no API key, transaction data never
     leaves the machine. The intended long-term backend once it's installed.
  2. GeminiClient   -- Google AI Studio free tier. Cloud-hosted: fast, no local
     setup, but transaction data leaves the machine and the free tier is
     rate-limited. Fine for this portfolio project; for a real fintech
     customer this would need a compliance/data-processing review first
     (Marcus's "no black box" instinct extends to "no data leaves our
     infrastructure" in practice).
  3. NvidiaClient   -- NVIDIA NIM free tier (build.nvidia.com). Same cloud
     trade-off as Gemini, different provider/model catalog.
  4. FallbackClient -- no LLM at all, returns the retrieved context directly.
     Exists so the copilot is always runnable with zero setup, and so
     retrieval can be verified even with no LLM configured anywhere.

get_llm_client() checks each in order and logs which one it picked -- same
pattern as stripe_source.py's live/fixture switch in week 1.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

# Load .env into os.environ if python-dotenv is installed and a .env file
# exists. Optional dependency, same graceful-fallback pattern as stripe_source.py
# -- if it's not installed, real environment variables (export ... in your
# shell) still work exactly as before.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"  # pull with: ollama pull llama3.1

GEMINI_MODEL = "gemini-3.5-flash"
NVIDIA_MODEL = "meta/llama-3.1-8b-instruct"
NVIDIA_HOST = "https://integrate.api.nvidia.com/v1/chat/completions"


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str: ...


class OllamaClient:
    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL):
        self.host = host
        self.model = model

    def generate(self, prompt: str) -> str:
        import requests

        response = requests.post(
            f"{self.host}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["response"].strip()

    def is_available(self) -> bool:
        import requests

        try:
            r = requests.get(f"{self.host}/api/tags", timeout=2)
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False


class GeminiClient:
    """Free tier via Google AI Studio (https://ai.google.dev) -- generate a
    key there, no card required. Rate-limited on the free tier (currently a
    handful of requests/minute for flash models); fine for demo use."""

    def __init__(self, model: str = GEMINI_MODEL):
        self.model = model
        self.api_key = os.environ["GEMINI_API_KEY"]

    def generate(self, prompt: str) -> str:
        import requests

        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent")
        response = requests.post(
            url,
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


class NvidiaClient:
    """Free tier via NVIDIA NIM (https://build.nvidia.com) -- OpenAI-compatible
    chat completions endpoint. Generate a key there, no card required for the
    free tier."""

    def __init__(self, model: str = NVIDIA_MODEL, host: str = NVIDIA_HOST):
        self.model = model
        self.host = host
        self.api_key = os.environ["NVIDIA_API_KEY"]

    def generate(self, prompt: str) -> str:
        import requests

        response = requests.post(
            self.host,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Accept": "application/json"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.2,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


class FallbackClient:
    """No model -- just formats the retrieved context as a direct answer.
    Makes the copilot runnable with zero setup; clearly not a substitute for
    the real thing."""

    def generate(self, prompt: str) -> str:
        return (
            "[NO LLM AVAILABLE -- configure Ollama, GEMINI_API_KEY, or "
            "NVIDIA_API_KEY for a real generated answer. Showing raw "
            "retrieved context instead:]\n\n" + prompt
        )


def get_llm_client() -> LLMClient:
    ollama = OllamaClient()
    if ollama.is_available():
        logger.info("using Ollama (%s) for generation", ollama.model)
        return ollama

    if os.environ.get("GEMINI_API_KEY"):
        logger.info("Ollama not reachable -- using Gemini (%s) for generation", GEMINI_MODEL)
        return GeminiClient()

    if os.environ.get("NVIDIA_API_KEY"):
        logger.info("Ollama not reachable, no GEMINI_API_KEY -- using NVIDIA NIM (%s)", NVIDIA_MODEL)
        return NvidiaClient()

    logger.warning("No LLM backend available (Ollama not running, no GEMINI_API_KEY or "
                    "NVIDIA_API_KEY set) -- using fallback (no-LLM) client.")
    return FallbackClient()