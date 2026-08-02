# Deploy your own

Stand up your own instance of the pipeline: your phone, your Modal endpoint, your R2 bucket, your inbox. Nothing here talks to anyone else's account — every credential you create belongs to you, and this repo never sees it. Total time: about 15 minutes, entirely on free tiers.

## 1. What you're deploying

```
[your iPhone]  →  [your Modal endpoint]  →  [your R2 bucket]  →  [your email]
   Shortcut          cloud/modal_app.py       hoops-data          report.html
```

You tap a Shortcut, it POSTs a recording to a Modal endpoint you deploy, the endpoint stashes the raw audio in an R2 bucket you own and spawns a processor that transcribes/parses/validates/renders it, and the finished report lands in your inbox a couple minutes later. Full detail on how the pipeline itself works — module map, failure handling, the parser's isolation gate — is in [architecture.md](architecture.md); this guide only covers getting an instance of it running.

## 2. Accounts you need (~10 min)

| Service | What you need | Where |
|---|---|---|
| OpenAI | API key (whisper-1 transcription) | platform.openai.com |
| Anthropic | API key (repair + narrative) | console.anthropic.com |
| Modal | account, free Starter plan — $30/mo credits, no card required | modal.com |
| Cloudflare R2 | account, free tier — 10GB storage | dash.cloudflare.com |
| Gmail | app password (requires 2-Step Verification) — paste WITHOUT the spaces Google displays | Google Account → Security → App passwords |

For R2, create a bucket named `hoops-data` (or any name — you'll set `R2_BUCKET` to match). Then mint a token: **R2 Object Storage → Overview → Account Details → API Tokens → Manage → Create Account API token**, permission **Object Read & Write**, scoped to your bucket. The endpoint, access key ID, and secret access key are shown once — copy all three before closing the dialog.

## 3. Configure (~3 min)

```bash
git clone https://github.com/guhandi/hoops && cd hoops
uv sync --extra cloud
cp .env.example .env
```

Open `.env` and fill in every variable: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, the three `R2_*` values from step 2, and `R2_BUCKET`. Generate the upload secret yourself:

```bash
openssl rand -hex 24    # → HOOPS_UPLOAD_KEY
```

Leave `HOOPS_ENDPOINT` empty for now — you don't have it until step 4 deploys. Also edit the `timezone` line in both `config.yaml` and `cloud/config.cloud.yaml` — the two must match, since the cloud container runs from a scratch-space clone of the local config.

## 4. Deploy (~2 min)

```bash
uv run modal setup        # one-time browser auth
set -a; source .env; set +a
uv run modal secret create hoops-secrets \
  OPENAI_API_KEY="$OPENAI_API_KEY" ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  GMAIL_ADDRESS="$GMAIL_ADDRESS" GMAIL_APP_PASSWORD="$GMAIL_APP_PASSWORD" \
  HOOPS_UPLOAD_KEY="$HOOPS_UPLOAD_KEY" R2_ENDPOINT="$R2_ENDPOINT" \
  R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  R2_BUCKET="$R2_BUCKET"
uv run modal deploy cloud/modal_app.py   # prints your endpoint URL — put it in .env as HOOPS_ENDPOINT
```

`modal deploy` prints an endpoint URL of the form `https://<you>--hoops-web.modal.run`. Paste it into `.env` as `HOOPS_ENDPOINT` — nothing else in the repo needs to know it; it only lives in your local `.env` and, next, in your Shortcut.

## 5. Smoke test

```bash
set -a; source .env; set +a   # re-load now that HOOPS_ENDPOINT is filled in
curl -sS -X POST "$HOOPS_ENDPOINT/upload?name=hoops__20990101-000001.m4a" \
  -H "X-Hoops-Key: $HOOPS_UPLOAD_KEY" -H "Content-Type: application/octet-stream" \
  --data-binary @fixtures/F01_NormalSwishBrick.m4a
```

Expect `{"status":"processing",...}` back immediately, and an email inside about 2 minutes. That email should arrive clean, with no ⚠️ flag — F01 ends on three straight makes, so invariants pass. (If it arrives flagged, that's whisper transcription variance on re-transcription — not a broken deploy.)

## 6. Your phone

Wire the Apple Shortcut to your new endpoint: [shortcut-setup.md](shortcut-setup.md) (cloud upload section) — three actions, five minutes, one Home Screen button.

## 7. What it costs

| Item | Cost |
|---|---|
| Modal | $0 (covered by free Starter credits) |
| R2 | $0 (free tier ≈ 5 years of daily sessions at this data volume) |
| OpenAI + Anthropic APIs | ≈ $0.01 per session |

Daily use, one session a day: roughly $0.30/month, all of it API usage — infrastructure costs nothing.

## 8. When something breaks

- **401** — `X-Hoops-Key` header doesn't match the `HOOPS_UPLOAD_KEY` in your Modal secret. Check the Shortcut's header value against `.env`.
- **400** — filename doesn't match the `hoops__YYYYMMDD-HHMMSS.m4a` contract. Check the Shortcut's Format Date step.
- **No email** — check the Modal dashboard logs; every run is logged there, a failing attempt alerts you by email on its own, and the raw file stays in `raw/` in your R2 bucket for replay regardless of outcome.
- **No email but Modal logs look clean** — confirm `GMAIL_ADDRESS` is in your `hoops-secrets` (without it the pipeline mails a placeholder address and Gmail silently drops it).
- **Dev loop** — to pull processed sessions down to your Mac for `replay`/`score`/inspection:
  ```bash
  set -a; source .env; set +a
  uv run modal run cloud/modal_app.py::pull_sessions
  ```
