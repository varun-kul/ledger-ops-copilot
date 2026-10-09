from datetime import datetime, timedelta, timezone

from app.db.models import NormalizedTransaction, SourceName
from app.fraud.rules import detect_amount_outliers, detect_geo_mismatch, detect_velocity

NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)


def _txn(ref, amount_cents, minutes_ago=0, country="US"):
    return NormalizedTransaction(
        txn_ref=ref,
        source=SourceName.LIVE_STREAM,
        amount_cents=amount_cents,
        currency="USD",
        ts=NOW - timedelta(minutes=minutes_ago),
        status="posted",
        raw={"country": country},
    )


def test_velocity_flags_burst_within_window():
    txns = [_txn(f"TXN-{i}", 5000, minutes_ago=i * 0.5, country="NG") for i in range(6)]
    flags = detect_velocity(txns)
    assert len(flags) == 1
    assert flags[0].rule.value == "velocity"
    assert flags[0].severity == "critical"


def test_velocity_does_not_flag_spread_out_transactions():
    txns = [_txn(f"TXN-{i}", 5000, minutes_ago=i * 30, country="US") for i in range(6)]
    flags = detect_velocity(txns)
    assert len(flags) == 0


def test_amount_outlier_flags_extreme_value():
    normal = [_txn(f"TXN-{i}", 5000 + i * 10, minutes_ago=i) for i in range(20)]
    outlier = [_txn("TXN-OUTLIER", 999999, minutes_ago=99)]
    flags = detect_amount_outliers(normal + outlier)
    refs_flagged = {r for f in flags for r in f.txn_refs}
    assert "TXN-OUTLIER" in refs_flagged


def test_amount_outlier_needs_minimum_sample_size():
    small_batch = [_txn(f"TXN-{i}", 5000, minutes_ago=i) for i in range(5)]
    flags = detect_amount_outliers(small_batch)
    assert flags == []


def test_geo_mismatch_flags_unexpected_country():
    txns = [_txn("TXN-1", 5000, country="US"), _txn("TXN-2", 5000, country="NG")]
    flags = detect_geo_mismatch(txns)
    assert len(flags) == 1
    assert flags[0].txn_refs == ["TXN-2"]