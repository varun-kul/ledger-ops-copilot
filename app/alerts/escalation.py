"""
Decides which breaks/flags are worth paging Slack for, as opposed to just
sitting in the audit record. See docs/feedback-log.md for the full story --
short version: geo_mismatch alone has a high false-positive rate (measured
~18% in week 2 testing), and after the first simulated customer feedback
("ops muted the channel, too noisy"), we stopped Slack-alerting on
geo_mismatch UNLESS it co-occurs with another signal on the same
transaction. Every flag still gets written to fraud_flags.json regardless --
this only changes what pages a human, never what's recorded (Marcus's audit
requirement is untouched by this change).
"""
from __future__ import annotations

from collections import Counter

from app.db.models import BreakReason, FraudFlag, FraudRuleName, ReconciliationBreak


def select_alertworthy_breaks(breaks: list[ReconciliationBreak]) -> list[ReconciliationBreak]:
    """Only critical-severity reconciliation breaks page Slack. Warning/info
    breaks are still in the report and the copilot's index -- just not an
    interruption."""
    return [b for b in breaks if b.severity == "critical"]


def select_alertworthy_flags(flags: list[FraudFlag]) -> list[FraudFlag]:
    """
    velocity and amount_outlier always alert (low false-positive rate,
    genuinely rare events worth a human looking at immediately).

    geo_mismatch only alerts when at least one of its transactions ALSO
    appears in another flag -- i.e. a legitimate signal is reinforcing it,
    not just "unusual country" on its own. This is the direct fix for the
    feedback cycle in docs/feedback-log.md.
    """
    ref_counts: Counter[str] = Counter()
    for f in flags:
        for ref in f.txn_refs:
            ref_counts[ref] += 1

    alertworthy = []
    for f in flags:
        if f.rule != FraudRuleName.GEO_MISMATCH:
            alertworthy.append(f)
        elif any(ref_counts[ref] > 1 for ref in f.txn_refs):
            alertworthy.append(f)
    return alertworthy