from app.alerts.escalation import select_alertworthy_breaks, select_alertworthy_flags
from app.alerts.slack import build_alert_message
from app.db.models import BreakReason, FraudFlag, FraudRuleName, ReconciliationBreak, SourceName


def _break(ref, reason, severity):
    return ReconciliationBreak(
        txn_ref=ref, reason=reason, detail="detail", severity=severity,
        sources_present=[SourceName.STRIPE], sources_missing=[], records=[],
    )


def _flag(refs, rule, severity):
    return FraudFlag(txn_refs=refs, rule=rule, explanation="explanation", severity=severity)


def test_only_critical_breaks_are_alertworthy():
    breaks = [
        _break("TXN-1", BreakReason.AMOUNT_MISMATCH, "critical"),
        _break("TXN-2", BreakReason.AMOUNT_MISMATCH, "warning"),
        _break("TXN-3", BreakReason.TIMING_DRIFT, "info"),
    ]
    result = select_alertworthy_breaks(breaks)
    assert [b.txn_ref for b in result] == ["TXN-1"]


def test_velocity_and_amount_outlier_always_alert():
    flags = [
        _flag(["TXN-1"], FraudRuleName.VELOCITY, "critical"),
        _flag(["TXN-2"], FraudRuleName.AMOUNT_OUTLIER, "warning"),
    ]
    result = select_alertworthy_flags(flags)
    assert len(result) == 2


def test_lone_geo_mismatch_is_suppressed():
    flags = [_flag(["TXN-1"], FraudRuleName.GEO_MISMATCH, "warning")]
    result = select_alertworthy_flags(flags)
    assert result == []


def test_geo_mismatch_alerts_when_transaction_also_flagged_by_another_rule():
    flags = [
        _flag(["TXN-1"], FraudRuleName.VELOCITY, "critical"),
        _flag(["TXN-1"], FraudRuleName.GEO_MISMATCH, "warning"),
        _flag(["TXN-2"], FraudRuleName.GEO_MISMATCH, "warning"),  # lone -- stays suppressed
    ]
    result = select_alertworthy_flags(flags)
    refs = {r for f in result for r in f.txn_refs}
    assert "TXN-1" in refs
    assert "TXN-2" not in refs


def test_build_alert_message_returns_none_when_nothing_alertworthy():
    assert build_alert_message([], []) is None


def test_build_alert_message_includes_counts_and_content():
    breaks = [_break("TXN-1", BreakReason.AMOUNT_MISMATCH, "critical")]
    flags = [_flag(["TXN-2"], FraudRuleName.VELOCITY, "critical")]
    message = build_alert_message(breaks, flags)
    assert "1 break" in message
    assert "1 fraud flag" in message
    assert "TXN-1" in message
    assert "TXN-2" in message