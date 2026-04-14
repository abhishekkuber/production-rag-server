# Process 5: URL Ingestion (Direct Queue)

## Goal

Ingest webpage content directly without S3 upload.

## Endpoint

| Method | Path                            | Auth         |
| ------ | ------------------------------- | ------------ |
| POST   | /api/projects/{project_id}/urls | JWT required |

## Request Body

```json
{
  "url": "https://example.com/article"
}
```

## Behavior

1. Normalizes URL to include scheme when missing.
2. Validates URL format.
3. Creates project_documents row with:
   - source_type = url
   - source_url = normalized URL
   - processing_status = queued
4. Enqueues perform_rag_ingestion(document_id).
5. Stores task_id on the document row.

## Success Response

```json
{
  "message": "URL added successfully, background processing started.",
  "data": {
    "id": "<document_uuid>",
    "source_type": "url",
    "source_url": "https://example.com/article",
    "processing_status": "queued",
    "task_id": "<celery_task_id>"
  }
}
```

## Failure Modes

- 400 for invalid URL.
- 422 for insert/update failures.
- 500 for unexpected backend/queue failures.

## Implementation Reference

- Route: server/src/routes/files.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
