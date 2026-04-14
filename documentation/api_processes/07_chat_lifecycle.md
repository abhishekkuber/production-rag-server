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

1. Save user message.
2. Resolve agent_type from settings.
3. Load chat history.
4. Stream agent events via astream_events.
5. Accumulate full final response and citations.
6. Save assistant message.
7. Emit done event.

## 7E: Delete Chat

- Deletes chat by chat_id + clerk_id.
- Returns deleted row payload.

## Failure Modes

- 404 for not found/access denied resources.
- 422 for persistence failures.
- 500 for unexpected backend errors.
- Streaming path emits error event when failures occur.

## Implementation Reference

- Chat routes: server/src/routes/chats.py
- Message routes: server/src/routes/projects.py

## Related Docs

- [Server README](../README.md)
- [API Endpoints](../API_ENDPOINTS.md)
