"""
End-to-end week 1 pipeline: load all three sources, reconcile, write a
report. This is the thing you'd actually demo on a call.

Run:
    python scripts/run_reconciliation.py
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingestion.legacy_csv import load_legacy_ledger
from app.ingestion.live_stream import load_live_stream_from_jsonl
from app.ingestion.stripe_source import load_stripe_transactions
from app.reconciliation.engine import reconcile

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main():
    legacy, skipped_rows = load_legacy_ledger(DATA_DIR / "legacy_ledger_sample.csv")
    stripe = load_stripe_transactions(DATA_DIR / "stripe_fixture.json")
    live = load_live_stream_from_jsonl(DATA_DIR / "live_stream_events.jsonl")

    report = reconcile(legacy, stripe, live)
    summary = report.summary()

    print("\n=== Reconciliation Summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")

    if skipped_rows:
        print(f"\n{len(skipped_rows)} legacy ledger rows were unparseable/duplicate "
              f"(see data/reconciliation_report.json -> skipped_ledger_rows for detail)")

    critical = [b for b in report.breaks if b.severity == "critical"]
    if critical:
        print(f"\n{len(critical)} CRITICAL breaks -- top 5:")
        for b in critical[:5]:
            print(f"  [{b.reason.value}] {b.txn_ref}: {b.detail}")

    out_path = DATA_DIR / "reconciliation_report.json"
    with open(out_path, "w") as f:
        json.dump({
            "summary": summary,
            "breaks": [b.to_dict() for b in report.breaks],
            "skipped_ledger_rows": skipped_rows,
        }, f, indent=2)
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
