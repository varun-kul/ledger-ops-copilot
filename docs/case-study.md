# Case Study: LedgerOps Copilot

**A simulated Forward Deployed Engineer engagement, built end-to-end over
four weeks.** This document is the walkthrough — what the ask was, what got
built and why, what changed based on feedback, and what I'd tell a hiring
manager if they asked "walk me through a project."

---

## The setup

Meridian Pay (fictional mid-size payments processor) has an ops team
manually reconciling transactions across three mismatched systems every
morning — a process that takes hours and still misses things (one break
sat unnoticed for 9 days and cost $40k, per the framing in the discovery
notes). Compliance separately needs fraud flagging they've promised
auditors "is coming," and whatever gets built has to be explainable, not
a black box.

The requirements from the first call were genuinely ambiguous and partly
contradictory — Ops didn't think they needed fraud detection, Compliance
was adamant they did. Rather than block on a follow-up call, I documented a
working interpretation and proceeded, revising it explicitly as real
feedback came in. (Full framing: `docs/discovery-notes.md`.)

## What got built, and the reasoning behind each piece

**Week 1 — ingestion + reconciliation.** Three sources, each with realistic
messiness injected on purpose: a legacy CSV with dollar-string amounts and
mixed date formats, a Stripe-shaped API (fixture by default, swappable to
live), and a raw live transaction stream. All three normalize into one
shared schema before anything else happens — that boundary is the part of
an integration actually worth designing well.

The one real design decision worth defending here: a naive diff across
sources would flag every transaction from the last ~18 hours as "missing,"
because the nightly batch export simply hasn't run yet. Reconciliation uses
a **per-source settlement window** instead of a bare set difference —
getting this wrong means paging someone at 2am for nothing, which is how
alert systems lose trust.

**Week 2 — fraud rules + RAG copilot.** Fraud detection is rule-based, not
a trained model — a deliberate trade-off. A rule has a plain-English
explanation an auditor can be shown; a model score doesn't, however
accurate it is. The copilot is TF-IDF retrieval (not embeddings — the
dataset is a few hundred short structured records, and TF-IDF needs no
model, no download, runs in milliseconds) plus a swappable LLM backend
(Ollama first for zero-data-leaves-the-machine, falling back to Gemini or
NVIDIA NIM free tiers, falling back further to a no-LLM mode that still
shows retrieved context). Every copilot answer is grounded strictly in
retrieved context and returns its sources, never a bare unsourced answer.

**Week 3 — dashboard, Slack alerts, first feedback cycle.** A FastAPI
backend plus a single-file dashboard turn the week 1/2 scripts into
something an ops team could actually look at. The first real feedback
cycle: "the Slack channel got muted" — geo-mismatch fraud flags were
technically correct but too noisy to act on, so they stopped paging Slack
unless reinforced by another signal, while staying fully in the audit
record. **87.5% noise reduction, zero loss of audit completeness.**

**Week 4 — deployment, second feedback cycle, this document.** Two more
pieces of feedback landed: the customer opened a new office (Lagos), which
would have kept re-triggering the same complaint under the cycle 1 fix
alone — so the fix moved one layer deeper, from filtering alerts to fixing
the actual config the rule reads from. And Compliance's original ask
finally got its concrete artifact: a chronological CSV audit export.

## The two feedback cycles, side by side

This is the part I'd actually walk through in an interview — not the code,
the *judgment calls*:

| | Cycle 1 (week 3) | Cycle 2 (week 4) |
|---|---|---|
| Complaint | Alert fatigue on geo-mismatch | New office triggers same complaint again |
| Where the fix landed | Alert-selection layer (`app/alerts/escalation.py`) | Root config (`app/fraud/config.py`) |
| What it actually fixed | Which flags interrupt a human | Which flags get generated at all |
| Audit record impact | None — everything still logged | None — everything still logged |
| Measured result | 48 → 6 flags paging Slack (87.5% reduction) | 48 → 1 flag generated in the first place |

Cycle 1 was the right fix *at the time*, given what was known. Cycle 2 isn't
"cycle 1 was wrong" — it's what a second round of real feedback reveals
that the first fix didn't anticipate. Both are true statements about doing
this work honestly: you fix what you can see, and you stay open to a better
fix one layer down when it becomes visible. That arc — not any individual
line of code — is the actual FDE skill this project was built to
demonstrate.

## Things I'd flag as open, not resolved

Being upfront about these is itself the point — a real engagement never
comes to a clean stop, and pretending otherwise would undercut the rest of
this document:

- The config-file approach to `expected_countries` still requires a human to
  notice and update it. A better long-term design would detect a country's
  transaction volume trend and *suggest* a config update rather than
  requiring someone to remember. Noted in `docs/feedback-log.md` cycle 2,
  not built — deciding what NOT to build in a given cycle is part of the job.
- `amount_outlier`'s z-score threshold (3 standard deviations) hasn't been
  through a feedback cycle yet. It might have the same "too noisy" problem
  geo-mismatch had; there just hasn't been a simulated complaint about it.
- The dashboard's TF-IDF retrieval has a known noise mode: near-duplicate
  documents (e.g. several `missing_in_ledger` breaks with nearly identical
  wording) can crowd out a more specific match on shared vocabulary. Caught
  during manual testing in week 2, not yet fixed — flagged rather than
  silently left in.
- Deployment here is a single Docker container with baked-in demo data
  (`Dockerfile`, `docker-compose.yml`). A real production version would
  replace the build-time data generation with a scheduled job (cron /
  GitHub Actions / whatever the customer already runs) writing to a shared
  volume, plus real monitoring beyond the basic `/api/health` check.

## What this project is meant to demonstrate

Not "I can build a fraud detector" — the rules here are intentionally
simple. The actual claims:

1. **Comfort with ambiguity** — the discovery notes are deliberately
   unresolved and contradictory, and the response was to document an
   interpretation and proceed, not to block.
2. **Integration judgment** — the settlement-window design in week 1 is the
   difference between a system ops trusts and one they mute.
3. **Explainability as a first-class constraint** — rule-based fraud
   detection, grounded RAG answers, and a full audit export all trace back
   to the same requirement stated on the first call.
4. **Real iteration, not staged iteration** — two feedback cycles that
   actually changed the architecture, with before/after numbers measured
   against the same dataset both times, and an honest account of why cycle
   2 wasn't just "cycle 1 but bigger."