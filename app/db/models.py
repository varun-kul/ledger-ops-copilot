"""
Normalized data models shared across all three ingestion sources and the
reconciliation engine. This is the schema every messy source gets mapped INTO —
the whole point of week 1 is that legacy_csv.py, stripe_source.py, and
live_stream.py each speak their own native format, and normalize() on each
converts to this shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class SourceName(str, Enum):
    LEGACY_LEDGER = "legacy_ledger"
    STRIPE = "stripe"
    LIVE_STREAM = "live_stream"


@dataclass
class NormalizedTransaction:
    """
    Canonical transaction shape. All amounts in integer cents (never floats —
    the legacy CSV stores dollars as strings like "40.00" and that's exactly
    the kind of thing that causes silent off-by-a-cent reconciliation breaks
    if you don't normalize early).
    """
    txn_ref: str                  # cross-system reference key
    source: SourceName
    amount_cents: int
    currency: str                 # normalized to uppercase ISO code, e.g. "USD"
    ts: datetime                  # normalized to UTC
    status: str                   # e.g. "posted", "pending", "settled"
    raw: dict[str, Any] = field(default_factory=dict)  # original record, for audit trail


class BreakReason(str, Enum):
    MISSING_IN_LEDGER = "missing_in_ledger"
    MISSING_IN_STRIPE = "missing_in_stripe"
    MISSING_IN_LIVE_STREAM = "missing_in_live_stream"
    AMOUNT_MISMATCH = "amount_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    DUPLICATE_IN_SOURCE = "duplicate_in_source"
    TIMING_DRIFT = "timing_drift"  # informational, not a hard break


@dataclass
class ReconciliationBreak:
    txn_ref: str
    reason: BreakReason
    detail: str
    severity: str  # "info" | "warning" | "critical"
    sources_present: list[SourceName]
    sources_missing: list[SourceName]
    records: list[NormalizedTransaction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "txn_ref": self.txn_ref,
            "reason": self.reason.value,
            "detail": self.detail,
            "severity": self.severity,
            "sources_present": [s.value for s in self.sources_present],
            "sources_missing": [s.value for s in self.sources_missing],
        }


class FraudRuleName(str, Enum):
    VELOCITY = "velocity"
    AMOUNT_OUTLIER = "amount_outlier"
    GEO_MISMATCH = "geo_mismatch"


@dataclass
class FraudFlag:
    """
    Output of a single fraud rule firing on one or more transactions.
    Deliberately rule-based, not a trained model: Marcus (compliance) needs
    to be able to explain every flag to an auditor in plain terms, so
    `explanation` is written to be read aloud, not just logged.
    """
    txn_refs: list[str]
    rule: FraudRuleName
    explanation: str
    severity: str  # "info" | "warning" | "critical"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "txn_refs": self.txn_refs,
            "rule": self.rule.value,
            "explanation": self.explanation,
            "severity": self.severity,
            "evidence": self.evidence,
        }