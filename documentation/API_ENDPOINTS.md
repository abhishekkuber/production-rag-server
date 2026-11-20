# API Endpoints (by Process)

Every route the server exposes, grouped by the user flow that calls it. Each process links to a detailed page with request and response shapes.

## Global Notes

- Most routes use `Depends(get_current_user_clerk_id)`: the client sends `Authorization: Bearer <clerk_jwt>`, Clerk verifies the token, and the backend uses its `sub` claim as `clerk_id`.
- Exceptions (see [Known Limitations](KNOWN_LIMITATIONS.md#security)):
  - `POST /api/users/create-user` is called by a Clerk webhook, not by a signed-in user.
  - `GET /api/projects/{project_id}/settings` has no auth check.
  - `POST /api/projects/{project_id}/chats/{chat_id}/messages/stream` takes `clerk_id` from the query string.

## 1. User Sign Up

Create an internal user row when Clerk emits a `user.created` event. [Details](api_processes/01_user_signup.md)

| Method | Path                   | Purpose                   |
| ------ | ---------------------- | ------------------------- |
| POST   | /api/users/create-user | Create internal users row |

## 2. Project Dashboard

Load and manage the signed-in user's projects. [Details](api_processes/02_project_dashboard.md)

| Method | Path                         | Trigger               | Purpose                                       |
| ------ | ---------------------------- | --------------------- | --------------------------------------------- |
| GET    | /api/projects                | Projects page mount   | Load all projects for current user            |
| POST   | /api/projects                | Create project action | Create project and default `project_settings` |
| GET    | /api/projects/quota/messages | Project UI render     | Load the current daily message quota          |
| DELETE | /api/projects/{project_id}   | Delete project action | Delete project and related DB data            |

## 3. Open a Project Workspace

Loaded in parallel when a project opens. [Details](api_processes/03_project_workspace.md)

| Method | Path                                | Purpose                                         |
| ------ | ----------------------------------- | ----------------------------------------------- |
| GET    | /api/projects/{project_id}          | Project metadata                                |
| GET    | /api/projects/{project_id}/chats    | Conversation list for sidebar                   |
| GET    | /api/projects/{project_id}/files    | Knowledge-base file list plus processing status |
| GET    | /api/projects/{project_id}/settings | Retrieval and agent settings                    |

## 4. Ingest a File

Presigned S3 uploads and a Celery task, so the API stays responsive while the file is processed. [Details](api_processes/04_file_ingestion.md)

| Method | Path                                       | Purpose                                                                              |
| ------ | ------------------------------------------ | ------------------------------------------------------------------------------------ |
| POST   | /api/projects/{project_id}/file/upload-url | Generate presigned S3 URL and create `project_documents` row with `uploading` status |
| PUT    | <presigned_s3_url>                         | Upload file bytes directly from client to S3                                         |
| POST   | /api/projects/{project_id}/file/confirm    | Mark as `queued`, enqueue `perform_rag_ingestion(document_id)`, persist `task_id`    |

## 5. Ingest a URL

URL ingestion skips S3 and queues work immediately. [Details](api_processes/05_url_ingestion.md)

| Method | Path                            | Purpose                                                                                   |
| ------ | ------------------------------- | ----------------------------------------------------------------------------------------- |
| POST   | /api/projects/{project_id}/urls | Validate URL, create queued `project_documents` row, enqueue ingestion, persist `task_id` |

## 6. Processing Status and Chunks

The front end polls while any document is still processing. [Details](api_processes/06_processing_polling.md)

| Method | Path                                              | Trigger                                     | Purpose                                                   |
| ------ | ------------------------------------------------- | ------------------------------------------- | --------------------------------------------------------- |
| GET    | /api/projects/{project_id}/files                  | About every 3s while status is non-terminal | Refresh status from `project_documents.processing_status` |
| GET    | /api/projects/{project_id}/files/{file_id}/chunks | Document details view                       | Inspect generated chunks                                  |

## 7. Chats and Messages

Create, load and delete chats, and send messages to the agent. [Details](api_processes/07_chat_lifecycle.md)

| Method | Path                                                                     | Purpose                                                       |
| ------ | ------------------------------------------------------------------------ | ------------------------------------------------------------- |
| POST   | /api/chats                                                               | Create chat under a project                                   |
| GET    | /api/chats/{chat_id}                                                     | Load chat with ordered message history                        |
| DELETE | /api/chats/{chat_id}                                                     | Delete chat                                                   |
| POST   | /api/projects/{project_id}/chats/{chat_id}/messages/stream?clerk_id=<id> | Stream the agent's reply as SSE and save it (used by the UI)  |
| POST   | /api/projects/{project_id}/chats/{chat_id}/messages                      | Same, but returns the whole reply as one JSON response        |

## 8. Retrieval and Agent Settings

Read and update a project's retrieval and agent settings. [Details](api_processes/08_settings_tuning.md)

| Method | Path                                | Purpose                                   |
| ------ | ----------------------------------- | ----------------------------------------- |
| GET    | /api/projects/{project_id}/settings | Read current retrieval and agent settings |
| PUT    | /api/projects/{project_id}/settings | Persist strategy and agent tuning updates |

## 9. Document Cleanup

Delete a document and its S3 object. [Details](api_processes/09_document_cleanup.md)

| Method | Path                                       | Purpose                                                      |
| ------ | ------------------------------------------ | ------------------------------------------------------------ |
| DELETE | /api/projects/{project_id}/files/{file_id} | Delete document row and delete S3 object when source is file |

## 10. Feedback

Rate an assistant message, with an optional category and comment. [Details](api_processes/10_feedback.md)

| Method | Path          | Purpose                                 |
| ------ | ------------- | --------------------------------------- |
| POST   | /api/feedback | Submit user feedback for a chat message |

## Implementation References

- User routes: `src/routes/users.py`
- Project and message routes: `src/routes/projects.py`
- File routes: `src/routes/files.py`
- Chat routes: `src/routes/chats.py`
- Feedback route: `src/routes/feedback.py`

## Related Docs

- [Server README](../README.md)
- [Architecture](ARCHITECTURE.md)
- [Database Design](DATABASE.md)
- [Ingestion Pipeline](INGESTION_PIPELINE.md)
- [Retrieval Pipeline](RETRIEVAL_PIPELINE.md)
- [Generation Pipeline](GENERATION_PIPELINE.md)
