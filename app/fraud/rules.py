"""
Rule-based fraud/anomaly flagging on the live transaction stream.

Deliberately NOT a trained ML model. Marcus's requirement from the discovery
call was explicit: "I need to be able to explain any flag to an auditor. No
black box." A rule with a plain-English explanation satisfies that; a model
score does not, however accurate it is. This is a real trade-off worth
naming out loud: these rules will have a higher false-positive rate than a
tuned model would, but every flag is defensible in one sentence.

Three rules, each independent and composable:
  - velocity: too many transactions from the same "actor" in too short a window
  - amount_outlier: a transaction far outside the normal amount range
  - geo_mismatch: a transaction from a country outside the customer's normal set

geo_mismatch's expected-countries list is loaded from a per-customer config
file (app/fraud/config.py) rather than hardcoded -- see docs/feedback-log.md
cycle 2 for why: a static allow-list breaks every time the customer opens a
new market.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import mean, pstdev

from app.db.models import FraudFlag, FraudRuleName, NormalizedTransaction
from app.fraud.config import load_expected_countries

# --- tunable thresholds, kept as named constants so they're easy to defend
# and adjust in a customer conversation, not buried as magic numbers ---
VELOCITY_WINDOW = timedelta(minutes=5)
VELOCITY_MAX_COUNT = 4          # more than this many txns in the window -> flag
AMOUNT_OUTLIER_STDDEV_MULTIPLIER = 3.0


def detect_velocity(transactions: list[NormalizedTransaction]) -> list[FraudFlag]:
    """
    Flags bursts of transactions from the same country within a short window.
    (Standing in for "same card" / "same account" -- country is the closest
    grouping key available in this dataset; a real system would group by
    account or payment instrument.)
    """
    by_country: dict[str, list[NormalizedTransaction]] = defaultdict(list)
    for t in transactions:
        country = t.raw.get("country", "UNKNOWN")
        by_country[country].append(t)

    flags = []
    for country, txns in by_country.items():
        txns = sorted(txns, key=lambda t: t.ts)
        window: list[NormalizedTransaction] = []
        for t in txns:
            window = [w for w in window if t.ts - w.ts <= VELOCITY_WINDOW] + [t]
            if len(window) > VELOCITY_MAX_COUNT:
                flags.append(FraudFlag(
                    txn_refs=[w.txn_ref for w in window],
                    rule=FraudRuleName.VELOCITY,
                    explanation=(
                        f"{len(window)} transactions from {country} within "
                        f"{VELOCITY_WINDOW.total_seconds() / 60:.0f} minutes "
                        f"(threshold: {VELOCITY_MAX_COUNT})"
                    ),
                    severity="critical",
                    evidence={"country": country, "count": len(window),
                              "window_minutes": VELOCITY_WINDOW.total_seconds() / 60},
                ))
                window = []
    return flags


def detect_amount_outliers(transactions: list[NormalizedTransaction]) -> list[FraudFlag]:
    """
    Flags transactions whose amount is more than N standard deviations from
    the mean of the batch. Simple, explainable, and good enough to catch the
    obviously-wrong-looking amounts without needing labeled training data.
    """
    amounts = [t.amount_cents for t in transactions]
    if len(amounts) < 10:
        return []

    mu, sigma = mean(amounts), pstdev(amounts)
    if sigma == 0:
        return []

    flags = []
    for t in transactions:
        z = (t.amount_cents - mu) / sigma
        if abs(z) > AMOUNT_OUTLIER_STDDEV_MULTIPLIER:
            flags.append(FraudFlag(
                txn_refs=[t.txn_ref],
                rule=FraudRuleName.AMOUNT_OUTLIER,
                explanation=(
                    f"{t.txn_ref} amount ${t.amount_cents / 100:.2f} is "
                    f"{abs(z):.1f} standard deviations from the batch mean "
                    f"(${mu / 100:.2f})"
                ),
                severity="warning" if abs(z) < AMOUNT_OUTLIER_STDDEV_MULTIPLIER * 1.5 else "critical",
                evidence={"amount_cents": t.amount_cents, "mean_cents": round(mu),
                          "stddev": round(sigma, 2), "z_score": round(z, 2)},
            ))
    return flags


def detect_geo_mismatch(transactions: list[NormalizedTransaction],
                          expected_countries: set[str] | None = None) -> list[FraudFlag]:
    """
    Flags transactions from a country outside the customer's expected set.

    expected_countries defaults to the per-customer config
    (app/fraud/config.py) if not passed explicitly -- pass it explicitly in
    tests to avoid depending on the config file's current contents.
    """
    expected = expected_countries if expected_countries is not None else load_expected_countries()
    flags = []
    for t in transactions:
        country = t.raw.get("country")
        if country and country not in expected:
            flags.append(FraudFlag(
                txn_refs=[t.txn_ref],
                rule=FraudRuleName.GEO_MISMATCH,
                explanation=(
                    f"{t.txn_ref} originated from {country}, outside the "
                    f"expected countries {sorted(expected)}"
                ),
                severity="warning",
                evidence={"country": country, "expected": sorted(expected)},
            ))
    return flags


def detect_fraud(transactions: list[NormalizedTransaction],
                   expected_countries: set[str] | None = None) -> list[FraudFlag]:
    """Runs all rules and returns the combined, unranked flag list."""
    return [
        *detect_velocity(transactions),
        *detect_amount_outliers(transactions),
        *detect_geo_mismatch(transactions, expected_countries),
    ]