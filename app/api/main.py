"""
FastAPI backend for the dashboard. Serves reconciliation breaks, fraud
flags, summary stats, and the copilot as JSON endpoints, plus the static
dashboard itself.

Run:
    uvicorn app.api.main:app --reload
Then open http://localhost:8000

Requires the week 1/2 pipeline to have already run at least once
(data/reconciliation_report.json and data/fraud_flags.json must exist) --
this API reads those files, it doesn't regenerate them. Re-run
run_reconciliation.py / run_fraud_detection.py and restart the server to
refresh the data.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.alerts.escalation import select_alertworthy_breaks, select_alertworthy_flags
from app.copilot.index import DocumentIndex, load_index
from app.copilot.query import ask
from app.db.models import BreakReason, FraudFlag, FraudRuleName, ReconciliationBreak, SourceName

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="LedgerOps Copilot API")

_index_cache: DocumentIndex | None = None


def _load_raw(name: str) -> dict:
    path = DATA_DIR / name
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"{name} not found -- run the week 1/2 pipeline scripts first "
                    f"(run_reconciliation.py, run_fraud_detection.py).",
        )
    with open(path) as f:
        return json.load(f)


def _breaks_from_raw(raw: dict) -> list[ReconciliationBreak]:
    return [
        ReconciliationBreak(
            txn_ref=b["txn_ref"], reason=BreakReason(b["reason"]), detail=b["detail"],
            severity=b["severity"],
            sources_present=[SourceName(s) for s in b["sources_present"]],
            sources_missing=[SourceName(s) for s in b["sources_missing"]],
            records=[],
        )
        for b in raw["breaks"]
    ]


def _flags_from_raw(raw: dict) -> list[FraudFlag]:
    return [
        FraudFlag(txn_refs=f["txn_refs"], rule=FraudRuleName(f["rule"]),
                   explanation=f["explanation"], severity=f["severity"], evidence=f["evidence"])
        for f in raw["flags"]
    ]


@app.get("/api/summary")
def get_summary():
    recon = _load_raw("reconciliation_report.json")
    fraud = _load_raw("fraud_flags.json")
    breaks = _breaks_from_raw(recon)
    flags = _flags_from_raw(fraud)
    return {
        "reconciliation": recon["summary"],
        "fraud": fraud["summary"],
        "alertworthy": {
            "breaks": len(select_alertworthy_breaks(breaks)),
            "flags": len(select_alertworthy_flags(flags)),
            "total_breaks": len(breaks),
            "total_flags": len(flags),
        },
    }


@app.get("/api/breaks")
def get_breaks(severity: str | None = None):
    raw = _load_raw("reconciliation_report.json")
    breaks = raw["breaks"]
    if severity:
        breaks = [b for b in breaks if b["severity"] == severity]
    return {"count": len(breaks), "breaks": breaks}


@app.get("/api/fraud-flags")
def get_fraud_flags(alertworthy_only: bool = False):
    raw = _load_raw("fraud_flags.json")
    flags = _flags_from_raw(raw)
    if alertworthy_only:
        flags = select_alertworthy_flags(flags)
    return {"count": len(flags), "flags": [f.to_dict() for f in flags]}


class CopilotRequest(BaseModel):
    question: str


class CopilotSource(BaseModel):
    doc_id: str
    kind: str


class CopilotResponse(BaseModel):
    answer: str
    sources: list[CopilotSource]


@app.post("/api/copilot/ask", response_model=CopilotResponse)
def copilot_ask(request: CopilotRequest):
    global _index_cache
    if _index_cache is None:
        _load_raw("reconciliation_report.json")  # raises 503 with a clear message if missing
        _load_raw("fraud_flags.json")
        _index_cache = load_index(DATA_DIR / "reconciliation_report.json",
                                    DATA_DIR / "fraud_flags.json")

    result = ask(request.question, _index_cache)
    return CopilotResponse(
        answer=result.answer,
        sources=[CopilotSource(doc_id=d.doc_id, kind=d.kind) for d in result.sources],
    )


@app.get("/")
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    recon_ok = (DATA_DIR / "reconciliation_report.json").exists()
    fraud_ok = (DATA_DIR / "fraud_flags.json").exists()
    return {"status": "ok" if (recon_ok and fraud_ok) else "degraded",
            "data": {"reconciliation_report": recon_ok, "fraud_flags": fraud_ok}}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")