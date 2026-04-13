from typing import List, Dict

from src.config.logging import get_logger
from src.services.cohere_reranker import cohere_reranker


logger = get_logger(__name__)

def reciprocal_rank_fusion(search_results_list: List[List[Dict]], weights: List[float]=None, k: int=60):
    """
        Do the Reciprocal Rank Fusion and return the new ranked list
    """

    # not search_results_list : Check whether the outer list is empty / falsy / null 
    # not any(search_results_list) : Check whether all the inner lists are empty.
    if not search_results_list or not any(search_results_list):
        return []
    
    if weights is None:
        weights = [1.0 / len(search_results_list)] * len(search_results_list)

    chunk_scores = {}
    all_chunks = {}

    for search_idx, results in enumerate(search_results_list):
        search_weight = weights[search_idx]

        for rank, chunk in enumerate(results):
            chunk_id = chunk.get('id')
            if not chunk_id:
                continue

            rrf_score = search_weight * (1.0 / (rank + 1 + k))
            if chunk_id in chunk_scores:
                chunk_scores[chunk_id] += rrf_score
            else:
                chunk_scores[chunk_id] = rrf_score
                all_chunks[chunk_id] = chunk
    
    # Sort and get the list of chunk ids based on their scores
    sorted_chunk_ids = sorted(chunk_scores.keys(), key=lambda chunk_id: chunk_scores[chunk_id], reverse=True)
    return [all_chunks[chunk_id] for chunk_id in sorted_chunk_ids]


def _chunk_to_document_text(chunk: Dict) -> str:
    """Create a rerankable text payload from a chunk record."""
    original_content = chunk.get("original_content") or {}
    text = original_content.get("text") or chunk.get("content") or ""
    if text:
        return str(text)

    # Fallback representation if text is missing.
    return str(original_content) if original_content else str(chunk)


def cohere_rerank_chunks(
    user_query: str,
    chunks: List[Dict],
    model: str = "rerank-english-v3.0",
) -> List[Dict]:
    """Rerank retrieved chunks with Cohere and return in relevance order."""
    if not chunks:
        return []

    documents = [_chunk_to_document_text(chunk) for chunk in chunks]

    try:
        response = cohere_reranker.rerank(
            model=model,
            query=user_query,
            documents=documents,
            top_n=len(documents),
        )

        ranked_chunks: List[Dict] = []
        for result in response.results:
            idx = getattr(result, "index", None)
            if idx is None or idx < 0 or idx >= len(chunks):
                continue
            ranked_chunks.append(chunks[idx])

        if ranked_chunks:
            return ranked_chunks

        logger.warning("cohere_rerank_empty_results_fallback")
        return chunks
    except Exception as e:
        logger.warning("cohere_rerank_failed_fallback", error=str(e))
        return chunks
