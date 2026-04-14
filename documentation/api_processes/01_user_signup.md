# Process 1: User Sign Up (Clerk Webhook -> Backend)

## Goal

Create an internal user row when Clerk emits a user-created event.

## Endpoint Contract

| Method | Path                   | Auth                                | Called By     |
| ------ | ---------------------- | ----------------------------------- | ------------- |
| POST   | /api/users/create-user | Webhook payload validation (no JWT) | Clerk webhook |

## Request Body (Expected Shape)

```json
{
  "type": "user.created",
  "data": {
    "id": "user_xxx"
  }
}
```

## Success Responses

### Created

```json
{
  "message": "User created successfully",
  "user": {
    "id": "<db_uuid>",
    "clerk_id": "user_xxx"
  }
}
```

### Already Exists

```json
{
  "message": "User already exists",
  "clerk_id": "user_xxx"
}
```

## Side Effects

1. Checks users table for existing clerk_id.
2. Inserts new users row when missing.
3. Ignores non-user.created events.

## Failure Modes

- 400 for invalid payload shape or missing user data.
- 500 for database/write failures.

## Implementation Reference

- Route: server/src/routes/users.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
