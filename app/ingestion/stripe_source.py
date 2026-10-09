"""
Ingests transactions from the payment processor. Two modes:

  1. LIVE mode -- if STRIPE_API_KEY is set, calls the real Stripe test-mode
     API (`stripe.Charge.list`). This is what you'd point at your own Stripe
     test account to make the engagement fully real.
  2. FIXTURE mode -- default, no key required. Reads data/stripe_fixture.json,
     which is shaped exactly like Stripe's actual API response. This is what
     lets the whole project run for free with zero external dependencies.

Swapping modes doesn't change anything downstream -- both paths produce the
same NormalizedTransaction objects. That boundary (raw API shape -> normalized
shape) is the part of an integration that's actually worth designing well;
which mode you're in shouldn't leak past this file.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from app.db.models import NormalizedTransaction, SourceName

logger = logging.getLogger(__name__)


def _normalize_charge(charge: dict) -> NormalizedTransaction | None:
    ref = charge.get("metadata", {}).get("ledger_ref")
    if not ref:
        logger.warning("stripe charge %s missing ledger_ref metadata, skipping", charge.get("id"))
        return None

    return NormalizedTransaction(
        txn_ref=ref,
        source=SourceName.STRIPE,
        amount_cents=charge["amount"],
        currency=charge["currency"].upper(),
        ts=datetime.fromtimestamp(charge["created"], tz=timezone.utc),
        status=charge["status"],
        raw=charge,
    )


def load_from_fixture(path: str | Path) -> list[NormalizedTransaction]:
    with open(path) as f:
        payload = json.load(f)
    charges = payload.get("data", [])
    out = [t for c in charges if (t := _normalize_charge(c)) is not None]
    logger.info("stripe_source (fixture): %d charges -> %d normalized", len(charges), len(out))
    return out


def load_from_live_api(limit: int = 500) -> list[NormalizedTransaction]:
    import stripe  # imported lazily -- not a hard dependency in fixture mode

    stripe.api_key = os.environ["STRIPE_API_KEY"]
    charges = stripe.Charge.list(limit=limit)
    out = [t for c in charges.auto_paging_iter() if (t := _normalize_charge(c)) is not None]
    logger.info("stripe_source (live): %d normalized", len(out))
    return out


def load_stripe_transactions(fixture_path: str | Path = "data/stripe_fixture.json") -> list[NormalizedTransaction]:
    if os.environ.get("STRIPE_API_KEY"):
        return load_from_live_api()
    logger.info("STRIPE_API_KEY not set -- using fixture data at %s", fixture_path)
    return load_from_fixture(fixture_path)
