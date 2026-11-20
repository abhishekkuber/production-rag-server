# Known Limitations

What I know is missing or weak, and what I would change next. Most of it surfaced while building the [evaluation](EVALUATION.md).

## Security

| Issue | Where | Fix I'd make |
|---|---|---|
| The streaming chat route takes `clerk_id` from the query string instead of verifying the JWT | `POST /api/projects/{id}/chats/{id}/messages/stream` | The client already sends a `token` in the query string and makes the request with `fetch`, so the route can verify it (or take an `Authorization` header) like the other routes do |
| `GET /api/projects/{id}/settings` has no auth check | `src/routes/projects.py` | Add the same ownership check as `PUT` |
| The Clerk sign-up webhook doesn't verify Clerk's signature, so anyone can create a user row | `POST /api/users/create-user` | Verify the Svix signature headers |
| CORS allows every origin (`*`) | `src/server.py` | Allow only the front-end domain |
| The backend uses the Supabase service-role key, which bypasses row-level security | everywhere | Ownership is checked in each query today. Row-level security policies would add a second layer. |

## Retrieval and generation

- **Image chunks retrieve poorly.** For questions about figures, the right chunk is in the model's context only 76% of the time, against 91% for text-only questions. The summary written for a figure doesn't describe what it shows. ([Evaluation](EVALUATION.md#baseline))
- **Images make prompts expensive.** Every image in the retrieved chunks is sent at high detail and makes up 87% of input tokens, including tiny slivers cut from equations. Filtering small images and using `detail: "low"` would cut input cost by about three quarters. ([Evaluation](EVALUATION.md#cost-images-dominate-the-prompt))
- **Rerank failures are silent.** If Cohere fails, retrieval falls back to search order and only a log line records it. The eval tracks this per question, but the app doesn't show it.
- **Two generation calls per answer.** The `rag_search` answer is rewritten by the agent, which doubles cost and latency and can drop the refusal sentence.
- **Guardrail false positives.** The input guardrail blocks anything it thinks contains personal data, which can catch innocent questions that name people. It also adds one LLM call to every message.
- **Models are hard-coded in the routes** (`gpt-4o` for streaming, `gpt-4o-mini` elsewhere), and `project_settings.embedding_model` is stored but not used.

## Ingestion

- **Chunk sizes are hard-coded** (3,000 / 2,400 / 500 characters in `chunking.py`), so chunking can't be tuned per project.
- **A failed ingestion has no `failed` status.** The error is logged, but the document stays at the last step it reached (for example `summarising`), so the UI keeps showing it as in progress.
- **Page numbers can be wrong.** If the parser gives no page, the page is set to `chunk index + 1`. A chunk that spans pages stores only one page.
- **Database writes are row by row.** Each chunk is inserted separately and summarisation makes two round trips per chunk. Batching would speed up large documents.

## Engineering

- **No automated tests or CI.** All the app's clients (Supabase, S3, Redis, OpenAI, Cohere) are created at import time and the config requires every env var, so tests need env stubs or lazily created clients first.
- **No `.env.example`.** The variables are listed in the [README](../README.md#run-locally).
- **The front end build ignores TypeScript errors** (`typescript.ignoreBuildErrors: true`).
- **Python versions differ:** 3.11 locally, 3.13 in the Docker image.
- **Manual releases** and a hand-edited CloudFront origin. See [Architecture](ARCHITECTURE.md#deployment).

## Related docs

- [Architecture](ARCHITECTURE.md)
- [Evaluation](EVALUATION.md)
- [Server README](../README.md)
