---
title: Nyaya AI · n8n
emoji: ⚖️
colorFrom: yellow
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Nyaya AI — n8n workflows

Hosts the 6 n8n workflows powering Nyaya AI (FIR human approval, verdict
notification fan-out, agent sub-workflows, eval/graph cron jobs, error handler).

## Architecture

- Docker image: `n8nio/n8n:latest`
- Port: **7860** (HF Spaces convention, NOT n8n's default 5678)
- Workflows: baked into the image under `/workflows/`, auto-imported and
  activated on each container start (HF free tier has no persistent storage)

## Secrets required (set under Space → Settings → Variables and secrets)

| Name | Why |
|------|-----|
| `OPENAI_API_KEY` | used by `agent-petitioner` workflow's chat-completions call |
| `ADMIN_INTERNAL_KEY` | shared secret for cron workflows to hit `/api/admin/*` on the backend |
| `WEBHOOK_URL` | full public URL of this Space, e.g. `https://tanu-jha-nyaya-n8n.hf.space` |
| `BACKEND_URL` | full public URL of the FastAPI backend on Render |

After setting secrets, restart the Space → workflows re-import on first boot.

## Workflow webhook URLs

After deployment, your webhooks will be available at:

- `{WEBHOOK_URL}/webhook/agent-petitioner` — petitioner sub-workflow
- `{WEBHOOK_URL}/webhook/case-notify` — verdict notification fan-out
- `{WEBHOOK_URL}/webhook/fir-approve` — FIR human-approval entry point
