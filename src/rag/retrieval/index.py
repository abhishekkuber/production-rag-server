from src.rag.retrieval.db import get_project_settings, get_project_documents
from src.rag.retrieval.search import vector_search, hybrid_search, multi_query_hybrid_search, multi_query_vector_search
from src.rag.retrieval.context_builder import separate_content_types
from src.rag.retrieval.reranker import cohere_rerank_chunks
from src.config.logging import get_logger, set_project_id
from fastapi import HTTPException

logger = get_logger(__name__)

def retrieve_context_and_build_prompt(project_id, user_query):
    set_project_id(project_id)
    try:
        # Step 1: Load the project settings
        project_settings = get_project_settings(project_id)
        strategy = project_settings["rag_strategy"]
        logger.info("project_settings_retrieved", strategy=strategy, final_context_size=project_settings["final_context_size"])

        # Step 2: Retrieve the IDs of the documents associated with this project
        document_ids = get_project_documents(project_id)
        logger.info("documents_found", document_count=len(document_ids))

        # Step 3: See what type of search is in the project settings
        search_strategy = project_settings['rag_strategy']
        chunks = []

        SEARCH_STRATEGIES = {
            "basic": vector_search,
            "hybrid": hybrid_search,
            "multi-query-vector": multi_query_vector_search,
            "multi-query-hybrid": multi_query_hybrid_search
        }

        chunks = SEARCH_STRATEGIES[search_strategy](user_query, document_ids, project_settings)
        logger.info(f"{SEARCH_STRATEGIES[search_strategy].__name__}_completed")
        # logger.info(f"{SEARCH_STRATEGIES[search_strategy].__name__}_completed", chunks_found=len(chunks))

        # Step 3.5: Optional reranking with Cohere before final context capping
        if project_settings.get("reranking_enabled", False) and chunks:
            rerank_model = project_settings.get("reranking_model", "rerank-english-v3.0")
            before_top_chunk_ids = [chunk.get("id") for chunk in chunks[:3]]
            chunks = cohere_rerank_chunks(user_query, chunks, model=rerank_model)
            after_top_chunk_ids = [chunk.get("id") for chunk in chunks[:3]]
            logger.info(
                "cohere_rerank_completed",
                model=rerank_model,
                reranked_chunk_count=len(chunks),
                before_top_chunk_ids=before_top_chunk_ids,
                after_top_chunk_ids=after_top_chunk_ids,
            )


        # Step 4: Cap the chunks at 'final_context_size' which is defined by the user in project settings
        chunks = chunks[:project_settings['final_context_size']]
        logger.info("chunks_limited", final_chunk_count=len(chunks))

        texts, images, tables, citations = separate_content_types(chunks)
        logger.info("retrieval_completed", texts_count=len(texts), images_count=len(images), tables_count=len(tables), citations_count=len(citations))
        
        return texts, images, tables, citations

    except Exception as e:
        logger.error("retrieval_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed in the RAG retrieval step. Reason: {str(e)}")
    