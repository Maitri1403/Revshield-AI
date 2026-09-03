"""
Real vector-store RAG, backed by Chroma (persistent, local, on-disk).

Each merchant gets their own collection so one merchant's data never
leaks into another's retrieval context. Documents are short, dated,
plain-language facts distilled from that day's data upload (see
rag/knowledge_builder.py) — this is what "trains" the system day by
day: every daily upload adds fresh documents, so retrieval quality and
grounding improve the longer a merchant uses the tool.

Embeddings: Chroma's bundled default embedding function (a local
MiniLM ONNX model, no external API call, no extra key needed) turns
each document into a vector at index time and turns each query into a
vector at search time; Chroma does the nearest-neighbour search.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

import chromadb

from app.config import settings

_client = chromadb.PersistentClient(path=settings.CHROMA_DIR)


def _collection_name(merchant_id: int) -> str:
    return f"merchant_{merchant_id}"


def get_collection(merchant_id: int):
    return _client.get_or_create_collection(name=_collection_name(merchant_id))


def add_documents(merchant_id: int, documents: List[str], metadatas: Optional[List[dict]] = None) -> int:
    """Index new knowledge documents for this merchant. Returns count added."""
    if not documents:
        return 0
    collection = get_collection(merchant_id)
    ids = [str(uuid.uuid4()) for _ in documents]
    metadatas = metadatas or [{} for _ in documents]
    collection.add(documents=documents, ids=ids, metadatas=metadatas)
    return len(documents)


def query(merchant_id: int, question: str, top_k: int = 6) -> List[str]:
    """Retrieve the most relevant indexed facts for a question / analysis task."""
    collection = get_collection(merchant_id)
    if collection.count() == 0:
        return []
    top_k = min(top_k, collection.count())
    results = collection.query(query_texts=[question], n_results=top_k)
    docs = results.get("documents", [[]])[0]
    return docs
