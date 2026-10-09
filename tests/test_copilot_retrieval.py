"""
Tests retrieval only, not generation -- generation depends on whether Ollama
is installed, which we can't assume in CI or on a fresh machine. Retrieval
correctness is what actually matters to test: if the wrong documents get
retrieved, a perfect LLM still produces a wrong answer.
"""
import json

from app.copilot.index import Document, DocumentIndex, build_documents


def test_search_returns_relevant_document_first(tmp_path):
    recon = {"breaks": [
        {"txn_ref": "TXN-1", "reason": "amount_mismatch", "severity": "critical",
         "detail": "amounts differ", "sources_present": ["stripe", "legacy_ledger"],
         "sources_missing": []},
        {"txn_ref": "TXN-2", "reason": "missing_in_ledger", "severity": "warning",
         "detail": "not yet settled", "sources_present": ["stripe"],
         "sources_missing": ["legacy_ledger"]},
    ]}
    fraud = {"flags": []}

    recon_path = tmp_path / "recon.json"
    fraud_path = tmp_path / "fraud.json"
    recon_path.write_text(json.dumps(recon))
    fraud_path.write_text(json.dumps(fraud))

    docs = build_documents(recon_path, fraud_path)
    index = DocumentIndex(docs)

    results = index.search("amount mismatch", top_k=1)
    assert len(results) == 1
    assert results[0][0].metadata["txn_ref"] == "TXN-1"


def test_empty_index_returns_no_results():
    index = DocumentIndex([])
    assert index.search("anything") == []


def test_search_respects_top_k():
    docs = [Document(doc_id=f"d{i}", kind="reconciliation_break",
                      text="reconciliation break amount mismatch transaction",
                      metadata={}) for i in range(10)]
    index = DocumentIndex(docs)
    results = index.search("amount mismatch", top_k=3)
    assert len(results) == 3