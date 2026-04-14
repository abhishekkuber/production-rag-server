# Process 9: Document Cleanup

## Goal

Delete a project document and remove backing S3 object when applicable.

## Endpoint

| Method | Path                                       | Auth         |
| ------ | ------------------------------------------ | ------------ |
| DELETE | /api/projects/{project_id}/files/{file_id} | JWT required |

## Behavior

1. Verifies document ownership using file_id + project_id + clerk_id.
2. If s3_key exists, deletes object from S3 bucket.
3. Deletes project_documents row.
4. Returns deleted document payload.

## Success Response

```json
{
  "message": "File deleted successfully",
  "data": {
    "id": "<document_uuid>",
    "project_id": "<project_uuid>"
  }
}
```

## Failure Modes

- 404 for not found/access denied.
- 500 for S3 deletion failure or unexpected backend errors.

## Notes

- URL-sourced documents may not have an s3_key; DB row deletion still proceeds.

## Implementation Reference

- Route: server/src/routes/files.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
