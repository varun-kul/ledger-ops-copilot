"""
Interactive CLI for the copilot. Ask questions in plain English about
reconciliation breaks and fraud flags.

Run:
    python scripts/run_copilot.py
    python scripts/run_copilot.py "which transactions had amount mismatches?"

Requires data/reconciliation_report.json and data/fraud_flags.json to exist
first (run run_reconciliation.py and run_fraud_detection.py).
For real generated answers, install Ollama (https://ollama.com) and run:
    ollama pull llama3.1
Without it, the fallback client shows retrieved context instead of a
generated answer -- still useful for verifying retrieval works.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.copilot.index import load_index
from app.copilot.query import ask

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _safe_ask(question: str, index) -> str:
    """Wraps ask() so a single failed/timed-out API call doesn't crash the
    whole session -- especially important in the interactive loop below,
    where you don't want one bad question to end the conversation."""
    try:
        result = ask(question, index)
        return result.format_with_sources()
    except Exception as e:
        return (f"Copilot request failed ({type(e).__name__}: {e}). "
                f"This is usually transient (rate limit, slow network) -- try again.")


def main():
    for required in ("reconciliation_report.json", "fraud_flags.json"):
        if not (DATA_DIR / required).exists():
            print(f"Missing {required} -- run the week 1/2 pipeline scripts first.")
            return

    index = load_index(DATA_DIR / "reconciliation_report.json", DATA_DIR / "fraud_flags.json")
    print(f"Indexed {len(index.documents)} documents "
          f"(reconciliation breaks + fraud flags).\n")

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(_safe_ask(question, index))
        return

    print("LedgerOps Copilot -- ask a question (empty line to quit)\n")
    while True:
        question = input("> ").strip()
        if not question:
            break
        print(_safe_ask(question, index))
        print()


if __name__ == "__main__":
    main()