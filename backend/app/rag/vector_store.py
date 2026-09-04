"""
Real vector-store RAG, backed by Chroma.
Chroma is loaded lazily so the FastAPI application can boot without
initializing native ML/RAG components during module import.
Uses a lightweight scikit-learn based embedding function instead of
Chroma's default ONNX-based embedder, since onnxruntime crashes with
an illegal-instruction error on some cloud hosts.
"""
from __future__ import annotations
import uuid
from typing import List, Optional

from app.config import settings

_client = None
_embedding_fn = None


def _get_embedding_fn():
    global _embedding_fn
    if _embedding_fn is None:
        from sklearn.feature_extraction.text import HashingVectorizer

        class SklearnEmbeddingFunction:
            def __init__(self, n_features: int = 256):
                self._vectorizer = HashingVectorizer(
                    n_features=n_features, alternate_sign=False, norm="l2"
                )

            def __call__(self, input):
                vecs = self._vectorizer.transform(input).toarray()
                return vecs.tolist()

            def name(self):
                return "sklearn-hashing"

        _embedding_fn = SklearnEmbeddingFunction()
    return _embedding_fn


def _get_client():
    global _client
    if _client is None:
        import chromadb
        _client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
    return _client


def _collection_name(merchant_id: int) -> str:
    return f"merchant_{merchant_id}"


def get_collection(merchant_id: int):
    client = _get_client()
    return client.get_or_create_collection(
        name=_collection_name(merchant_id),
        embedding_function=_get_embedding_fn(),
    )


def add_documents(
    merchant_id: int,
    documents: List[str],
    metadatas: Optional[List[dict]] = None,
) -> int:
    """Index new knowledge documents for this merchant."""
    if not documents:
        return 0
    collection = get_collection(merchant_id)
    ids = [str(uuid.uuid4()) for _ in documents]
    metadatas = metadatas or [{} for _ in documents]
    collection.add(
        documents=documents,
        ids=ids,
        metadatas=metadatas,
    )
    return len(documents)


def query(
    merchant_id: int,
    question: str,
    top_k: int = 6,
) -> List[str]:
    """Retrieve relevant indexed facts for a question."""
    collection = get_collection(merchant_id)
    count = collection.count()
    if count == 0:
        return []
    top_k = min(top_k, count)
    results = collection.query(
        query_texts=[question],
        n_results=top_k,
    )
    docs = results.get("documents", [[]])[0]
    return docs
