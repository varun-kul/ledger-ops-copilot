# LedgerOps Copilot

A simulated Forward Deployed Engineer engagement: Meridian Pay (fictional
mid-size payments/neobank customer) has three mismatched transaction sources
and an ops team drowning in manual reconciliation. This repo is the
engagement, built week by week, feedback cycles included.

See [`docs/discovery-notes.md`](docs/discovery-notes.md) for the framing —
deliberately ambiguous/contradictory requirements, the way a real discovery
call actually is.

## Week 1 — messy ingestion + reconciliation engine

**The three sources, each with real-world quirks injected on purpose:**

| Source | Format | Quirks |
|---|---|---|
| Legacy ledger | Nightly-batch CSV | dollar strings not cents, mixed date formats, duplicate rows, occasional missing reference, ~20h settlement lag |
| Payment processor | Stripe test-mode API (fixture by default) | cents, occasional rounding mismatch, `pending` vs `succeeded` status |
| Live transaction feed | JSONL / websocket | freshest & most complete, includes a deliberate fraud-pattern burst for week 2 |

**Design decision worth noting:** a naive diff across sources would flag
every transaction from the last ~18 hours as "missing" from the ledger,
because the batch export simply hasn't run yet. The reconciliation engine
uses a per-source **settlement window** instead of a bare set difference —
see the comment at the top of `app/reconciliation/engine.py`.

### Run it

```bash
pip install -r requirements.txt

# 1. generate the synthetic messy data (deterministic, seeded)
python scripts/generate_sample_data.py

# 2. run the full ingestion + reconciliation pipeline
python scripts/run_reconciliation.py

# 3. run the tests
pytest tests/ -v
```

Output: a console summary plus `data/reconciliation_report.json` with every
break, its reason, severity, and the underlying records — built so every
flag is explainable to an auditor (Marcus's requirement on the discovery
call), not a black box.

### Using a real Stripe test account instead of the fixture

Set `STRIPE_API_KEY` (a Stripe **test-mode** secret key) and
`app/ingestion/stripe_source.py` will call the live API instead of reading
`data/stripe_fixture.json`. Nothing else changes — same normalized shape
downstream. `pip install stripe` first (not in requirements.txt by default,
kept optional so the project runs free with zero external accounts).

## Week 2 — fraud rules + free-tier RAG copilot

**Fraud detection** (`app/fraud/rules.py`) — three explainable, rule-based
checks over the live transaction stream (no trained model, per Marcus's
"no black box" requirement on the discovery call):

| Rule | What it catches |
|---|---|
| velocity | too many transactions from the same country within 5 minutes |
| amount_outlier | amounts more than 3 standard deviations from the batch mean |
| geo_mismatch | transactions from outside Meridian Pay's expected countries |

Run: `python scripts/run_fraud_detection.py` → writes `data/fraud_flags.json`.
On the sample data this correctly catches the planted fraud burst (velocity,
critical) and also surfaces a real, honestly-reported ~18% false-positive
rate on `geo_mismatch` — worth tightening in a future feedback cycle rather
than hidden.

**RAG copilot** (`app/copilot/`) — lets a non-technical ops person ask plain
English questions over reconciliation breaks and fraud flags:
- `index.py` — TF-IDF retrieval over short text summaries of every break/flag.
  No embedding model needed; deliberately zero-dependency for this dataset
  size. (Watch out: sklearn's built-in `stop_words="english"` filters out
  "amount" — a real bug we hit and fixed, see the comment in `index.py`.)
- `llm_client.py` — Ollama (free, local, `ollama pull llama3.1`) if
  available, auto-falling back to a no-LLM mode that shows raw retrieved
  context if not — so the whole pipeline is testable with zero setup.
- `query.py` — grounds every answer strictly in retrieved context and
  returns sources alongside the answer, never a bare text blob.

Run: `python scripts/run_copilot.py "which transactions had amount mismatches?"`
(or with no argument, for an interactive loop). Requires
`reconciliation_report.json` and `fraud_flags.json` to already exist.

## What's next

- **Week 3** — ops dashboard + Slack alerts, first simulated customer
  feedback cycle.
- **Week 4** — deployment, second feedback cycle, case study writeup.

## Project layout

```
app/
  db/models.py            normalized schema every source maps into
  ingestion/
    legacy_csv.py          CSV source, format-quirk handling
    stripe_source.py        Stripe fixture/live source
    live_stream.py          JSONL + websocket replay source
  reconciliation/
    engine.py               core matching + break detection
  fraud/
    rules.py                 explainable fraud detection rules
  copilot/
    index.py                 TF-IDF retrieval over breaks + flags
    llm_client.py            Ollama client + free fallback
    query.py                 grounded ask() with source citations
docs/
  discovery-notes.md        the fictional customer engagement framing
scripts/
  generate_sample_data.py   deterministic synthetic data generator
  run_reconciliation.py     end-to-end reconciliation pipeline
  run_fraud_detection.py    end-to-end fraud detection pipeline
  run_copilot.py            interactive/one-shot copilot CLI
tests/
  test_reconciliation.py
  test_fraud_rules.py
  test_copilot_retrieval.py
```