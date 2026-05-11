from functools import lru_cache

import numpy as np


DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=2)
def load_embedding_model(model_name=DEFAULT_MODEL):
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model_name or DEFAULT_MODEL)
    except Exception:
        return None


def embed_texts(texts, model_name=DEFAULT_MODEL):
    model = load_embedding_model(model_name)
    if model is None:
        return None
    try:
        return model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
    except Exception:
        return None


def compute_cosine_similarity(query_embedding, matrix_embeddings):
    if query_embedding is None or matrix_embeddings is None or len(matrix_embeddings) == 0:
        return np.array([])
    query = np.asarray(query_embedding).reshape(1, -1)
    matrix = np.asarray(matrix_embeddings)
    try:
        from sklearn.metrics.pairwise import cosine_similarity

        return cosine_similarity(query, matrix)[0]
    except Exception:
        qn = np.linalg.norm(query, axis=1, keepdims=True)
        mn = np.linalg.norm(matrix, axis=1, keepdims=True)
        return ((query / np.maximum(qn, 1e-9)) @ (matrix / np.maximum(mn, 1e-9)).T)[0]


def best_semantic_match(text, keyword_rows, model_name=DEFAULT_MODEL):
    if not keyword_rows:
        return None, 0.0
    texts = [r.get("keyword", "") for r in keyword_rows]
    embeddings = embed_texts(texts, model_name)
    query = embed_texts([text], model_name)
    if embeddings is None or query is None:
        return None, 0.0
    sims = compute_cosine_similarity(query[0], embeddings)
    if len(sims) == 0:
        return None, 0.0
    idx = int(np.argmax(sims))
    return keyword_rows[idx], float(sims[idx] * 100)
