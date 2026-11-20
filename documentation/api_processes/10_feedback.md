# Process 10: Feedback

## Goal

Let users rate an assistant message (like or dislike), with an optional category and comment, so answer quality can be reviewed later.

## Endpoint

| Method | Path          | Auth         | Called By                       |
| ------ | ------------- | ------------ | ------------------------------- |
| POST   | /api/feedback | JWT required | Feedback modal on a chat message |

## Request Body

```json
{
  "message_id": "<message_uuid>",
  "rating": "like",
  "category": "helpful",
  "comment": "Great response",
  "project_id": "<project_uuid>"
}
```

| Field      | Required | Notes                                          |
| ---------- | -------- | ---------------------------------------------- |
| message_id | Yes      | The assistant message being rated              |
| rating     | Yes      | `like` or `dislike`                            |
| category   | No       | For example `inaccurate`, `irrelevant`         |
| comment    | No       | Free text                                      |
| project_id | Yes      | Used for log context; not stored on the row    |

## Success Response

```json
{
  "message": "Feedback submitted successfully",
  "data": {
    "id": "<feedback_uuid>",
    "rating": "like",
    "category": "helpful",
    "comment": "Great response",
    "message_id": "<message_uuid>",
    "clerk_id": "user_xxx",
    "created_at": "2026-04-13T10:30:00Z"
  }
}
```

## Side Effects

1. Inserts one row into `feedback`. `clerk_id` comes from the verified token, not the request body.
2. Nothing else changes. Feedback rows are deleted automatically when their message or user is deleted.

## Failure Modes

- 401 for a missing or invalid token.
- 422 for an invalid request body (Pydantic validation).
- 500 for any database error, including a `message_id` that doesn't exist. The route's own 422 for an empty insert result is caught by its `except` block and also comes back as 500.

## Notes

- `rating` is not checked against `like` / `dislike` on the server; the UI only sends those two values.
- Feedback is stored in Supabase only. It isn't sent to LangSmith yet, although each message stores its `trace_id`, so the two could be linked.
- There is no screen to review feedback yet.

## Implementation Reference

- Route: src/routes/feedback.py
- Model: src/models/index.py (`FeedbackRequest`)
- Table: supabase/migrations/20260413155104_feedback_table.sql

## Related Docs

- [Server README](../../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
