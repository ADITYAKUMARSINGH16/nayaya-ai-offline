# n8n Automation Workflows

Six workflows that turn n8n into the integration / human-in-the-loop layer
around the FastAPI core. All of them ship **inactive** — activate after you
wire the placeholder outbound nodes (Email/Slack/Telegram).

| File | Trigger | What it does |
|------|---------|--------------|
| **`case-notify-fanout.json`** | Webhook `POST /webhook/case-notify` (backend calls this on every verdict) | Fans out the verdict to Email + Slack + Telegram + WhatsApp branches in parallel. **Telegram is wired live** (uses `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — same vars `fir-human-approval` already uses); Email / Slack / WhatsApp remain placeholder noOps until you wire the n8n credentials for those channels. |
| **`fir-human-approval.json`** | Webhook `POST /webhook/fir-approve` (backend calls when `N8N_FIR_APPROVAL=true`) | `Wait` node pauses the flow; reviewer clicks Approve/Reject; on resume the workflow calls the backend back to set the FIR's status. |
| **`eval-cron.json`** | Schedule (daily 09:00 IST) | Runs `python -m eval.runner` inside the backend container *and* fetches `/api/eval/latest` for a Slack/Email digest. |
| **`graph-rebuild-cron.json`** | Schedule (weekly Sunday 03:00 IST) | POSTs `/api/admin/rebuild-graph` (admin JWT) so newly-ingested statutes show up in LegalGraph-Lite. |
| **`agent-petitioner.json`** | Webhook `POST /webhook/agent/petitioner` | Self-contained "Petitioner agent as a sub-workflow" demo — shows how a role *could* run in n8n, callable via Execute Workflow. |
| **`error-handler.json`** | Error Trigger | Attached to all the above (`settings.errorWorkflow = "error-handler"`). Catches failures, formats them, alerts the admin. |

## Importing

1. `docker compose up -d n8n` and open <http://localhost:5678>.
2. On first launch, create the owner account.
3. **Workflows → Import from File** → pick a `.json` here. Repeat for each.
4. For each one, open it, add real credentials/nodes where you see
   "(placeholder — wire …)", and click **Activate**.

## Required env vars (set in n8n's environment, e.g. via docker-compose)

| Var | Used by |
|-----|---------|
| `WEBHOOK_URL` | n8n base — used by `fir-human-approval` for resume URLs |
| `TELEGRAM_BOT_TOKEN` | `fir-human-approval` + `case-notify-fanout` (Telegram branch) |
| `TELEGRAM_CHAT_ID` | `fir-human-approval` + `case-notify-fanout` (Telegram branch) |
| `GROQ_API_KEY` | `agent-petitioner` |
| `ADMIN_INTERNAL_KEY` | `graph-rebuild-cron` + `eval-cron` (shared secret matched on the backend via `X-Internal-Key`) |

## Calling these from the backend

Already wired:

- After a verdict: `app/agents/courtroom.py` → router → `services/n8n.notify_verdict()` → `/webhook/case-notify` (this workflow).
- During FIR draft (when `N8N_FIR_APPROVAL=true`): `app/routers/fir.py` → `services/n8n.request_fir_approval()` → `/webhook/fir-approve`.

Both calls are best-effort: an n8n outage never breaks the user-facing
request.
