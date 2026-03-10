from src.rag.retrieval.db import get_project_settings, get_project_documents
from src.rag.retrieval.search import vector_search, hybrid_search, multi_query_hybrid_search, multi_query_vector_search
from src.rag.retrieval.context_builder import separate_content_types
from fastapi import HTTPException

def retrieve_context_and_build_prompt(project_id, user_query):
    try:
        # Step 1: Load the project settings
        project_settings = get_project_settings(project_id)

        # Step 2: Retrieve the IDs of the documents associated with this project
        document_ids = get_project_documents(project_id)

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

        # Step 4: Cap the chunks at 'final_context_size' which is defined by the user in project settings
        chunks = chunks[:project_settings['final_context_size']]

        texts, images, tables, citations = separate_content_types(chunks)
        
        return texts, images, tables, citations

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed in the RAG retrieval step. Reason: {str(e)}")
    
