"""
Eval-only constants. Kept separate from the app so evals never change how
projects are created through the UI.
"""

EVAL_CLERK_ID = "eval_open_ragbench"
EVAL_PROJECT_NAME = "evals"

# Copied from the defaults in src/routes/projects.py create_project,
# except agent_type: "simple" so evals never trigger web search.
EVAL_PROJECT_SETTINGS = {
    "embedding_model": "text-embedding-3-large",
    "rag_strategy": "basic",
    "agent_type": "simple",
    "chunks_per_search": 10,
    "final_context_size": 5,
    "similarity_threshold": 0.3,
    "number_of_queries": 5,
    "reranking_enabled": True,
    "reranking_model": "rerank-english-v3.0",
    "vector_weight": 0.7,
    "keyword_weight": 0.3,
}
