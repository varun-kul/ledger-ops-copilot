# LedgerOps Copilot

A simulated Forward Deployed Engineer engagement: Meridian Pay (fictional
mid-size payments/neobank customer) has three mismatched transaction sources
and an ops team drowning in manual reconciliation. Built week by week, two
real feedback cycles included.

**Start here:** [`docs/case-study.md`](docs/case-study.md) — the full
walkthrough of what was built, why, and what changed based on feedback.
[`docs/discovery-notes.md`](docs/discovery-notes.md) has the original
(deliberately ambiguous) engagement framing, and
[`docs/feedback-log.md`](docs/feedback-log.md) has both feedback cycles in
detail with before/after numbers.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # optional -- add GEMINI_API_KEY / NVIDIA_API_KEY / SLACK_WEBHOOK_URL

python scripts/generate_sample_data.py
python scripts/run_reconciliation.py
python scripts/run_fraud_detection.py
python scripts/export_audit_trail.py

pytest tests/ -v

uvicorn app.api.main:app --reload   # then open http://localhost:8000
```

Or with Docker (bakes in demo data at build time):
```bash
docker compose up --build
```

## What's in each week

**Week 1 — ingestion + reconciliation.** Three sources (legacy CSV, Stripe
fixture/live, live stream JSONL), each with realistic messiness injected on
purpose, normalized into one shared schema. Reconciliation uses per-source
**settlement windows** instead of a naive diff, so recently-unsettled
transactions aren't falsely flagged as breaks. See `app/reconciliation/engine.py`.

**Week 2 — fraud rules + free-tier RAG copilot.** Three explainable,
rule-based fraud checks (`app/fraud/rules.py`) — no trained model, so every
flag can be explained to an auditor in one sentence. The copilot
(`app/copilot/`) uses TF-IDF retrieval (no embedding model needed) and a
swappable LLM backend: Ollama (free, local) → Gemini → NVIDIA NIM → a
no-LLM fallback that shows raw retrieved context. Every answer is grounded
strictly in retrieved context and returns its sources.

**Week 3 — dashboard, Slack alerts, first feedback cycle.** FastAPI backend
(`app/api/main.py`) + single-file dashboard (`app/api/static/index.html`,
React via CDN, no build step). Slack alerts (`app/alerts/`) post
alert-worthy items via webhook. First feedback cycle: geo-mismatch alert
noise reduced 87.5% by only paging Slack when a flag is reinforced by
another signal, while keeping the full record for compliance.

**Week 4 — deployment, second feedback cycle, case study.** Dockerized
(`Dockerfile`, `docker-compose.yml`) with a `/api/health` endpoint. Second
feedback cycle went deeper than the first: `EXPECTED_COUNTRIES` moved from
a hardcoded constant to a per-customer config file
(`config/meridian_pay.json`, loaded via `app/fraud/config.py`), so a new
customer market doesn't require a code deploy — this eliminated the noise
at the source rather than just filtering it downstream (48 → 1 flags
generated, not just 48 → 6 that page Slack). Also added
`scripts/export_audit_trail.py`, the compliance-ready CSV export Marcus
asked for on the very first discovery call.

## Environment variables (`.env`, see `.env.example`)

| Variable | Used by | Required? |
|---|---|---|
| `GEMINI_API_KEY` | copilot LLM backend | No — falls back to NVIDIA, then no-LLM mode |
| `NVIDIA_API_KEY` | copilot LLM backend | No — same fallback chain |
| `SLACK_WEBHOOK_URL` | `scripts/send_alerts.py` | No — falls back to printing to stdout |
| `STRIPE_API_KEY` | `app/ingestion/stripe_source.py` | No — falls back to bundled fixture data |

Nothing in this project requires any paid service or account to run fully,
end to end, including the LLM-backed copilot (via Ollama, run locally).

## Project layout

```
app/
  db/models.py              normalized schema every source maps into
  ingestion/
    legacy_csv.py            CSV source, format-quirk handling
    stripe_source.py          Stripe fixture/live source
    live_stream.py            JSONL + websocket replay source
  reconciliation/
    engine.py                 core matching + break detection
  fraud/
    rules.py                   explainable fraud detection rules
    config.py                  per-customer config loader (feedback cycle 2)
  copilot/
    index.py                   TF-IDF retrieval over breaks + flags
    llm_client.py               Ollama / Gemini / NVIDIA / fallback backends
    query.py                    grounded ask() with source citations
  alerts/
    escalation.py                alert-worthy filtering (feedback cycle 1)
    slack.py                     Slack webhook client
  api/
    main.py                      FastAPI backend
    static/index.html            dashboard (React via CDN)
config/
  meridian_pay.json          per-customer settings (feedback cycle 2)
docs/
  discovery-notes.md         the fictional customer engagement framing
  feedback-log.md            both feedback cycles, before/after numbers
  case-study.md               full engagement walkthrough -- start here
scripts/
  generate_sample_data.py    deterministic synthetic data generator
  run_reconciliation.py      end-to-end reconciliation pipeline
  run_fraud_detection.py     end-to-end fraud detection pipeline
  run_copilot.py             interactive/one-shot copilot CLI
  send_alerts.py             posts alert-worthy items to Slack
  export_audit_trail.py       compliance-ready CSV export (feedback cycle 2)
tests/
  test_reconciliation.py
  test_fraud_rules.py
  test_fraud_config.py
  test_copilot_retrieval.py
  test_llm_client.py
  test_alerts.py
  test_api.py
  test_export_audit_trail.py
  test_run_copilot_resilience.py
Dockerfile
docker-compose.yml
```