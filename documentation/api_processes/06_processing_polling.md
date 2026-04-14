# Process 6: Short Polling

## Goal

Track ingestion progress and inspect generated chunks.

## Endpoints

| Method | Path                                              | Auth         | Typical Trigger                |
| ------ | ------------------------------------------------- | ------------ | ------------------------------ |
| GET    | /api/projects/{project_id}/files                  | JWT required | Short polling while processing |
| GET    | /api/projects/{project_id}/files/{file_id}/chunks | JWT required | File details modal/view        |

## GET /api/projects/{project_id}/files

### Purpose

- Return current file list plus processing statuses.
- Used by the frontend short polling mechanism while non-terminal statuses exist.

### Status Values Seen in Pipeline

- uploading
- queued
- processing
- partitioning
- chunking
- summarising
- vectorization
- completed

## GET /api/projects/{project_id}/files/{file_id}/chunks

### Purpose

- Return generated document chunks for a specific file.
- Verifies document ownership before returning chunks.

### Success Response

```json
{
  "message": "Document chunks retrieved successfully",
  "data": [
    {
      "id": "<chunk_uuid>",
      "document_id": "<document_uuid>",
      "chunk_index": 0,
      "content": "..."
    }
  ]
}
```

## Failure Modes

- 404 for file not found/access denied.
- 500 for unexpected backend/database errors.

## Implementation Reference

- Route: server/src/routes/files.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
