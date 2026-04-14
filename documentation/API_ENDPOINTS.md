# API Endpoints (by Process)

API overview for the server.

## Global Notes

- Most protected routes use `Depends(get_current_user_clerk_id)`.
- Expected request header: `Authorization: Bearer <clerk_jwt>`
- Backend behavior: Clerk verifies the JWT and backend extracts `sub` as `clerk_id`
- Exceptions:
  - `POST /api/users/create-user` is webhook-driven (no user JWT)
  - `GET /api/projects/{project_id}/settings` currently has no auth dependency in route signature (project settings is not sensitive data)
  - `POST /api/projects/{project_id}/chats/{chat_id}/messages/stream` currently accepts `clerk_id` as query param

## Process 1: User Sign Up

Create an internal user row when Clerk emits a `user.created` event.

| Method | Path                   | Purpose                   |
| ------ | ---------------------- | ------------------------- |
| POST   | /api/users/create-user | Create internal users row |

## Process 2: Project Dashboard Load

Load and manage top-level project records for the signed-in user.

| Method | Path                         | Trigger               | Purpose                                       |
| ------ | ---------------------------- | --------------------- | --------------------------------------------- |
| GET    | /api/projects                | Projects page mount   | Load all projects for current user            |
| POST   | /api/projects                | Create project action | Create project and default `project_settings` |
| GET    | /api/projects/quota/messages | Project UI render     | Load the current daily message quota          |
| DELETE | /api/projects/{project_id}   | Delete project action | Delete project and related DB data            |

## Process 3: Open a Project Workspace

These calls are typically loaded in parallel.

| Method | Path                                | Purpose                                         |
| ------ | ----------------------------------- | ----------------------------------------------- |
| GET    | /api/projects/{project_id}          | Project metadata                                |
| GET    | /api/projects/{project_id}/chats    | Conversation list for sidebar                   |
| GET    | /api/projects/{project_id}/files    | Knowledge-base file list plus processing status |
| GET    | /api/projects/{project_id}/settings | Retrieval and agent settings                    |

## Process 4: Ingest a File

File ingestion uses presigned S3 uploads and Celery so the API stays responsive while heavy processing runs in the background.

| Method | Path                                       | Purpose                                                                              |
| ------ | ------------------------------------------ | ------------------------------------------------------------------------------------ |
| POST   | /api/projects/{project_id}/file/upload-url | Generate presigned S3 URL and create `project_documents` row with `uploading` status |
| PUT    | <presigned_s3_url>                         | Upload file bytes directly from client to S3                                         |
| POST   | /api/projects/{project_id}/file/confirm    | Mark as `queued`, enqueue `perform_rag_ingestion(document_id)`, persist `task_id`    |

## Process 5: Ingest a URL

URL ingestion skips S3 and queues work immediately.

| Method | Path                            | Purpose                                                                                   |
| ------ | ------------------------------- | ----------------------------------------------------------------------------------------- |
| POST   | /api/projects/{project_id}/urls | Validate URL, create queued `project_documents` row, enqueue ingestion, persist `task_id` |

## Process 6: Short Polling

The frontend uses short polling while any document is still processing.

| Method | Path                                              | Trigger                                     | Purpose                                                   |
| ------ | ------------------------------------------------- | ------------------------------------------- | --------------------------------------------------------- |
| GET    | /api/projects/{project_id}/files                  | About every 3s while status is non-terminal | Refresh status from `project_documents.processing_status` |
| GET    | /api/projects/{project_id}/files/{file_id}/chunks | Document details view                       | Inspect generated chunks                                  |

## Process 7: Chat Lifecycle

Create chats, retrieve message history, and delete chats.

| Method | Path                 | Purpose                                |
| ------ | -------------------- | -------------------------------------- |
| POST   | /api/chats           | Create chat under a project            |
| GET    | /api/chats/{chat_id} | Load chat with ordered message history |
| DELETE | /api/chats/{chat_id} | Delete chat                            |

## Process 8: Streaming Message Send

Send a message to the agent and stream the response back to the client as SSE events.

| Method | Path                                                                     | Purpose                                                     |
| ------ | ------------------------------------------------------------------------ | ----------------------------------------------------------- |
| POST   | /api/projects/{project_id}/chats/{chat_id}/messages/stream?clerk_id=<id> | Stream agent output and persist the final assistant message |

## Process 9: Feedback Submission

Users can rate assistant messages and leave optional comments for future improvement.

| Method | Path          | Purpose                                 |
| ------ | ------------- | --------------------------------------- |
| POST   | /api/feedback | Submit user feedback for a chat message |

## Process 10: Retrieval and Agent Settings

Read and update project-level retrieval and generation behavior.

| Method | Path                                | Purpose                                   |
| ------ | ----------------------------------- | ----------------------------------------- |
| GET    | /api/projects/{project_id}/settings | Read current retrieval and agent settings |
| PUT    | /api/projects/{project_id}/settings | Persist strategy and agent tuning updates |

## Process 11: Document Cleanup

Delete a project document and remove the backing S3 object when applicable.

| Method | Path                                       | Purpose                                                      |
| ------ | ------------------------------------------ | ------------------------------------------------------------ |
| DELETE | /api/projects/{project_id}/files/{file_id} | Delete document row and delete S3 object when source is file |

## Implementation References

- User routes: `server/src/routes/users.py`
- Project routes: `server/src/routes/projects.py`
- File routes: `server/src/routes/files.py`
- Chat routes: `server/src/routes/chats.py`
- Feedback route: `server/src/routes/feedback.py`

## Detailed Process Docs

- [01_user_signup.md](api_processes/01_user_signup.md)
- [02_project_dashboard.md](api_processes/02_project_dashboard.md)
- [03_project_workspace.md](api_processes/03_project_workspace.md)
- [04_file_ingestion.md](api_processes/04_file_ingestion.md)
- [05_url_ingestion.md](api_processes/05_url_ingestion.md)
- [06_processing_polling.md](api_processes/06_processing_polling.md)
- [07_chat_lifecycle.md](api_processes/07_chat_lifecycle.md)
- [08_settings_tuning.md](api_processes/08_settings_tuning.md)
- [09_document_cleanup.md](api_processes/09_document_cleanup.md)
- [10_feedback.md](api_processes/10_feedback.md)

## Related Docs

- [Server README](../README.md)
- [Database Design](DATABASE.md)
- [Ingestion Pipeline](INGESTION_PIPELINE.md)
- [Retrieval Pipeline](RETRIEVAL_PIPELINE.md)
- [Generation Pipeline](GENERATION_PIPELINE.md)
