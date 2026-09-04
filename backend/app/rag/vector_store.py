"""
Lightweight vector-store RAG — no Chroma/hnswlib, to stay within a
512MB memory budget. Documents are embedded with a simple sklearn
HashingVectorizer and stored as a small JSON file per merchant.
Retrieval uses cosine similarity, computed with numpy.
"""
from __future__ import annotations
import json
import os
import uuid
from typing import List, Optional

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from app.config import settings

_vectorizer = None


def _get_vectorizer():
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = HashingVectorizer(n_features=256, alternate_sign=False, norm="l2")
    return _vectorizer


def _store_path(merchant_id: int) -> str:
    os.makedirs(settings.CHROMA_DIR, exist_ok=True)
    return os.path.join(settings.CHROMA_DIR, f"merchant_{merchant_id}.json")


def _load(merchant_id: int) -> list[dict]:
    path = _store_path(merchant_id)
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)


def _save(merchant_id: int, records: list[dict]) -> None:
    path = _store_path(merchant_id)
    with open(path, "w") as f:
        json.dump(records, f)


def add_documents(
    merchant_id: int,
    documents: List[str],
    metadatas: Optional[List[dict]] = None,
) -> int:
    """Index new knowledge documents for this merchant."""
    if not documents:
        return 0
    vec = _get_vectorizer()
    vectors = vec.transform(documents).toarray().tolist()
    metadatas = metadatas or [{} for _ in documents]

    records = _load(merchant_id)
    for doc, vector, meta in zip(documents, vectors, metadatas):
        records.append({
            "id": str(uuid.uuid4()),
            "document": doc,
            "vector": vector,
            "metadata": meta,
        })
    _save(merchant_id, records)
    return len(documents)


def query(
    merchant_id: int,
    question: str,
    top_k: int = 6,
) -> List[str]:
    """Retrieve the most relevant indexed facts for a question."""
    records = _load(merchant_id)
    if not records:
        return []

    vec = _get_vectorizer()
    q_vector = np.array(vec.transform([question]).toarray()[0])

    scored = []
    for r in records:
        r_vector = np.array(r["vector"])
        denom = (np.linalg.norm(q_vector) * np.linalg.norm(r_vector)) or 1e-9
        similarity = float(np.dot(q_vector, r_vector) / denom)
        scored.append((similarity, r["document"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:top_k]]
