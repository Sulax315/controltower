# n8n Execution Integration

Control Tower now emits a normalized downstream execution event whenever a review run is approved or auto-approved through the existing control plane.

Recommended flow:

1. Control Tower records approval through the review plane.
2. Control Tower selects a deterministic execution pack.
3. Control Tower emits the normalized `codex_run.approved` event through the configured provider.
4. n8n receives the event by webhook or by watching the durable file queue.
5. n8n branches on `pack_type` and runs the corresponding automation.
6. n8n POSTs the result back to `POST /api/execution/results`.
7. Control Tower records closeout, updates the review UI, and writes continuity history.

## Retry And Dead-Letter Model

- Dispatch retries are bounded by `CODEX_EXECUTION_MAX_ATTEMPTS`, default `3`.
- Backoff uses `CODEX_EXECUTION_RETRY_BACKOFF_MS` and `CODEX_EXECUTION_RETRY_BACKOFF_MULTIPLIER`.
- File and stub providers retry only on real local IO failures.
- Webhook provider retries on timeout, network failure, and HTTP `5xx`.
- Malformed config and permanent HTTP `4xx` failures do not retry automatically.
- Exhausted failures write one durable dead-letter payload into `CODEX_EXECUTION_DEAD_LETTER_DIR`.
- Dead-letter payloads include the original approved payload, failure metadata, and full attempt history.
- Replay stays operator-visible through `execution-dispatch-retry --run-id <RUN_ID>`.

Dead-letter operator command:

```powershell
python .\run_controltower.py execution-dead-letter-list
```

## Event Contract

Current version: `v1`

Stable top-level fields:

- `event_type`
- `event_version`
- `event_id`
- `trigger_id`
- `run_id`
- `workspace`
- `title`
- `risk_level`
- `decision_mode`
- `decision_reasons`
- `approved_at`
- `approved_by`
- `approved_next_prompt`
- `review_url`
- `artifacts`
- `source`
- `pack_hint`
- `correlation_id`
- `request_id`

Control Tower also includes:

- `pack_id`
- `pack_type`
- `pack`
- `review`

Example emitted payload:

```json
{
  "event_type": "codex_run.approved",
  "event_version": "v1",
  "event_id": "event_v1_review_2026-03-30T17-36-32Z",
  "trigger_id": "trigger_review_2026-03-30T17-36-32Z",
  "run_id": "review_2026-03-30T17-36-32Z",
  "workspace": "controltower",
  "title": "Control Tower Release Readiness Passed",
  "risk_level": "medium",
  "decision_mode": "manual_review",
  "decision_reasons": [
    "Release-readiness handling defaults to manual review."
  ],
  "approved_at": "2026-03-30T17:40:00Z",
  "approved_by": "operator",
  "approved_next_prompt": "Checkpoint fix, push to repo, and run full production validation.",
  "review_url": "http://127.0.0.1:8787/reviews/review_2026-03-30T17-36-32Z",
  "artifacts": [
    {
      "label": "release_readiness_2026-03-30T17-36-32Z.json",
      "file_name": "release_readiness_2026-03-30T17-36-32Z.json",
      "path": "C:/Dev/ControlTower/.controltower_runtime/orchestration/reviews/review_2026-03-30T17-36-32Z/artifacts/release_readiness_2026-03-30T17-36-32Z.json"
    }
  ],
  "source": "controltower_orchestration",
  "pack_hint": "release_readiness_pack",
  "correlation_id": "corr-123",
  "request_id": "req-123",
  "pack_id": "pack_release_readiness_v1",
  "pack_type": "release_readiness_pack",
  "pack": {
    "pack_id": "pack_release_readiness_v1",
    "pack_type": "release_readiness_pack",
    "selection_reason": "Matched keywords release readiness, production validation across workspace/title/summary/prompt.",
    "downstream_target": "release_readiness_orchestrator"
  }
}
```

## Providers

### File queue provider

- Writes one JSON file per event into `CODEX_EXECUTION_FILE_DIR`
- Uses a deterministic file name based on `event_id`
- Safe for n8n file-watch flows and exactly-once replays

Recommended n8n shape:

1. Trigger on new file in the execution queue directory
2. Read JSON
3. Switch on `pack_type`
4. Run downstream steps
5. POST result back to Control Tower

### Webhook provider

- Sends a JSON `POST` to `CODEX_EXECUTION_WEBHOOK_URL`
- Uses a bounded timeout from `CODEX_EXECUTION_WEBHOOK_TIMEOUT_MS`
- Includes idempotency and routing headers

Expected headers:

- `Content-Type: application/json`
- `Idempotency-Key: <event_id>`
- `X-ControlTower-Run-ID: <run_id>`
- `X-ControlTower-Trigger-ID: <trigger_id>`
- `X-ControlTower-Event-ID: <event_id>`
- `X-ControlTower-Event-Version: <event_version>`
- `X-ControlTower-Pack-ID: <pack_id>`
- `X-ControlTower-Pack-Type: <pack_type>`

### Stub provider

- Records the intended downstream execution into `orchestration/stub_records/`
- Useful for local demos, Cursor walkthroughs, and safe dry runs

## Result Ingest

Endpoint:

```text
POST /api/execution/results
```

Example payload:

```json
{
  "event_id": "event_v1_review_2026-03-30T17-36-32Z",
  "run_id": "review_2026-03-30T17-36-32Z",
  "pack_id": "pack_release_readiness_v1",
  "status": "succeeded",
  "summary": "n8n completed the release-readiness pack and published the closeout bundle.",
  "output_artifacts": [
    {
      "label": "closeout",
      "path": "C:/tmp/closeout.md",
      "content_type": "text/markdown"
    }
  ],
  "started_at": "2026-03-30T17:40:00Z",
  "completed_at": "2026-03-30T17:45:00Z",
  "external_reference": "n8n-exec-42",
  "logs_excerpt": "All readiness checks passed."
}
```

Validation rules:

- `event_id`, `run_id`, `pack_id`, and `status` are required
- `status` must be `succeeded`, `failed`, or `partial`
- `event_id` must match the originating review run
- `pack_id` must match the selected pack for that run
- `external_reference` should be your downstream execution id when you have one
- `output_artifacts` should include concrete file paths or external URLs for operator follow-up

## Pack Validation And Guard Rules

- `deploy_pack`: requires a clear workspace target and non-empty approved prompt
- `smoke_pack`: requires run linkage through `run_id` plus source operation or artifacts
- `release_readiness_pack`: requires workspace or artifact context
- `report_pack`: requires explicit publish/report/output intent
- `continuity_pack`: must remain non-destructive
- `noop_pack`: stays explicit and operator-visible

Guard rules:

- `CODEX_EXECUTION_GUARDED_PACKS` defaults to `deploy_pack,release_readiness_pack`
- In prod, guarded packs are blocked unless `CODEX_EXECUTION_ALLOW_GUARDED_IN_PROD=true`
- In dev/local mode, guarded packs remain visible as guarded but still use the current demo dispatch path

## Closeout Artifacts

Control Tower writes predictable closeout artifacts per review run:

- `orchestration/reviews/<run_id>/closeout/closeout_latest.json`
- `orchestration/reviews/<run_id>/closeout/closeout_latest.md`

Inspection commands:

```powershell
python .\run_controltower.py execution-event-show --run-id <RUN_ID>
python .\run_controltower.py execution-closeout-show --run-id <RUN_ID>
```

The closeout payload includes:

- run, event, trigger, pack, and provider identifiers
- dispatch attempts and final dispatch status
- downstream result status and external reference
- output artifacts
- closeout summary
- timestamps
- dispatch and downstream errors

## Idempotency And Failure Handling

- `event_id` is deterministic per review run and event version
- `trigger_id` is deterministic per review run
- File queue writes reuse the same `event_id.json` path
- Webhook requests send `Idempotency-Key: <event_id>`
- Provider attempts are persisted on the review run
- Exhausted provider failures write a dead-letter payload into `CODEX_EXECUTION_DEAD_LETTER_DIR`
- Successful emissions are not duplicated
- Failed emissions remain visible in the review UI, run list, closeout artifacts, and continuity markdown

## Pack Branching Hints

Branch on `pack_type`:

- `deploy_pack`
- `smoke_pack`
- `release_readiness_pack`
- `report_pack`
- `continuity_pack`
- `noop_pack`

`noop_pack` is intentional. It preserves operator visibility when Control Tower does not have a safe deterministic mapping for autonomous follow-on work.

## Safe Replay

Recommended replay sequence for a dead-lettered event:

1. Inspect the dead-letter payload and root cause.
2. Fix the provider config or downstream endpoint.
3. Verify the guarded-pack policy is intentionally satisfied if the pack is guarded.
4. Run `execution-dispatch-retry --run-id <RUN_ID>`.
5. Confirm the review detail or `execution-closeout-show` output moves from `dead_lettered` to a healthy dispatch state.
