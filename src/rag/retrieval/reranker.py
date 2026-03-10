from typing import List, Dict

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
