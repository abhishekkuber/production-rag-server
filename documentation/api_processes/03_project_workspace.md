# Process 3: Open a Project Workspace

## Goal

Load all data required for the project workspace shell.

## Typical Parallel Calls

| Method | Path                                | Auth                         | Purpose                         |
| ------ | ----------------------------------- | ---------------------------- | ------------------------------- |
| GET    | /api/projects/{project_id}          | JWT required                 | Load project metadata           |
| GET    | /api/projects/{project_id}/chats    | JWT required                 | Load chat list                  |
| GET    | /api/projects/{project_id}/files    | JWT required                 | Load document list and statuses |
| GET    | /api/projects/{project_id}/settings | No auth dependency currently | Load retrieval/agent settings   |

## GET /api/projects/{project_id}

- Enforces ownership via project_id + clerk_id.
- Returns one project row.

## GET /api/projects/{project_id}/chats

- Loads chats under the project for the current clerk_id.
- Returns chats sorted by created_at descending.

## GET /api/projects/{project_id}/files

- Loads project_documents for the project and current clerk_id.
- Returns files sorted by created_at descending.

## GET /api/projects/{project_id}/settings

- Returns project_settings for project_id.
- Note: this route currently does not apply auth dependency in signature.

## Failure Modes

- 404 for not found or access denied (where ownership is enforced).
- 500 for unexpected backend/database errors.

## Implementation Reference

- Project routes: server/src/routes/projects.py
- File routes: server/src/routes/files.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
