"""
Runs fraud detection over the live transaction stream and writes flags to
data/fraud_flags.json.

Run:
    python scripts/run_fraud_detection.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.fraud.rules import detect_fraud
from app.ingestion.live_stream import load_live_stream_from_jsonl

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main():
    transactions = load_live_stream_from_jsonl(DATA_DIR / "live_stream_events.jsonl")
    flags = detect_fraud(transactions)

    print(f"\n=== Fraud Detection Summary ===")
    print(f"transactions scanned: {len(transactions)}")
    print(f"flags raised: {len(flags)}")

    by_rule = Counter(f.rule.value for f in flags)
    by_severity = Counter(f.severity for f in flags)
    print(f"by rule: {dict(by_rule)}")
    print(f"by severity: {dict(by_severity)}")

    critical = [f for f in flags if f.severity == "critical"]
    if critical:
        print(f"\n{len(critical)} CRITICAL flags:")
        for f in critical[:5]:
            print(f"  [{f.rule.value}] {f.txn_refs}: {f.explanation}")

    out_path = DATA_DIR / "fraud_flags.json"
    with open(out_path, "w") as f:
        json.dump({
            "summary": {"scanned": len(transactions), "flags": len(flags),
                        "by_rule": dict(by_rule), "by_severity": dict(by_severity)},
            "flags": [flag.to_dict() for flag in flags],
        }, f, indent=2)
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()