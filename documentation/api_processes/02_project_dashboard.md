# Process 2: Project Dashboard Load

## Goal

Load and manage top-level project records for the signed-in user.

## Endpoints

| Method | Path                         | Auth         | Trigger               |
| ------ | ---------------------------- | ------------ | --------------------- |
| GET    | /api/projects                | JWT required | Projects page mount   |
| POST   | /api/projects                | JWT required | Create project action |
| GET    | /api/projects/quota/messages | JWT required | Project UI render     |
| DELETE | /api/projects/{project_id}   | JWT required | Delete project action |

## GET /api/projects

### Behavior

- Filters projects by clerk_id from JWT.
- Returns project list ordered by DB default.

### Success Response

```json
{
  "message": "Projects fetched successfully",
  "data": [
    {
      "id": "<project_uuid>",
      "name": "My Project",
      "description": "Optional",
      "clerk_id": "user_xxx"
    }
  ]
}
```

## POST /api/projects

### Request Body

```json
{
  "name": "My Project",
  "description": "Optional description"
}
```

### Behavior

1. Creates projects row.
2. Creates default project_settings row.
3. Rolls back created project if settings insert fails.

### Success Response

```json
{
  "message": "Project created successfully",
  "data": {
    "id": "<project_uuid>",
    "name": "My Project",
    "description": "Optional description",
    "clerk_id": "user_xxx"
  }
}
```

## DELETE /api/projects/{project_id}

### Behavior

- Verifies project ownership with project_id + clerk_id.
- Deletes project row for that owner.

### Success Response

```json
{
  "message": "Project deleted successfully",
  "data": {
    "id": "<project_uuid>"
  }
}
```

## GET /api/projects/quota/messages

### Behavior

- Returns the current daily message quota for the authenticated user.
- Uses a fixed daily limit of 20 messages.

### Success Response

```json
{
  "message": "Message quota fetched successfully",
  "data": {
    "daily_limit": 20,
    "used": 0,
    "remaining": 20
  }
}
```

## Failure Modes

- 404 when project is missing or access is denied.
- 422 for validation/write failures.
- 500 for unexpected backend/database errors.

## Implementation Reference

- Route: server/src/routes/projects.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
