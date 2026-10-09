import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.export_audit_trail import FIELDNAMES, _breaks_rows, _flags_rows


def test_breaks_rows_includes_every_break_regardless_of_alertworthy():
    recon = {"breaks": [
        {"txn_ref": "TXN-1", "reason": "amount_mismatch", "severity": "critical",
         "detail": "d1", "sources_present": ["stripe"], "sources_missing": []},
        {"txn_ref": "TXN-2", "reason": "timing_drift", "severity": "info",
         "detail": "d2", "sources_present": ["stripe", "legacy_ledger"], "sources_missing": []},
    ]}
    rows = _breaks_rows(recon, alertworthy_refs={"TXN-1"})
    assert len(rows) == 2  # both included, not just the alertworthy one
    assert rows[0]["alertworthy"] is True
    assert rows[1]["alertworthy"] is False
    assert set(rows[0].keys()) == set(FIELDNAMES)


def test_flags_rows_marks_alertworthy_by_any_matching_ref():
    fraud = {"flags": [
        {"txn_refs": ["TXN-1", "TXN-2"], "rule": "velocity", "severity": "critical",
         "explanation": "e1", "evidence": {}},
        {"txn_refs": ["TXN-3"], "rule": "geo_mismatch", "severity": "warning",
         "explanation": "e2", "evidence": {}},
    ]}
    rows = _flags_rows(fraud, alertworthy_refs={"TXN-2"})  # only TXN-2 is alertworthy
    assert rows[0]["alertworthy"] is True   # TXN-1's group includes TXN-2
    assert rows[1]["alertworthy"] is False  # TXN-3 alone, not alertworthy