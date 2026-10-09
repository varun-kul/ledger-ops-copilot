"""
Tests the client selection priority and each backend's request/response
handling using mocked HTTP calls -- no real network access or API keys
needed to run these (important since CI and this sandbox have neither).
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from app.copilot.llm_client import (
    FallbackClient,
    GeminiClient,
    NvidiaClient,
    OllamaClient,
    get_llm_client,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every test starts with no API keys set, regardless of the real
    environment this suite runs in -- avoids false passes/failures based on
    who's running it."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


def test_falls_back_to_fallback_client_when_nothing_available():
    with patch.object(OllamaClient, "is_available", return_value=False):
        client = get_llm_client()
    assert isinstance(client, FallbackClient)


def test_prefers_gemini_over_nvidia_when_both_keys_set(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "fake-nvidia-key")
    with patch.object(OllamaClient, "is_available", return_value=False):
        client = get_llm_client()
    assert isinstance(client, GeminiClient)


def test_falls_back_to_nvidia_when_only_nvidia_key_set(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "fake-nvidia-key")
    with patch.object(OllamaClient, "is_available", return_value=False):
        client = get_llm_client()
    assert isinstance(client, NvidiaClient)


def test_prefers_ollama_over_cloud_apis_when_available(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    with patch.object(OllamaClient, "is_available", return_value=True):
        client = get_llm_client()
    assert isinstance(client, OllamaClient)


def test_gemini_client_parses_response_correctly(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    client = GeminiClient()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "  the answer  "}]}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = client.generate("some prompt")

    assert result == "the answer"
    call_url = mock_post.call_args[0][0]
    assert "fake-key" in call_url
    assert "generativelanguage.googleapis.com" in call_url


def test_nvidia_client_parses_response_correctly(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "fake-key")
    client = NvidiaClient()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "  the answer  "}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = client.generate("some prompt")

    assert result == "the answer"
    call_headers = mock_post.call_args.kwargs["headers"]
    assert call_headers["Authorization"] == "Bearer fake-key"


def test_fallback_client_shows_prompt_and_disclaimer():
    result = FallbackClient().generate("some prompt")
    assert "NO LLM AVAILABLE" in result
    assert "some prompt" in result