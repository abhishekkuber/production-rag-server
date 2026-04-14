# Process 8: Retrieval and Agent Settings Tuning

## Goal

Read and update project-level retrieval and generation behavior.

## Endpoints

| Method | Path                                | Auth                         |
| ------ | ----------------------------------- | ---------------------------- |
| GET    | /api/projects/{project_id}/settings | No auth dependency currently |
| PUT    | /api/projects/{project_id}/settings | JWT required                 |

## Settings Fields

The update payload follows ProjectSettings model.

```json
{
  "embedding_model": "text-embedding-3-large",
  "rag_strategy": "hybrid",
  "agent_type": "agentic",
  "chunks_per_search": 10,
  "final_context_size": 5,
  "similarity_threshold": 0.3,
  "number_of_queries": 5,
  "reranking_enabled": true,
  "reranking_model": "rerank-english-v3.0",
  "vector_weight": 0.7,
  "keyword_weight": 0.3
}
```

## GET Behavior

- Reads project_settings by project_id.
- Returns one settings object.

## PUT Behavior

1. Verifies project ownership by project_id + clerk_id.
2. Updates project_settings with request payload.
3. Returns updated settings row.

## Why This Matters

- rag_strategy controls retrieval method.
- agent_type selects simple vs agentic message path behavior.
- reranking and weight fields tune ranking quality and blending.

## Failure Modes

- 404 for missing settings/project ownership mismatch.
- 422 for update failures.
- 500 for unexpected backend/database errors.

## Implementation Reference

- Route: server/src/routes/projects.py
- Model: server/src/models/index.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
