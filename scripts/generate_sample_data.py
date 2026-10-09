"""
Generates synthetic data for all three sources, sharing a txn_ref across them
so the reconciliation engine has something real to chew on. Messiness is
injected ON PURPOSE and documented below — this is standing in for what an
actual legacy-system integration looks like.

Run:
    python scripts/generate_sample_data.py
"""
import csv
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

random.seed(7)  # deterministic output, easier to write tests against

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
N_TRANSACTIONS = 250
NOW = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc)

CURRENCIES = ["USD", "usd", "USD", "USD"]  # occasional lowercase, on purpose
COUNTRIES = ["US", "US", "US", "GB", "US", "NG"]  # NG used for a fraud-rule test case


def txn_ref(i: int) -> str:
    return f"TXN-{i:05d}"


def make_transactions():
    txns = []
    for i in range(1, N_TRANSACTIONS + 1):
        ts = NOW - timedelta(hours=random.randint(0, 96), minutes=random.randint(0, 59))
        amount_cents = random.choice([1999, 4500, 12000, 7599, 2500, 999999, 15000])
        currency = random.choice(CURRENCIES)
        country = random.choice(COUNTRIES)
        txns.append({
            "ref": txn_ref(i),
            "amount_cents": amount_cents,
            "currency": currency,
            "ts": ts,
            "country": country,
        })
    return txns


def write_legacy_ledger_csv(txns):
    """
    Simulates the nightly batch export Priya warned about:
    - amounts as dollar STRINGS, not cents ("45.00" not 4500)
    - inconsistent date formats across rows (two formats mixed, like a
      system that changed locale settings at some point)
    - a handful of duplicate rows (the export job double-writes sometimes)
    - transactions from the last ~18h are simply ABSENT (nightly batch cutoff
      -- this is expected settlement lag, not a break)
    - ~4% of rows missing the reference entirely (should be flagged as
      unmatchable, not silently dropped)
    """
    path = DATA_DIR / "legacy_ledger_sample.csv"
    rows = []
    for t in txns:
        if t["ts"] > NOW - timedelta(hours=18):
            continue  # not in last night's batch yet -- expected lag

        ref = t["ref"]
        if random.random() < 0.04:
            ref = ""  # occasionally the export drops the reference

        date_fmt = "%Y-%m-%d %H:%M:%S" if random.random() < 0.7 else "%m/%d/%Y %I:%M %p"
        rows.append({
            "reference": ref,
            "amount_usd": f"{t['amount_cents'] / 100:.2f}",
            "posted_at": t["ts"].strftime(date_fmt),
            "acct": "MERIDIAN-OPS-01",
        })
        if random.random() < 0.03:
            rows.append(dict(rows[-1]))  # duplicate row, export bug

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["reference", "amount_usd", "posted_at", "acct"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {path}")


def write_stripe_fixture(txns):
    """
    Simulates a Stripe-shaped charges list (test-mode). Amounts already in
    cents (Stripe's real convention). ~6% of charges have an amount that's a
    few cents off from what the ledger will show (rounding / fee handling
    disagreement between systems -- a very real class of recon break).
    5% are still "pending", not yet "succeeded" (in-flight, not a break).
    """
    charges = []
    for t in txns:
        amount = t["amount_cents"]
        if random.random() < 0.06:
            amount += random.choice([-3, -1, 1, 2])  # rounding mismatch, injected

        status = "succeeded"
        if t["ts"] > NOW - timedelta(hours=2):
            status = random.choice(["succeeded", "pending"])

        charges.append({
            "id": f"ch_{t['ref'].lower().replace('-', '')}",
            "amount": amount,
            "currency": t["currency"].lower(),
            "created": int(t["ts"].timestamp()),
            "status": status,
            "metadata": {"ledger_ref": t["ref"]},
            "billing_details": {"address": {"country": t["country"]}},
        })

    path = DATA_DIR / "stripe_fixture.json"
    with open(path, "w") as f:
        json.dump({"object": "list", "data": charges}, f, indent=2)
    print(f"wrote {len(charges)} charges -> {path}")


def write_live_stream_events(txns):
    """
    Simulates the raw event feed Dana mentioned ("streams somewhere for the
    fraud team that never shipped"). This is the freshest, most complete
    source -- includes everything, even the very latest transactions the
    other two sources haven't caught up to yet. Also where we inject one
    obvious velocity-based fraud pattern (same-second burst of charges) for
    the week-2 fraud rules to catch.
    """
    events = []
    for t in txns:
        events.append({
            "event_id": f"evt_{t['ref']}",
            "txn_ref": t["ref"],
            "amount_cents": t["amount_cents"],
            "currency": t["currency"].upper(),
            "occurred_at": t["ts"].isoformat(),
            "country": t["country"],
            "status": "posted",
        })

    # inject a velocity-fraud pattern: 6 charges, same card/country, 40s apart
    burst_start = NOW - timedelta(minutes=10)
    for j in range(6):
        events.append({
            "event_id": f"evt_BURST-{j}",
            "txn_ref": f"TXN-BURST-{j:02d}",
            "amount_cents": 49999,
            "currency": "USD",
            "occurred_at": (burst_start + timedelta(seconds=40 * j)).isoformat(),
            "country": "NG",
            "status": "posted",
        })

    path = DATA_DIR / "live_stream_events.jsonl"
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    print(f"wrote {len(events)} events -> {path}")


if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    txns = make_transactions()
    write_legacy_ledger_csv(txns)
    write_stripe_fixture(txns)
    write_live_stream_events(txns)
