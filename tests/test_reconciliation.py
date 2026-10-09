from datetime import datetime, timedelta, timezone

from app.db.models import NormalizedTransaction, SourceName
from app.reconciliation.engine import reconcile

NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)


def _txn(ref, source, amount_cents, hours_ago=1, currency="USD", status="posted"):
    return NormalizedTransaction(
        txn_ref=ref,
        source=source,
        amount_cents=amount_cents,
        currency=currency,
        ts=NOW - timedelta(hours=hours_ago),
        status=status,
        raw={},
    )


def test_clean_match_across_all_three_sources():
    legacy = [_txn("TXN-1", SourceName.LEGACY_LEDGER, 5000, hours_ago=25)]
    stripe = [_txn("TXN-1", SourceName.STRIPE, 5000, hours_ago=25)]
    live = [_txn("TXN-1", SourceName.LIVE_STREAM, 5000, hours_ago=25)]

    report = reconcile(legacy, stripe, live, now=NOW)

    assert report.clean_count == 1
    assert len(report.breaks) == 0


def test_recent_transaction_not_yet_in_ledger_is_not_a_break():
    # within legacy ledger's settlement window -- should NOT be flagged
    stripe = [_txn("TXN-2", SourceName.STRIPE, 3000, hours_ago=1)]
    live = [_txn("TXN-2", SourceName.LIVE_STREAM, 3000, hours_ago=1)]

    report = reconcile([], stripe, live, now=NOW)

    assert report.clean_count == 1
    assert len(report.breaks) == 0


def test_old_transaction_missing_from_ledger_is_flagged():
    # past the settlement window -- SHOULD be flagged
    stripe = [_txn("TXN-3", SourceName.STRIPE, 3000, hours_ago=30)]
    live = [_txn("TXN-3", SourceName.LIVE_STREAM, 3000, hours_ago=30)]

    report = reconcile([], stripe, live, now=NOW)

    assert len(report.breaks) == 1
    assert report.breaks[0].reason.value == "missing_in_ledger"


def test_amount_mismatch_detected():
    legacy = [_txn("TXN-4", SourceName.LEGACY_LEDGER, 5000, hours_ago=25)]
    stripe = [_txn("TXN-4", SourceName.STRIPE, 5003, hours_ago=25)]
    live = [_txn("TXN-4", SourceName.LIVE_STREAM, 5000, hours_ago=25)]

    report = reconcile(legacy, stripe, live, now=NOW)

    assert len(report.breaks) == 1
    assert report.breaks[0].reason.value == "amount_mismatch"


def test_large_amount_mismatch_is_critical_small_is_warning():
    legacy = [_txn("TXN-5", SourceName.LEGACY_LEDGER, 5000, hours_ago=25)]
    stripe_small_diff = [_txn("TXN-5", SourceName.STRIPE, 5002, hours_ago=25)]
    live = [_txn("TXN-5", SourceName.LIVE_STREAM, 5000, hours_ago=25)]

    report = reconcile(legacy, stripe_small_diff, live, now=NOW)
    assert report.breaks[0].severity == "warning"

    legacy2 = [_txn("TXN-6", SourceName.LEGACY_LEDGER, 5000, hours_ago=25)]
    stripe_big_diff = [_txn("TXN-6", SourceName.STRIPE, 15000, hours_ago=25)]
    live2 = [_txn("TXN-6", SourceName.LIVE_STREAM, 5000, hours_ago=25)]

    report2 = reconcile(legacy2, stripe_big_diff, live2, now=NOW)
    assert report2.breaks[0].severity == "critical"


def test_duplicate_within_source_flagged():
    legacy = [
        _txn("TXN-7", SourceName.LEGACY_LEDGER, 5000, hours_ago=25),
        _txn("TXN-7", SourceName.LEGACY_LEDGER, 5000, hours_ago=25),
    ]
    stripe = [_txn("TXN-7", SourceName.STRIPE, 5000, hours_ago=25)]
    live = [_txn("TXN-7", SourceName.LIVE_STREAM, 5000, hours_ago=25)]

    report = reconcile(legacy, stripe, live, now=NOW)

    reasons = {b.reason.value for b in report.breaks}
    assert "duplicate_in_source" in reasons
