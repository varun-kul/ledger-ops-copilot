"""
Retrieval layer for the copilot. Turns reconciliation breaks and fraud flags
into short text documents, then retrieves the most relevant ones for a given
question using TF-IDF similarity.

Deliberately NOT using embeddings here, on purpose: TF-IDF needs no model,
no download, no network call, and runs in milliseconds on a dataset this
size. It's the right tool for "search a few hundred short structured
records," and it means retrieval works even before you've set up Ollama.
If this were scaled to millions of documents, embeddings would earn their
keep -- naming that trade-off is itself useful FDE material.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Document:
    doc_id: str
    kind: str          # "reconciliation_break" | "fraud_flag"
    text: str           # human-readable summary, what actually gets embedded/matched
    metadata: dict


def build_documents(reconciliation_report_path: str | Path,
                     fraud_flags_path: str | Path) -> list[Document]:
    documents: list[Document] = []

    with open(reconciliation_report_path) as f:
        recon = json.load(f)
    for b in recon.get("breaks", []):
        reason_readable = b["reason"].replace("_", " ")
        text = (
            f"Reconciliation break for transaction {b['txn_ref']}: {reason_readable} "
            f"(severity: {b['severity']}). {b['detail']}. "
            f"Present in: {', '.join(b['sources_present']) or 'none'}. "
            f"Missing from: {', '.join(b['sources_missing']) or 'none'}."
        )
        documents.append(Document(
            doc_id=f"break::{b['txn_ref']}::{b['reason']}",
            kind="reconciliation_break",
            text=text,
            metadata=b,
        ))

    with open(fraud_flags_path) as f:
        fraud = json.load(f)
    for flag in fraud.get("flags", []):
        rule_readable = flag["rule"].replace("_", " ")
        text = (
            f"Fraud flag ({rule_readable}, severity: {flag['severity']}) on "
            f"transaction(s) {', '.join(flag['txn_refs'])}: {flag['explanation']}"
        )
        documents.append(Document(
            doc_id=f"fraud::{'-'.join(flag['txn_refs'])}::{flag['rule']}",
            kind="fraud_flag",
            text=text,
            metadata=flag,
        ))

    return documents


class DocumentIndex:
    """TF-IDF index over a fixed set of documents, built once and queried
    many times (cheap enough here to rebuild on every process start)."""

    def __init__(self, documents: list[Document]):
        self.documents = documents
        # NOTE: deliberately NOT using sklearn's stop_words="english" -- its
        # built-in list (inherited from an old IR stopword list) filters out
        # "amount", which is a critical term in this domain, not noise. Short
        # structured documents like ours don't need stopword removal anyway;
        # TF-IDF's IDF weighting already downweights common words like "the".
        self._vectorizer = TfidfVectorizer()
        self._matrix = self._vectorizer.fit_transform([d.text for d in documents]) if documents else None

    def search(self, query: str, top_k: int = 5) -> list[tuple[Document, float]]:
        if not self.documents or self._matrix is None:
            return []
        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._matrix)[0]
        ranked = sorted(zip(self.documents, scores), key=lambda pair: pair[1], reverse=True)
        return [(doc, float(score)) for doc, score in ranked[:top_k] if score > 0]


def load_index(reconciliation_report_path: str | Path = "data/reconciliation_report.json",
                fraud_flags_path: str | Path = "data/fraud_flags.json") -> DocumentIndex:
    docs = build_documents(reconciliation_report_path, fraud_flags_path)
    return DocumentIndex(docs)