"""
RAG retrieval pipeline: hybrid search over RTL corpus and knowledge base.
- retrieve(): deterministic fetch by module name + BM25+semantic hybrid fill
- query_knowledge(): semantic search over knowledge corpus
"""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import chromadb
import torch
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModel

logger = logging.getLogger(__name__)

REPO_ROOT = Path(os.getenv("REPO_ROOT", Path(__file__).parent.parent))
CHROMA_PATH = REPO_ROOT / "data" / "chromadb"

os.environ.setdefault("HF_HOME", str(REPO_ROOT / "data" / "model_cache"))

MINILM_MODEL   = "sentence-transformers/all-MiniLM-L6-v2"
CROSS_MODEL    = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CODEBERT_MODEL = "microsoft/codebert-base"

# ── Component → known good reference modules ───────────────────────────────────
COMPONENT_TO_MODULES: dict[str, list[str]] = {
    "alu":       ["ibex_alu", "ibex_ex_block", "rv32i_alu"],
    "decoder":   ["ibex_decoder", "rv32i_decoder"],
    "regfile":   ["ibex_register_file_ff", "rv32i_basereg"],
    "lsu":       ["ibex_load_store_unit", "rv32i_memoryaccess"],
    "hazard":    ["rv32i_forwarding"],
    "writeback": ["rv32i_writeback"],
    "full_core": ["picorv32"],
}

# Singleton clients and models
_chroma_client: Optional[chromadb.PersistentClient] = None
_rtl_collection: Optional[chromadb.Collection] = None
_knowledge_collection: Optional[chromadb.Collection] = None
_minilm_model: Optional[SentenceTransformer] = None
_cross_model: Optional[object] = None
_codebert_model = None
_codebert_tokenizer = None


def _get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _chroma_client


def _get_rtl_collection() -> chromadb.Collection:
    global _rtl_collection
    if _rtl_collection is None:
        client = _get_chroma_client()
        _rtl_collection = client.get_or_create_collection(
            "rtl_corpus",
            metadata={"hnsw:space": "cosine"},
        )
    return _rtl_collection


def _get_knowledge_collection() -> chromadb.Collection:
    global _knowledge_collection
    if _knowledge_collection is None:
        client = _get_chroma_client()
        _knowledge_collection = client.get_or_create_collection(
            "knowledge_corpus",
            metadata={"hnsw:space": "cosine"},
        )
    return _knowledge_collection


def _get_minilm() -> SentenceTransformer:
    global _minilm_model
    if _minilm_model is None:
        logger.info("Loading MiniLM model (%s) ...", MINILM_MODEL)
        _minilm_model = SentenceTransformer(MINILM_MODEL)
    return _minilm_model


def _get_cross_encoder():
    """Lazy-load the CrossEncoder singleton."""
    global _cross_model
    if _cross_model is None:
        from sentence_transformers import CrossEncoder
        logger.info("Loading Cross-Encoder model (%s) ...", CROSS_MODEL)
        _cross_model = CrossEncoder(CROSS_MODEL)
    return _cross_model


def _get_codebert():
    global _codebert_model, _codebert_tokenizer
    if _codebert_model is None:
        logger.info("Loading CodeBERT model (%s) ...", CODEBERT_MODEL)
        _codebert_tokenizer = AutoTokenizer.from_pretrained(CODEBERT_MODEL)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _codebert_model = AutoModel.from_pretrained(CODEBERT_MODEL).to(device).eval()
        logger.info("CodeBERT loaded on %s", device)
    return _codebert_model, _codebert_tokenizer


def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    sum_hidden = torch.sum(last_hidden_state * mask_expanded, dim=1)
    sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
    return sum_hidden / sum_mask


def embed_query(text: str) -> list[float]:
    """Embed a query string with MiniLM. Returns 384-dim float vector."""
    model = _get_minilm()
    return model.encode(text, convert_to_numpy=True).tolist()


def embed_query_codebert(text: str) -> list[float]:
    """Embed a query string with CodeBERT mean-pooling. Returns 768-dim float vector."""
    model, tokenizer = _get_codebert()
    device = next(model.parameters()).device
    encoded = tokenizer(
        text,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    ).to(device)
    with torch.no_grad():
        outputs = model(**encoded)
    embedding = _mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
    return embedding.cpu().squeeze(0).tolist()


def _bm25_search(
    corpus_docs: list[str],
    corpus_ids: list[str],
    query: str,
    k: int,
) -> list[tuple[str, float]]:
    """
    BM25 search over corpus_docs. Returns list of (doc_id, score) sorted descending.
    Uses whitespace tokenization.
    """
    tokenized_corpus = [doc.lower().split() for doc in corpus_docs]
    tokenized_query = query.lower().split()
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(tokenized_query)
    ranked = sorted(zip(corpus_ids, scores), key=lambda x: x[1], reverse=True)
    return ranked[:k]


def _reciprocal_rank_fusion(
    semantic_ids: list[str],
    bm25_ids: list[str],
    k: int = 60,
) -> list[str]:
    """
    Reciprocal Rank Fusion: combines semantic and BM25 rankings.
    RRF score = sum(1 / (k + rank_i)) for each retrieval method.
    Returns merged list sorted by RRF score descending.
    """
    scores: dict[str, float] = {}
    for rank, doc_id in enumerate(semantic_ids, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    for rank, doc_id in enumerate(bm25_ids, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda x: scores[x], reverse=True)


def _cross_encode_rerank(query: str, candidates: list[dict], top_n: int = 5) -> list[dict]:
    """
    Rerank candidates using a Cross-Encoder.
    Takes the query and a list of candidates, scores each pair, and returns top_n.
    """
    if not candidates:
        return []

    model = _get_cross_encoder()
    # Prepare pairs for the cross-encoder: (query, document)
    pairs = [[query, c["document"]] for c in candidates]
    scores = model.predict(pairs)

    # Attach scores and sort
    for i, score in enumerate(scores):
        candidates[i]["cross_score"] = float(score)

    ranked = sorted(candidates, key=lambda x: x["cross_score"], reverse=True)
    return ranked[:top_n]


def retrieve(component: str, query: str, k: int = 3) -> list[dict]:
    """
    Hybrid retrieval for RTL context.

    Step 1 (Deterministic): Fetch all documents from rtl_collection where
      metadata.module_name is in COMPONENT_TO_MODULES[component].
      Always include these known-good reference modules.

    Step 2 (Hybrid fill): If deterministic results < k:
      - Semantic search via CodeBERT 768-dim query.
      - BM25 keyword search.
      - RRF to combine; fill remaining slots (excluding already-included IDs).

    Returns list of dicts with keys: id, document, metadata.
    """
    collection = _get_rtl_collection()

    if collection.count() == 0:
        logger.warning("rtl_corpus is empty — returning no RTL context.")
        return []

    target_modules = COMPONENT_TO_MODULES.get(component, [])
    results: list[dict] = []
    seen_ids: set[str] = set()

    # Step 1: Deterministic fetch
    if target_modules:
        for module_name in target_modules:
            try:
                res = collection.get(
                    where={"module_name": {"$eq": module_name}},
                    include=["documents", "metadatas"],
                )
                for doc_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
                    if doc_id not in seen_ids:
                        results.append({"id": doc_id, "document": doc, "metadata": meta})
                        seen_ids.add(doc_id)
            except Exception as e:
                logger.debug("Deterministic fetch for %s failed: %s", module_name, e)

    # Step 2: Hybrid fill for remaining slots
    remaining = k - len(results)
    if remaining > 0:
        # Get all documents for BM25
        try:
            all_docs_res = collection.get(include=["documents", "metadatas"])
            all_ids = all_docs_res["ids"]
            all_docs = all_docs_res["documents"]

            # Semantic search with CodeBERT
            query_vec = embed_query_codebert(query)
            n_results = min(k * 3, collection.count())
            semantic_res = collection.query(
                query_embeddings=[query_vec],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
            semantic_ids = semantic_res["ids"][0] if semantic_res["ids"] else []

            # BM25 search
            bm25_ranked = _bm25_search(all_docs, all_ids, query, k=n_results)
            bm25_ids = [doc_id for doc_id, _ in bm25_ranked]

            # RRF merge
            merged_ids = _reciprocal_rank_fusion(semantic_ids, bm25_ids)

            # Build lookup for fast access
            id_to_doc = dict(zip(all_ids, all_docs))
            id_to_meta = dict(zip(all_ids, all_docs_res["metadatas"]))

            for doc_id in merged_ids:
                if remaining <= 0:
                    break
                if doc_id not in seen_ids and doc_id in id_to_doc:
                    results.append({
                        "id": doc_id,
                        "document": id_to_doc[doc_id],
                        "metadata": id_to_meta.get(doc_id, {}),
                    })
                    seen_ids.add(doc_id)
                    remaining -= 1

            # Step 3: Final Cross-Encoder Rerank of the collected candidates
            # We take all 'results' and rerank them based on the query
            if results:
                results = _cross_encode_rerank(query, results, top_n=k)

        except Exception as e:
            logger.warning("Hybrid fill failed: %s", e)

    return results[:k]


def query_knowledge(
    query: str,
    k: int = 3,
    category_filter: Optional[str] = None,
) -> list[dict]:
    """
    Query knowledge_corpus with MiniLM embedding of query.
    Optional filter by category ('bug_pattern', 'debug_lesson', 'angelo_pattern').
    Returns list of dicts with keys: id, document, metadata, distance.
    """
    collection = _get_knowledge_collection()

    if collection.count() == 0:
        logger.warning("knowledge_corpus is empty — returning no knowledge context.")
        return []

    query_vec = embed_query(query)
    where_filter = {"category": {"$eq": category_filter}} if category_filter else None

    try:
        res = collection.query(
            query_embeddings=[query_vec],
            n_results=min(k, collection.count()),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.warning("knowledge query failed: %s", e)
        return []

    results = []
    for doc_id, doc, meta, dist in zip(
        res["ids"][0],
        res["documents"][0],
        res["metadatas"][0],
        res["distances"][0],
    ):
        results.append({"id": doc_id, "document": doc, "metadata": meta, "distance": dist})

    return results
