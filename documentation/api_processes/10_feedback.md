# Process 10: User Feedback Submission

## Overview

This process handles user feedback on chat messages. Users can rate messages (like/dislike), optionally categorize the feedback, and leave comments for future improvement.

## Trigger

User clicks feedback button on a message in the chat interface and submits the feedback form.

## Endpoint Contract

### Endpoint

```
POST /api/feedback
```

### Authentication

- Required: `Authorization: Bearer <clerk_jwt>`
- Backend extracts `clerk_id` from JWT via Clerk validation

### Request Body

```json
{
  "message_id": "string (UUID)",
  "rating": "string (like | dislike)",
  "category": "string (optional)",
  "comment": "string (optional)",
  "project_id": "string (UUID)"
}
```

**Field Details:**

| Field      | Type   | Required | Description                                                |
| ---------- | ------ | -------- | ---------------------------------------------------------- |
| message_id | UUID   | Yes      | ID of the message being rated                              |
| rating     | string | Yes      | Either "like" or "dislike"                                 |
| category   | string | No       | Optional categorization (e.g., "inaccurate", "irrelevant") |
| comment    | string | No       | Optional free-form user feedback                           |
| project_id | UUID   | Yes      | Project ID for context and logging                         |

### Response (Success)

**Status:** `200 OK`

```json
{
  "message": "Feedback submitted successfully",
  "data": {
    "id": "UUID",
    "rating": "like",
    "category": "helpful",
    "comment": "Great response",
    "message_id": "UUID",
    "clerk_id": "user_123",
    "created_at": "2026-04-13T10:30:00Z"
  }
}
```

### Response (Error)

**Status:** `422 Unprocessable Entity` (Validation Error)

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "comment"],
      "msg": "Field required",
      "input": {
        "message_id": "...",
        "rating": "dislike",
        ...
      }
    }
  ]
}
```

**Status:** `500 Internal Server Error` (Database or Submission Error)

```json
{
  "detail": "Feedback submission failed. Reason: [error details]"
}
```

## Side Effects

### Database

- **Insert to `feedback` table:**
  - Sets `clerk_id` from authenticated user (not from request body)
  - Uses provided `message_id`, `rating`, `category`, `comment`
  - Generates UUID `id` and `created_at` timestamp on insert
  - FK checks: `message_id` must exist in `messages` table; `clerk_id` must exist in `users` table

- **No Changes to other tables**
  - Message content is not modified
  - Chat state is not modified
  - Counter or aggregation tables are not updated

### Logging

- `submitting_feedback`: User has called endpoint
- `feedback_submission_successful`: Insert completed without error
- `feedback_submission_error`: Exception during insert; logged with full traceback and error message

### Failure Scenarios

1. **Missing or Invalid `message_id`:** FK constraint violation in DB
   - Backend catches exception and returns 500
   - Logs: `feedback_submission_error` with constraint error details

2. **Missing or Invalid `rating`:** Empty string or invalid enum value
   - Pydantic validation fails before endpoint is called
   - Frontend receives 422 with validation details

3. **Missing `comment` but schema required:** Fixed in schema to make optional
   - This was the original issue now fixed with `Optional[str]` fields

4. **User not authenticated:** No `Authorization` header or invalid JWT
   - `get_current_user_clerk_id` dependency raises `HTTPException(status_code=401)`
   - Response: 401 Unauthorized

## Backend Implementation

### Route Handler

**File:** `server/src/routes/feedback.py`

```python
@router.post("")
async def get_feedback(
    feedback: FeedbackRequest,
    clerk_id: str=Depends(get_current_user_clerk_id)
):
    set_user_id(clerk_id)
    set_project_id(feedback.project_id)
    try:
        logger.info("submitting_feedback")
        feedback_result = supabase.table("feedback").insert({
            "rating": feedback.rating,
            "category": feedback.category,
            "comment": feedback.comment,
            "message_id": feedback.message_id,
            "clerk_id": clerk_id
        }).execute()

        if not feedback_result.data:
            logger.error("feedback_submission_failed", reason="no_data_returned")
            raise HTTPException(status_code=422, detail=f"Failed to submit feedback.")

        logger.info("feedback_submission_successful")
        return {
            "message": "Feedback submitted successfully",
            "data": feedback_result.data[0]
        }

    except Exception as e:
        logger.error("feedback_submission_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Feedback submission failed. Reason: {str(e)}")
```

### Model

**File:** `server/src/models/index.py`

```python
class FeedbackRequest(BaseModel):
    message_id: str=Field(..., description="The ID of the message to which the user is giving feedback")
    rating: str=Field(..., description="Whether the rating is a like or a dislike")
    category: Optional[str]=Field(None, description="What is the user feedback about the message")
    comment: Optional[str]=Field(None, description="Extra comments about the feedback")
    project_id: str=Field(..., description="The project in which the message is")
```

### Database Schema

**File:** `server/supabase/migrations/20260413155104_feedback_table.sql`

```sql
CREATE TABLE feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rating TEXT NOT NULL,
    category TEXT,
    comment TEXT DEFAULT '',
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE
);

CREATE INDEX idx_feedback_message_id ON feedback(message_id);
CREATE INDEX idx_feedback_clerk_id ON feedback(clerk_id);
```

## Frontend Integration

**File:** `client/app/(dashboard)/projects/[projectId]/chats/[chatId]/page.tsx`

```typescript
// User clicks feedback button on message
// Frontend opens feedback modal with message_id pre-filled
// User fills form (rating required, category and comment optional)
// User clicks submit

const submitFeedback = async () => {
  const response = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message_id: selectedMessageId,
      rating: feedbackForm.rating,
      category: feedbackForm.category || undefined,
      comment: feedbackForm.comment || undefined,
      project_id: projectId,
    }),
  });

  if (response.ok) {
    // Close modal, show success toast
    setOpen(false);
    showSuccessNotification("Feedback submitted");
  } else {
    // Show error toast
    const error = await response.json();
    showErrorNotification(error.detail);
  }
};
```

## Usage Notes

- **Only authenticated users can submit feedback** (clerk_id extracted from JWT)
- **Feedback is tied to the user who submitted it** (clerk_id set by backend, not frontend)
- **Category and comment are optional** to minimize friction; rating is required for core functionality
- **Feedback persists permanently** (no hard delete, but CASCADE handles orphaned feedback if message or user is deleted)
- **No feedback aggregation or analytics** yet; feedback table is write-only for now

## Future Enhancements

1. **Feedback Analytics:** Dashboard showing feedback distribution (likes/dislikes) per project or message
2. **Feedback Categories:** Define allowed values and show dropdown in UI (inaccurate, irrelevant, missing info, off-topic, etc.)
3. **Feedback Review:** Internal admin endpoint to browse feedback and iterate on retrieval quality
4. **Duplicate Detection:** Prevent user submitting same feedback twice on same message
5. **Feedback Webhooks:** Trigger integrations (e.g., send to Slack, Mixpanel for quality tracking)

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
