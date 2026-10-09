"""
The copilot's public interface: ask(question) -> grounded answer.

Grounding matters here specifically because of Marcus's "no black box"
requirement -- every answer must be traceable back to the actual
reconciliation breaks / fraud flags that informed it, not a plausible-
sounding hallucination. The prompt explicitly instructs the model to only
use the provided context and to say so if it doesn't know, and the returned
CopilotAnswer always carries the source documents alongside the text so the
UI (week 3) can show citations.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.copilot.index import Document, DocumentIndex
from app.copilot.llm_client import LLMClient, get_llm_client

SYSTEM_PROMPT = """You are LedgerOps Copilot, an assistant for a payments \
company's operations and compliance team. Answer the user's question using \
ONLY the context provided below -- do not use outside knowledge, and do not \
guess. If the context doesn't contain enough information to answer, say so \
plainly rather than speculating. Keep answers short and concrete. Reference \
specific transaction IDs when relevant, since the ops team needs to be able \
to look them up."""


@dataclass
class CopilotAnswer:
    answer: str
    sources: list[Document] = field(default_factory=list)

    def format_with_sources(self) -> str:
        out = self.answer
        if self.sources:
            out += "\n\nSources:\n" + "\n".join(f"- {d.doc_id}" for d in self.sources)
        return out


def build_prompt(question: str, context_docs: list[Document]) -> str:
    context_block = "\n".join(f"- {d.text}" for d in context_docs) or "(no relevant records found)"
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Context:\n{context_block}\n\n"
        f"Question: {question}\n"
        f"Answer:"
    )


def ask(question: str, index: DocumentIndex, llm: LLMClient | None = None,
         top_k: int = 5) -> CopilotAnswer:
    llm = llm or get_llm_client()
    results = index.search(question, top_k=top_k)
    docs = [doc for doc, _score in results]

    prompt = build_prompt(question, docs)
    answer_text = llm.generate(prompt)

    return CopilotAnswer(answer=answer_text, sources=docs)