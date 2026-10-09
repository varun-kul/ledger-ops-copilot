"""
Ingests the legacy nightly-batch ledger CSV. This is the messiest source by
design (see scripts/generate_sample_data.py for what's injected):
  - amounts as dollar strings, not cents
  - two different date formats mixed in the same file
  - occasional duplicate rows
  - occasional missing reference

Every quirk handled here is logged, not silently swallowed -- an FDE
integration that silently drops bad rows is the kind of thing that causes a
$40k break to sit unnoticed for 9 days (see docs/discovery-notes.md).
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from app.db.models import NormalizedTransaction, SourceName

logger = logging.getLogger(__name__)

DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%m/%d/%Y %I:%M %p"]


def _parse_date(raw: str) -> datetime | None:
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    return None


def load_legacy_ledger(path: str | Path) -> tuple[list[NormalizedTransaction], list[dict]]:
    """
    Returns (normalized_transactions, skipped_rows_with_reason).
    Skipped rows are NOT dropped silently -- they're returned so the caller
    can surface them (this matters for Marcus's "no black box" requirement:
    every row must be accounted for, matched or explicitly flagged as
    unparseable).
    """
    from datetime import timezone

    normalized: list[NormalizedTransaction] = []
    skipped: list[dict] = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            ref = (row.get("reference") or "").strip()
            if not ref:
                skipped.append({"row": i, "reason": "missing_reference", "raw": row})
                continue

            try:
                amount_cents = round(float(row["amount_usd"]) * 100)
            except (ValueError, KeyError):
                skipped.append({"row": i, "reason": "unparseable_amount", "raw": row})
                continue

            ts = _parse_date(row.get("posted_at", ""))
            if ts is None:
                skipped.append({"row": i, "reason": "unparseable_date", "raw": row})
                continue

            normalized.append(NormalizedTransaction(
                txn_ref=ref,
                source=SourceName.LEGACY_LEDGER,
                amount_cents=amount_cents,
                currency="USD",  # legacy system is USD-only, no field for it
                ts=ts.replace(tzinfo=timezone.utc),
                status="posted",
                raw=row,
            ))

    dupes = _flag_duplicates(normalized, skipped)
    logger.info(
        "legacy_csv: %d normalized, %d skipped, %d duplicate rows",
        len(normalized), len(skipped), dupes,
    )
    return normalized, skipped


def _flag_duplicates(records: list[NormalizedTransaction], skipped: list[dict]) -> int:
    """De-dupes exact repeat rows (export bug) but records that it happened --
    a silently de-duped row is still information the customer should be able
    to see, per Marcus's audit requirement."""
    seen = set()
    unique = []
    dupe_count = 0
    for r in records:
        key = (r.txn_ref, r.amount_cents, r.ts)
        if key in seen:
            dupe_count += 1
            skipped.append({"reason": "duplicate_row_deduped", "txn_ref": r.txn_ref})
            continue
        seen.add(key)
        unique.append(r)
    records[:] = unique
    return dupe_count
