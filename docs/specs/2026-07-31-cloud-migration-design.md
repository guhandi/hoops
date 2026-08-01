# Cloud migration — phone → Modal → R2 → email

**Date:** 2026-07-31 · **Status:** approved for implementation
**Supersedes:** the iCloud/launchd ingestion described in `architecture.md` as the *primary* path (local mode remains documented fallback).

## Problem

Two sessions in two days were half-processed and never emailed. Root cause: the Mac has ~3GB free disk, so macOS evicts iCloud file content aggressively — once mid-pipeline (the archive step died under a vanishing file) and then perpetually (a 5-minute eviction-vs-poll race kept the recording dataless). The local pipeline's failure modes are all workarounds for consumer infrastructure: sync timing, launchd, TCC grants, dataless stubs, stability gates. I want the structural fix, free if possible, on infrastructure that repeats for future automations and teaches transferable skills (object storage, async workers, data-lake discipline), with a future path to ML over accumulated data.

## Decisions (owner, 2026-07-31)

1. **Full cloud pipeline** — the Mac leaves the data path entirely. Bonus: the phone POSTs audio directly, so reports arrive ~2 minutes after recording (no iCloud sync wait).
2. **Stack: standard pattern, pragmatic parts** —
   - **Modal** for compute (verified: free Starter, $30/mo credits, no card; Python-native; ~one 60s CPU run/day ≈ $0). Also the GPU on-ramp for future model work.
   - **Cloudflare R2** for storage (10GB free ≈ 5 years of sessions; S3 API via boto3 — the transferable skill). *Task-1 verification: whether R2 activation needs a card; fallbacks Backblaze B2 or existing Supabase storage, same S3-compatible code.*
   - **Gmail SMTP** delivery, unchanged.
   - Rejected: Cloud Run (billing card now required), Vercel Python functions (4.5MB body limit fails on forgot-to-stop recordings), full AWS (IAM friction disproportionate; boto3-against-R2 teaches the same API).
3. **Compute stateless, bucket is source of truth.** Raw audio and every session artifact live in R2 under the existing `sessions/YYYY/MM/<sid>/` layout — a miniature data lake, ML-ready by construction.
4. **Golden-data acceptance gate required**: the migration is done only when the deployed cloud pipeline reproduces the local pipeline's committed baselines on our real fixtures and a real archived session.

## Architecture

```
[iPhone]  Shortcut → POST https://<modal-endpoint>/upload
          multipart hoops__<yyyyMMdd-HHmmss>.m4a + X-Hoops-Key header → fast ack

[Modal: cloud/modal_app.py]
  endpoint  auth (hmac.compare_digest) · filename vs session._PREFIX_RE · ≤64MB
            → PUT raw/<name> in R2 → sid dedupe → processor.spawn → ack
  processor retries=3 · download raw → scratch · process_file(..., email=True,
            archive="move") with scratch-rooted Config · upload session dir
            (or needs_review/rejected outcome) to R2 · delete raw/<name>
            · each failed attempt → alert email + Modal dashboard logs
  secrets   modal.Secret "hoops-secrets" (OpenAI, Anthropic, Gmail, upload key,
            R2 keys) — never committed, never printed

[R2 "hoops-data"]  raw/ (transient) · sessions/YYYY/MM/<sid>/ · needs_review/ · rejected/
```

- `cloud/store.py` isolates all S3-compatible access (put/get/list/delete against a configurable endpoint) — the reusable piece for future capture tools.
- `config.cloud.yaml` clones `config.yaml` with scratch-space roots (`load_config` already takes a path).
- `pull_sessions` local entrypoint syncs the bucket's sessions down for replay/score/build_db — the Mac keeps the whole dev loop.
- The pipeline core (`process_file` and below: whisper → isolation-gated parse → invariants → stats → interactive report → session-zip email) is unchanged.

## Golden-data acceptance gate

Baseline = the manifest's committed machine columns (`got_calls`, local run 2026-07-30) and archived real-session outputs.

1. POST through the real deployed endpoint: F01 (happy path), F02 (chatty trap), F04 (quiet), R01 (real unscripted), and archived `hoops__20260730-125100.m4a` (20 shots) — under fresh sids.
2. Each produces: email with session zip, artifacts in R2, successful `pull_sessions`.
3. Cloud canonical call sequences must match the local baselines exactly; any mismatch is investigated (documented as whisper variance only if reproducible locally).
4. F02 shows zero phantom calls (trap parity). The 20-shot re-run reproduces 20 calls, 10/10, same I1/I6 flags.
5. Test sessions deleted from R2/local afterward.

## Error handling

- Endpoint: wrong key → 401 (nothing written); malformed filename → 4xx with clear message; duplicate sid → 200 `{"status":"duplicate"}` (idempotent re-taps); oversize → 413.
- Processor: Modal retries ×3; each failed attempt fires a best-effort alert email — up to 4 for a permanent failure — with the error; raw file remains in `raw/` for manual replay; nothing is silently swallowed (Modal logs every run). (amended 2026-08-01: alert is per-attempt)
- Rollback: `launchctl load` the kept plist + re-point the Shortcut at iCloud — both ingest paths coexist in the repo.

## Testing

- Unit (no network): endpoint app factory via FastAPI TestClient with a stubbed store — auth, validation, dedupe, oversize; `cloud/store.py` against moto or an interface stub. Processor logic is `process_file`, already covered by the existing suite.
- Live: deploy smoke (one fixture through the real endpoint), then the golden-data acceptance gate above (~$0.10 of whisper).
- Existing gates unchanged: `uv run pytest`, replay no-op discipline, `hoops score`.

## Skills inventory (why built this way)

Object storage + S3 API and data-lake layout (boto3, identical against AWS later) · stateless async workers with spawn/retry/idempotency · secrets management · deploy-as-code (`modal deploy` of one reviewable file) · the four-box ingestion→processing→storage→delivery pattern that generalizes to every future capture automation — and, already in the repo, the eval-engineering discipline (labeled golden data + gates) that this migration's acceptance gate reuses.
