from src.services.llm import open_ai_models
from src.services.database import supabase
from src.rag.retrieval.reranker import reciprocal_rank_fusion
from src.models.index import QueryVariations

from langchain_core.messages import HumanMessage, SystemMessage
from typing import List


def vector_search(user_query, document_ids, project_settings):
    query_embedding = open_ai_models['embedding_model'].embed_query(user_query)
    vector_search_results = supabase.rpc(
        fn="vector_search_document_chunks",
        params= {
            "query_embedding": query_embedding,
            "filter_document_ids": document_ids,
            "match_threshold": project_settings['similarity_threshold'],
            "chunks_per_search": project_settings['chunks_per_search'],
        }
    ).execute()

    return vector_search_results.data if vector_search_results.data else []

def hybrid_search(user_query, document_ids, project_settings):
    vector_search_chunks = vector_search(user_query, document_ids, project_settings)
    keyword_search_chunks = _keyword_search(user_query, document_ids, project_settings)

    # Combine using Reciprocal Rank Fusion
    return reciprocal_rank_fusion(
        [vector_search_chunks, keyword_search_chunks],
        [project_settings['vector_weight'], project_settings['keyword_weight']]
    )

def multi_query_vector_search(user_query, document_ids, project_settings):
    queries = _generate_query_variations(user_query, project_settings['number_of_queries'])
    all_results = []
    for i, query in enumerate(queries):
        results = vector_search(query, document_ids, project_settings)
        print(f"Query {i+1}: {query}\nReturned {len(results)} chunks\n\n")
        all_results.append(results)
    chunks = reciprocal_rank_fusion(all_results)
    return chunks


def multi_query_hybrid_search(user_query, document_ids, project_settings):
    queries = _generate_query_variations(user_query, project_settings['number_of_queries'])
    all_results = []
    for i, query in enumerate(queries):
        results = hybrid_search(query, document_ids, project_settings)
        print(f"Query {i+1}: {query}\nReturned {len(results)} chunks\n\n")
        all_results.append(results)
    chunks = reciprocal_rank_fusion(all_results)
    return chunks




def _generate_query_variations(user_query: str,  num_queries: int=3) -> List[str]:
    """
        Take the original query and make multiple variations of it. Used in multi query search strategies.
    """
    system_prompt = f"""Generate {num_queries-1} alternative ways to phrase this questions for document search. Use different keywords and synonyms while maintaining the same intent. Return exactly {num_queries-1} variations."""

    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Original query: {user_query}")
        ]
        structured_llm = open_ai_models["chat_llm"].with_structured_output(QueryVariations)
        result = structured_llm.invoke(messages)
        return [user_query] + result.variations[:num_queries-1]
    
    except Exception as e:
        print(f"Cannot generate query variations. Reason : {str(e)}")
        import traceback
        traceback.print_exc()
        return [user_query]


def _keyword_search(user_query, document_ids, project_settings):
    keyword_search_results = supabase.rpc(
        fn="keyword_search_document_chunks",
        params={
            "query_text":user_query,
            "filter_document_ids": document_ids,
            "chunks_per_search": project_settings['chunks_per_search']
        }
    ).execute()
    return keyword_search_results.data if keyword_search_results.data else []
