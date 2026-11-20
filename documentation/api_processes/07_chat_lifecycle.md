# Process 7: Chat Lifecycle

## Goal

Create chats, retrieve message history, send user messages to agents, and persist assistant responses with citations.

## Endpoints Overview

| Method | Path                                                                     | Auth                                        | Purpose              |
| ------ | ------------------------------------------------------------------------ | ------------------------------------------- | -------------------- |
| POST   | /api/chats                                                               | JWT required                                | Create chat          |
| GET    | /api/chats/{chat_id}                                                     | JWT required                                | Load chat + messages |
| DELETE | /api/chats/{chat_id}                                                     | JWT required                                | Delete chat          |
| POST   | /api/projects/{project_id}/chats/{chat_id}/messages/stream?clerk_id=<id> | Query clerk_id (no JWT dependency in route) | Streaming SSE path   |
| POST   | /api/projects/{project_id}/chats/{chat_id}/messages                      | JWT required                                | Non-streaming path   |

## 7A: Create Chat

### Request Body

```json
{
  "title": "New chat",
  "project_id": "<project_uuid>"
}
```

### Success Response

```json
{
  "message": "Chat created successfully",
  "data": {
    "id": "<chat_uuid>",
    "project_id": "<project_uuid>",
    "title": "New chat",
    "clerk_id": "user_xxx"
  }
}
```

## 7B: Get Chat With Messages

- Loads chat by chat_id and clerk_id.
- Loads messages for that chat ordered by created_at ascending.

## 7C: Send Message (Streaming SSE)

| Method | Path                                                                     |
| ------ | ------------------------------------------------------------------------ |
| POST   | /api/projects/{project_id}/chats/{chat_id}/messages/stream?clerk_id=<id> |

### Request Body

```json
{
  "content": "What does my document say about black holes?"
}
```

### SSE Events

- status: phase progress (thinking/searching/generating)
- token: incremental response content
- done: final persisted userMessage + aiMessage payload
- error: terminal error event

### Backend Sequence

1. Check the daily message quota (20 per day); return 429 when it is used up.
2. Save user message.
3. Resolve agent_type from settings.
4. Load chat history (last 10 messages).
5. Stream agent events via astream_events. The agent model on this route is `gpt-4o`.
6. Accumulate full final response and citations.
7. Save assistant message with its LangSmith trace id.
8. Emit done event.

## 7D: Send Message (Non-Streaming)

| Method | Path                                                |
| ------ | --------------------------------------------------- |
| POST   | /api/projects/{project_id}/chats/{chat_id}/messages |

Same request body and the same steps as 7C, but it verifies the JWT, runs the agent with `gpt-4o-mini`, and returns the saved user and assistant messages in one JSON response. The UI doesn't use it.

## 7E: Delete Chat

- Deletes chat by chat_id + clerk_id.
- Returns deleted row payload.

## Failure Modes

- 404 for not found/access denied resources.
- 422 for persistence failures.
- 500 for unexpected backend errors.
- Streaming path emits error event when failures occur.

## Implementation Reference

- Chat routes: src/routes/chats.py
- Message routes: src/routes/projects.py

## Related Docs

- [Server README](../../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
