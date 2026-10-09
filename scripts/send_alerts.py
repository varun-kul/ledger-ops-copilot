"""
Loads the latest reconciliation report and fraud flags, filters down to
what's actually alert-worthy (see app/alerts/escalation.py), and posts to
Slack.

Run after run_reconciliation.py and run_fraud_detection.py:
    python scripts/send_alerts.py

Set SLACK_WEBHOOK_URL in .env to actually post; without it, alerts print
to stdout instead (see app/alerts/slack.py).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alerts.escalation import select_alertworthy_breaks, select_alertworthy_flags
from app.alerts.slack import build_alert_message, post_to_slack
from app.db.models import BreakReason, FraudFlag, FraudRuleName, ReconciliationBreak, SourceName

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_breaks() -> list[ReconciliationBreak]:
    with open(DATA_DIR / "reconciliation_report.json") as f:
        data = json.load(f)
    return [
        ReconciliationBreak(
            txn_ref=b["txn_ref"], reason=BreakReason(b["reason"]), detail=b["detail"],
            severity=b["severity"],
            sources_present=[SourceName(s) for s in b["sources_present"]],
            sources_missing=[SourceName(s) for s in b["sources_missing"]],
            records=[],  # not needed for alerting, and not serialized in the report
        )
        for b in data["breaks"]
    ]


def _load_flags() -> list[FraudFlag]:
    with open(DATA_DIR / "fraud_flags.json") as f:
        data = json.load(f)
    return [
        FraudFlag(txn_refs=f["txn_refs"], rule=FraudRuleName(f["rule"]),
                   explanation=f["explanation"], severity=f["severity"], evidence=f["evidence"])
        for f in data["flags"]
    ]


def main():
    for required in ("reconciliation_report.json", "fraud_flags.json"):
        if not (DATA_DIR / required).exists():
            print(f"Missing {required} -- run run_reconciliation.py / run_fraud_detection.py first.")
            return

    all_breaks = _load_breaks()
    all_flags = _load_flags()

    alert_breaks = select_alertworthy_breaks(all_breaks)
    alert_flags = select_alertworthy_flags(all_flags)

    print(f"{len(all_breaks)} total breaks -> {len(alert_breaks)} alert-worthy")
    print(f"{len(all_flags)} total flags -> {len(alert_flags)} alert-worthy "
          f"({len(all_flags) - len(alert_flags)} suppressed as noise, still in audit record)")

    message = build_alert_message(alert_breaks, alert_flags)
    if message is None:
        print("Nothing alert-worthy -- not posting.")
        return

    post_to_slack(message)


if __name__ == "__main__":
    main()