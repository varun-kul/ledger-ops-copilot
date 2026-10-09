# Feedback Log

Simulated customer feedback and the changes made in response, kept as a
running log (see docs/discovery-notes.md for the original framing).

---

## Cycle 1 — "the Slack channel got muted"

**When:** week 3, after the fraud rules and Slack alerts had been running
against sample data for a few (simulated) days.

**The complaint (Dana, Ops):**
> "Half my team has muted #ledgerops-alerts. It's mostly the geo-mismatch
> ones — we get like five NG transactions flagged a day and almost none of
> them turn out to be anything. Nobody's even opening them anymore, which
> means when a REAL one comes through, we might miss it."

**Root cause:** `geo_mismatch` on its own is a weak signal (a static
allow-list of countries), and on the sample dataset it had roughly an 18%
false-positive rate. Every one of those was still a real, correctly-typed
event — the problem isn't the rule being *wrong*, it's the rule being *too
noisy to act on alone*. Classic alert-fatigue: a technically correct alert
that trains people to stop looking.

**The fix:** `app/alerts/escalation.py` — `geo_mismatch` flags now only page
Slack when the same transaction is *also* flagged by another rule (velocity
or amount_outlier). A geo-mismatch on its own is still logged in
`fraud_flags.json`; it's just not an interruption anymore.

**What did NOT change:** the audit record. Marcus's "explain every flag to
an auditor" requirement doesn't care about Slack noise — it cares about
nothing being silently dropped.

**Measured impact:**

| | Before | After |
|---|---|---|
| Fraud flags in the audit record | 48 | 48 (unchanged) |
| Fraud flags that would page Slack | 48 | 6 |
| Noise reduction | — | 87.5% |

**Open question raised at the time (now resolved in cycle 2):** should
`EXPECTED_COUNTRIES` itself be reviewed, since a static allow-list keeps
generating this exact complaint every time the customer opens a new market?

---

## Cycle 2 — "we opened a Lagos office" + the standing audit-export ask

**When:** week 4.

**Two things landed at once, both worth addressing together:**

**1. Dana, Ops:** "Quick heads up — we opened an office in Lagos last week,
so we're going to have a lot more legitimate NG transactions now. Can you
make sure that doesn't light up the fraud dashboard?"

This is exactly the open question flagged at the end of cycle 1. The cycle 1
fix (escalation-only) was a reasonable stopgap, but it was always going to
keep needing this conversation every time the customer's footprint changed.
The actual fix belongs one layer down: **`EXPECTED_COUNTRIES` moved from a
hardcoded constant in `app/fraud/rules.py` to a per-customer config file**
(`config/meridian_pay.json`, loaded via `app/fraud/config.py`, with a safe
hardcoded fallback if the file is ever missing or malformed). Updating the
customer's expected countries is now a config change, not a code deploy.

**Measured impact — and this one is a bigger deal than cycle 1's fix:**

| | Before cycle 2 | After cycle 2 |
|---|---|---|
| Fraud flags generated in the first place | 48 | 1 |
| Fraud flags that would page Slack | 6 | 1 |

Cycle 1 only reduced what pages a human; the flags themselves were still
being generated and logged. Cycle 2 fixes the actual root cause — NG is no
longer treated as anomalous at all, because it isn't anymore. The one
remaining flag is the planted `velocity` burst, which still fires
correctly and still pages Slack, since velocity doesn't depend on country
at all. Nothing real was lost; this time the noise didn't even get created.

**2. Marcus, Compliance:** his original discovery-call ask ("I need to be
able to explain any flag to an auditor") has been satisfied conversationally
by the copilot and the JSON reports since week 2, but he never actually got
a document he could hand to an external auditor. Built
`scripts/export_audit_trail.py` — a single chronological CSV combining
every reconciliation break and every fraud flag (alert-worthy or not,
same audit-completeness principle as everywhere else in this project),
sorted critical-first, with an explicit `alertworthy` column so an auditor
can see both "what happened" and "what actually got a human's attention."

**What did NOT change:** nothing about severity thresholds or the
escalation logic from cycle 1 — that logic is still in place and still
matters for rules that DO have real ongoing noise (amount_outlier, and
geo_mismatch for any country not yet in the customer's config).

**Open item for a future cycle:** the config file currently has to be
updated manually. If Meridian Pay keeps expanding into new markets
regularly, a better long-term design might detect a country's *transaction
volume trend* (recently-common but not-yet-configured) and suggest a config
update rather than silently flagging it as risky forever. Flagged, not
built — good scope discipline is part of the job too.