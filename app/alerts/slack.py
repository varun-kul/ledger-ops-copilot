"""
Posts formatted alerts to Slack via an Incoming Webhook -- free, no Slack
app/bot needed, just a webhook URL from Slack's app directory
(https://api.slack.com/messaging/webhooks). Set SLACK_WEBHOOK_URL in .env
or your environment.

Without a webhook configured, alerts are printed to stdout instead of
posted -- same "always runnable, never hard-fails on missing config"
pattern as the rest of the project.
"""
from __future__ import annotations

import logging
import os

from app.db.models import FraudFlag, ReconciliationBreak

logger = logging.getLogger(__name__)


def _format_break(b: ReconciliationBreak) -> str:
    emoji = "\U0001F6A8" if b.severity == "critical" else "\u26A0\uFE0F"
    return f"{emoji} *{b.reason.value}* on `{b.txn_ref}` ({b.severity}): {b.detail}"


def _format_flag(f: FraudFlag) -> str:
    emoji = "\U0001F6A8" if f.severity == "critical" else "\u26A0\uFE0F"
    refs = ", ".join(f"`{r}`" for r in f.txn_refs)
    return f"{emoji} *{f.rule.value}* on {refs} ({f.severity}): {f.explanation}"


def build_alert_message(breaks: list[ReconciliationBreak], flags: list[FraudFlag]) -> str | None:
    """Returns None if there's nothing to alert on -- callers should skip
    posting entirely rather than sending an empty/pointless message."""
    if not breaks and not flags:
        return None

    lines = [f"*LedgerOps Copilot -- {len(breaks)} break(s), {len(flags)} fraud flag(s)*"]
    if breaks:
        lines.append("\n*Reconciliation breaks:*")
        lines.extend(_format_break(b) for b in breaks)
    if flags:
        lines.append("\n*Fraud flags:*")
        lines.extend(_format_flag(f) for f in flags)
    return "\n".join(lines)


def post_to_slack(message: str, webhook_url: str | None = None) -> bool:
    """Returns True if actually posted, False if it fell back to stdout
    (no webhook configured) or the post failed."""
    webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set -- printing alert instead of posting")
        print("\n=== [Slack alert -- not posted, no webhook configured] ===")
        print(message)
        print("=" * 60)
        return False

    import requests

    try:
        response = requests.post(webhook_url, json={"text": message}, timeout=10)
        response.raise_for_status()
        logger.info("posted alert to Slack")
        return True
    except requests.exceptions.RequestException as e:
        logger.error("failed to post to Slack: %s", e)
        print("\n=== [Slack post failed -- printing instead] ===")
        print(message)
        print("=" * 60)
        return False