# Process 4: File Ingestion (S3 + Celery)

## Goal

Upload a file to S3, register it in project_documents, and queue asynchronous ingestion.

## Flow Summary

1. Request presigned upload URL.
2. Upload bytes directly to S3.
3. Confirm upload and enqueue Celery ingestion.
4. Worker updates statuses and creates chunks.

## Step 1: Generate Presigned URL

| Method | Path                                       | Auth         |
| ------ | ------------------------------------------ | ------------ |
| POST   | /api/projects/{project_id}/file/upload-url | JWT required |

### Request Body

```json
{
  "filename": "paper.pdf",
  "file_size": 123456,
  "file_type": "application/pdf"
}
```

### Behavior

- Verifies project ownership.
- Generates unique S3 key.
- Creates project_documents row with processing_status = uploading.
- Returns upload_url and document metadata.

### Success Response

```json
{
  "message": "Presigned URL generated successfully",
  "data": {
    "upload_url": "https://...",
    "s3_key": "projects/<project_id>/documents/<uuid>.pdf",
    "document": {
      "id": "<document_uuid>",
      "processing_status": "uploading"
    }
  }
}
```

## Step 2: Upload to S3

| Method | Path               | Auth                        |
| ------ | ------------------ | --------------------------- |
| PUT    | <presigned_s3_url> | Presigned URL authorization |

### Behavior

- Frontend uploads file content directly to S3.
- Backend is not in data path for file bytes.

## Step 3: Confirm Upload and Queue Ingestion

| Method | Path                                    | Auth         |
| ------ | --------------------------------------- | ------------ |
| POST   | /api/projects/{project_id}/file/confirm | JWT required |

### Request Body

```json
{
  "s3_key": "projects/<project_id>/documents/<uuid>.pdf"
}
```

### Behavior

1. Verifies document ownership by s3_key + project_id + clerk_id.
2. Sets processing_status to queued.
3. Enqueues perform_rag_ingestion(document_id).
4. Stores Celery task_id in project_documents.

### Success Response

```json
{
  "message": "Upload to S3 confirmed, background processing started.",
  "data": {
    "id": "<document_uuid>",
    "processing_status": "queued",
    "task_id": "<celery_task_id>"
  }
}
```

## Failure Modes

- 400 when required s3_key is missing.
- 404 for not found/access denied resources.
- 422 for write/update failures.
- 500 for unexpected backend/storage/queue failures.

## Implementation Reference

- Route: server/src/routes/files.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
