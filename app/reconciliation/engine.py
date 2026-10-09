"""
Core reconciliation logic. Groups normalized transactions from all three
sources by txn_ref and decides, per group, whether it's clean or a break --
and if a break, what kind and how severe.

Design decision worth calling out (this is the kind of thing to talk about
in an interview): a naive "set A - set B" diff would flag every transaction
from the last 18 hours as MISSING_IN_LEDGER, because the legacy batch export
simply hasn't run yet. That's not a break, it's expected settlement lag. So
every "missing" check is gated by a settlement window per source, not a bare
diff. Getting this wrong is exactly how you'd ship something that pages an
on-call ops person at 2am for nothing -- eroding trust in the system fast.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db.models import BreakReason, NormalizedTransaction, ReconciliationBreak, SourceName

# How long to wait before flagging a transaction as missing from a given
# source. Legacy ledger is nightly-batch, so it gets a generous window;
# Stripe and the live stream should be near-real-time.
SETTLEMENT_WINDOWS = {
    SourceName.LEGACY_LEDGER: timedelta(hours=20),
    SourceName.STRIPE: timedelta(minutes=15),
    SourceName.LIVE_STREAM: timedelta(minutes=2),
}

AMOUNT_MISMATCH_TOLERANCE_CENTS = 0  # any difference is flagged; severity varies by size


@dataclass
class ReconciliationReport:
    total_refs: int
    clean_count: int
    breaks: list[ReconciliationBreak]
    generated_at: datetime

    def summary(self) -> dict:
        by_reason: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        for b in self.breaks:
            by_reason[b.reason.value] += 1
            by_severity[b.severity] += 1
        return {
            "total_refs": self.total_refs,
            "clean_count": self.clean_count,
            "break_count": len(self.breaks),
            "by_reason": dict(by_reason),
            "by_severity": dict(by_severity),
            "generated_at": self.generated_at.isoformat(),
        }


def reconcile(
    legacy: list[NormalizedTransaction],
    stripe: list[NormalizedTransaction],
    live: list[NormalizedTransaction],
    now: datetime | None = None,
) -> ReconciliationReport:
    now = now or datetime.now(timezone.utc)

    by_ref: dict[str, dict[SourceName, list[NormalizedTransaction]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in (*legacy, *stripe, *live):
        by_ref[record.txn_ref][record.source].append(record)

    breaks: list[ReconciliationBreak] = []
    clean_count = 0

    for ref, sources in by_ref.items():
        record_breaks = _check_duplicates(ref, sources)
        breaks.extend(record_breaks)

        present = [s for s in SourceName if sources.get(s)]
        missing = [s for s in SourceName if not sources.get(s)]

        # earliest timestamp we've seen for this ref, across sources present --
        # used to decide whether "missing" is still within a source's expected lag
        earliest_ts = min(r.ts for recs in sources.values() for r in recs)

        real_missing = [
            s for s in missing
            if now - earliest_ts > SETTLEMENT_WINDOWS[s]
        ]
        if real_missing:
            breaks.append(_missing_break(ref, present, real_missing, sources))
            continue

        if len(present) >= 2:
            mismatch = _check_amount_and_currency(ref, sources)
            if mismatch:
                breaks.append(mismatch)
                continue

        if not real_missing and not missing:
            drift = _check_timing_drift(ref, sources)
            if drift:
                breaks.append(drift)

        if ref not in {b.txn_ref for b in breaks}:
            clean_count += 1

    return ReconciliationReport(
        total_refs=len(by_ref),
        clean_count=clean_count,
        breaks=breaks,
        generated_at=now,
    )


def _check_duplicates(ref: str, sources: dict) -> list[ReconciliationBreak]:
    out = []
    for source_name, records in sources.items():
        if len(records) > 1:
            out.append(ReconciliationBreak(
                txn_ref=ref,
                reason=BreakReason.DUPLICATE_IN_SOURCE,
                detail=f"{len(records)} records for {ref} in {source_name.value}",
                severity="warning",
                sources_present=[source_name],
                sources_missing=[],
                records=records,
            ))
    return out


def _missing_break(ref, present, missing, sources) -> ReconciliationBreak:
    reason_map = {
        SourceName.LEGACY_LEDGER: BreakReason.MISSING_IN_LEDGER,
        SourceName.STRIPE: BreakReason.MISSING_IN_STRIPE,
        SourceName.LIVE_STREAM: BreakReason.MISSING_IN_LIVE_STREAM,
    }
    # if only one source is missing it, that's the clearer story; report on the first
    primary_missing = missing[0]
    all_records = [r for recs in sources.values() for r in recs]
    severity = "critical" if len(missing) > 1 else "warning"
    return ReconciliationBreak(
        txn_ref=ref,
        reason=reason_map[primary_missing],
        detail=f"{ref} present in {[s.value for s in present]}, "
               f"missing from {[s.value for s in missing]} past settlement window",
        severity=severity,
        sources_present=present,
        sources_missing=missing,
        records=all_records,
    )


def _check_amount_and_currency(ref: str, sources: dict) -> ReconciliationBreak | None:
    all_records = [r for recs in sources.values() for r in recs]
    amounts = {r.amount_cents for r in all_records}
    currencies = {r.currency for r in all_records}

    if len(currencies) > 1:
        return ReconciliationBreak(
            txn_ref=ref,
            reason=BreakReason.CURRENCY_MISMATCH,
            detail=f"currency mismatch across sources: {currencies}",
            severity="critical",
            sources_present=list(sources.keys()),
            sources_missing=[],
            records=all_records,
        )

    if len(amounts) > 1:
        spread = max(amounts) - min(amounts)
        severity = "critical" if spread > 100 else "warning"  # >$1 diff = critical
        return ReconciliationBreak(
            txn_ref=ref,
            reason=BreakReason.AMOUNT_MISMATCH,
            detail=f"amount mismatch across sources: {sorted(amounts)} cents",
            severity=severity,
            sources_present=list(sources.keys()),
            sources_missing=[],
            records=all_records,
        )
    return None


def _check_timing_drift(ref: str, sources: dict, threshold_minutes: int = 30) -> ReconciliationBreak | None:
    all_records = [r for recs in sources.values() for r in recs]
    timestamps = [r.ts for r in all_records]
    drift = max(timestamps) - min(timestamps)
    if drift > timedelta(minutes=threshold_minutes):
        return ReconciliationBreak(
            txn_ref=ref,
            reason=BreakReason.TIMING_DRIFT,
            detail=f"timestamps span {drift} across sources (threshold {threshold_minutes}m)",
            severity="info",
            sources_present=list(sources.keys()),
            sources_missing=[],
            records=all_records,
        )
    return None
