# API

OpenAPI is the contract (`T gen-api` regenerates the TypeScript client). Errors are always
`{"code": "<machine code>", "message": "<plain language>"}`; codes: `invalid_input` (422), `not_found` (404),
`path_not_allowed` (403), `job_state` (409).

## Implemented (Phase 1)
- `GET /api/system/health`
- `POST/GET /api/projects`, `GET/PATCH/DELETE /api/projects/{id}`
- `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`
- `GET /api/jobs/events` (SSE). Query: `job_id` (filter), `follow=false` (send stored events, then close).
  Frames carry `id:` = `job_events.id`; reconnect with `Last-Event-ID` to resume without gaps.

Job creation endpoints (`POST .../process`) arrive with the first real pipeline stage (Phase 3).

## Jobs and the worker
`cinemind serve` starts the API and one worker process (`--no-worker` to skip; `cinemind worker` runs it alone).
The worker polls `jobs`, runs the chain's stages in order, caches each stage, and writes events.
On startup it re-queues any job left `running` (assumes exactly one worker); finished stages come back from the
cache, so a killed job resumes at the stage that was interrupted (that stage restarts from its beginning).
Cancel is cooperative: stages call `ctx.check_cancelled()` and the runner checks between stages.
Retry keeps succeeded stages.
