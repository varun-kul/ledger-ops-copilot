"""
Ingests the "live transaction feed" Dana mentioned on the discovery call
(see docs/discovery-notes.md). This is the freshest, most complete source --
it has every transaction, including ones the ledger and Stripe haven't
caught up to yet.

Two ways to consume it:
  - `load_live_stream_from_jsonl` -- batch load for the reconciliation script
    (what week 1 uses).
  - `serve_replay` / `consume_stream` -- an actual asyncio websocket
    server+client pair that replays data/live_stream_events.jsonl with small
    delays, simulating a real feed. This is what week 2/3's anomaly service
    will consume from directly instead of batch-loading.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from app.db.models import NormalizedTransaction, SourceName

logger = logging.getLogger(__name__)


def _normalize_event(event: dict) -> NormalizedTransaction:
    return NormalizedTransaction(
        txn_ref=event["txn_ref"],
        source=SourceName.LIVE_STREAM,
        amount_cents=event["amount_cents"],
        currency=event["currency"].upper(),
        ts=datetime.fromisoformat(event["occurred_at"]).astimezone(timezone.utc),
        status=event.get("status", "posted"),
        raw=event,
    )


def load_live_stream_from_jsonl(path: str | Path = "data/live_stream_events.jsonl") -> list[NormalizedTransaction]:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(_normalize_event(json.loads(line)))
    logger.info("live_stream: %d events normalized", len(out))
    return out


# --- optional: real websocket replay, for the near-real-time demo in week 2/3 ---

async def serve_replay(path: str | Path = "data/live_stream_events.jsonl",
                        host: str = "localhost", port: int = 8765,
                        delay_seconds: float = 0.05) -> None:
    """Starts a websocket server that replays events to any connected client.
    Requires the `websockets` package (see requirements.txt)."""
    import websockets

    async def handler(ws):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                await ws.send(line)
                await asyncio.sleep(delay_seconds)
        logger.info("replay finished, closing connection")

    async with websockets.serve(handler, host, port):
        logger.info("live stream replay serving on ws://%s:%d", host, port)
        await asyncio.Future()  # run forever


async def consume_stream(uri: str = "ws://localhost:8765") -> AsyncIterator[NormalizedTransaction]:
    """Async generator a downstream consumer (e.g. the fraud/anomaly service
    in week 2) can iterate over as events arrive."""
    import websockets

    async with websockets.connect(uri) as ws:
        async for message in ws:
            event = json.loads(message)
            yield _normalize_event(event)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve_replay())
