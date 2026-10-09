import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_copilot import _safe_ask


def test_safe_ask_returns_readable_message_on_exception(monkeypatch):
    def broken_ask(question, index):
        raise TimeoutError("simulated network timeout")

    monkeypatch.setattr("scripts.run_copilot.ask", broken_ask)

    result = _safe_ask("any question", index=MagicMock())

    assert "failed" in result.lower()
    assert "TimeoutError" in result
    assert "simulated network timeout" in result