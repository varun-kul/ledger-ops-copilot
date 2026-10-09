"""
Marcus's standing ask from the week 1 discovery call, finally addressed:
"whatever you build, I need to be able to explain any flag to an auditor."
Up to now that's meant every break/flag being explainable in the JSON
reports and the copilot -- this script produces the actual artifact an
external auditor would want: one flat, chronological CSV covering every
reconciliation break AND every fraud flag (alert-worthy or not -- audit
completeness, same principle as fraud_flags.json always keeping everything).

Run:
    python scripts/export_audit_trail.py
    python scripts/export_audit_trail.py --output data/audit_2026_08.csv
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FIELDNAMES = ["record_type", "txn_ref", "reason_or_rule", "severity",
              "detail_or_explanation", "sources_present_or_evidence", "alertworthy"]


def _breaks_rows(recon: dict, alertworthy_refs: set[str]) -> list[dict]:
    rows = []
    for b in recon["breaks"]:
        rows.append({
            "record_type": "reconciliation_break",
            "txn_ref": b["txn_ref"],
            "reason_or_rule": b["reason"],
            "severity": b["severity"],
            "detail_or_explanation": b["detail"],
            "sources_present_or_evidence": "; ".join(b["sources_present"]) or "none",
            "alertworthy": b["txn_ref"] in alertworthy_refs,
        })
    return rows


def _flags_rows(fraud: dict, alertworthy_refs: set[str]) -> list[dict]:
    rows = []
    for f in fraud["flags"]:
        rows.append({
            "record_type": "fraud_flag",
            "txn_ref": "; ".join(f["txn_refs"]),
            "reason_or_rule": f["rule"],
            "severity": f["severity"],
            "detail_or_explanation": f["explanation"],
            "sources_present_or_evidence": json.dumps(f.get("evidence", {})),
            "alertworthy": any(ref in alertworthy_refs for ref in f["txn_refs"]),
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=None, help="Output CSV path (default: data/audit_trail.csv)")
    args = parser.parse_args()

    for required in ("reconciliation_report.json", "fraud_flags.json"):
        if not (DATA_DIR / required).exists():
            print(f"Missing {required} -- run the pipeline scripts first.")
            return

    from app.alerts.escalation import select_alertworthy_breaks, select_alertworthy_flags
    from app.db.models import BreakReason, FraudFlag, FraudRuleName, ReconciliationBreak, SourceName

    with open(DATA_DIR / "reconciliation_report.json") as f:
        recon = json.load(f)
    with open(DATA_DIR / "fraud_flags.json") as f:
        fraud = json.load(f)

    breaks = [
        ReconciliationBreak(b["txn_ref"], BreakReason(b["reason"]), b["detail"], b["severity"],
                             [SourceName(s) for s in b["sources_present"]],
                             [SourceName(s) for s in b["sources_missing"]], [])
        for b in recon["breaks"]
    ]
    flags = [
        FraudFlag(f["txn_refs"], FraudRuleName(f["rule"]), f["explanation"], f["severity"], f["evidence"])
        for f in fraud["flags"]
    ]

    alertworthy_refs = {b.txn_ref for b in select_alertworthy_breaks(breaks)}
    alertworthy_refs |= {ref for f in select_alertworthy_flags(flags) for ref in f.txn_refs}

    rows = _breaks_rows(recon, alertworthy_refs) + _flags_rows(fraud, alertworthy_refs)
    rows.sort(key=lambda r: (r["severity"] != "critical", r["record_type"], r["txn_ref"]))

    output_path = Path(args.output) if args.output else DATA_DIR / "audit_trail.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} records ({len(recon['breaks'])} breaks + {len(fraud['flags'])} flags) "
          f"-> {output_path}")
    print(f"{len(alertworthy_refs)} distinct transactions were alert-worthy "
          f"(would have paged Slack); every record is in this export regardless.")


if __name__ == "__main__":
    main()