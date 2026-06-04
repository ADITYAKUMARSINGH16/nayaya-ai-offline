# FIR Human-Approval Workflow — Setup Guide

End-to-end flow:

```
User submits FIR via UI
       │
       ▼
Backend drafts FIR with the LLM agent
       │
       ▼
Backend saves FIR (status="pending_approval")
       │
       ▼
Backend fires n8n webhook (fire-and-forget) ─────► returns FIR to user immediately
                                                    (UI shows "Pending approval")
       │ (n8n receives trigger, prepares payload)
       ▼
n8n Telegram node sends message to reviewer ─────► reviewer sees FIR preview
   with inline ✅ Approve / ❌ Reject URL buttons   on their phone
       │
       │  reviewer taps a button → opens URL → resumes workflow
       ▼
n8n calls backend PATCH /api/internal/fir/{id}/approval
       │
       ▼
Backend flips FIR status to "approved" or "rejected"
       │
       ▼
Frontend polls /api/fir/{id}/status → sees the new status → updates UI
```

---

## 5-minute setup

### 1. Create a Telegram bot (2 min)

1. Open Telegram → search **@BotFather** → start chat
2. Send `/newbot`
3. Pick a display name (e.g. "Nyaya FIR Reviewer")
4. Pick a username ending in `bot` (e.g. `nyaya_fir_review_bot`)
5. BotFather replies with a **token** like `123456789:ABCdef...`. Save it.

### 2. Get your Telegram chat ID (1 min)

1. Open your new bot's chat → send `/start` (or any message)
2. In your browser, open:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
3. Find `"chat":{"id":NNNNNNN}` in the JSON. That's your chat ID. Save it.

For demo purposes use your personal chat. For real deployment, create a Telegram **group**, add the bot, get the group's chat ID (negative integer).

### 3. Set env vars in n8n (HF Spaces) — 1 min

In HF Spaces dashboard → your n8n Space → **Settings → Variables and secrets**, add:

| Variable | Value |
|--|--|
| `TELEGRAM_BOT_TOKEN` | the bot token from BotFather (step 1) |
| `TELEGRAM_CHAT_ID` | the chat ID from step 2 (e.g. `123456789`) |
| `BACKEND_URL` | `https://nyaya-ai-backend-bfel.onrender.com` |
| `ADMIN_INTERNAL_KEY` | **REUSE** the same value you already have set on Render |
| `WEBHOOK_URL` | `https://tanujha-nyaya-n8n.hf.space/` (your n8n public URL — already set) |

**That's it for n8n.** No UI clicks needed — `entrypoint.sh` automatically:
- Creates the Telegram credential from `TELEGRAM_BOT_TOKEN`
- Patches the workflow JSON to link the credential
- Imports + publishes the workflow on each Space rebuild

After saving the env vars, HF will rebuild the Space (~2-3 min). Check logs to confirm:
```
[entrypoint] creating Telegram credential from TELEGRAM_BOT_TOKEN...
[entrypoint] credential ID = abc123 — patching workflow JSONs...
[entrypoint] publishing each workflow by ID...
```

### 4. Set env vars on Render backend — 30 sec

In Render dashboard → your backend service → **Environment**, add:

| Variable | Value |
|--|--|
| `N8N_FIR_APPROVAL` | `true` |
| `N8N_WEBHOOK_BASE` | `https://tanujha-nyaya-n8n.hf.space` |
| `ADMIN_INTERNAL_KEY` | (already set — no action needed) |

Render redeploys automatically.

### 5. Test it (30 sec)

```bash
curl -X POST https://nyaya-ai-backend-bfel.onrender.com/api/fir \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-1",
    "complainant_name": "Test Complainant",
    "incident_date": "2026-05-31",
    "police_station": "Demo PS",
    "facts": "A man stole my mobile phone from my bag at the metro station."
  }'
```

You should see:
- Backend response within 2-3 seconds with FIR text + `record_id`
- Telegram message on your phone within 5 seconds with the FIR preview and Approve/Reject buttons
- Click ✅ Approve → browser opens to n8n's confirmation page
- Poll status:
  ```bash
  curl https://nyaya-ai-backend-bfel.onrender.com/api/fir/<record_id>/status
  ```
  Should return `{"status": "approved", ...}`

---

## Troubleshooting

**No Telegram message arrives:**
- Check n8n Executions panel — did the workflow run? Any errored node?
- Verify the Telegram credential is set on the workflow's Telegram node
- Verify `TELEGRAM_CHAT_ID` env is set correctly
- Verify you've started a chat with your bot (bots can't message you first)

**"401 invalid internal key" in n8n callback:**
- `INTERNAL_CALLBACK_KEY` must be IDENTICAL on both Render backend and n8n HF Spaces

**FIR returns immediately but status never flips:**
- Workflow may have errored on the callback node — check n8n Executions
- Backend logs (Render → Logs) will show what came in on `/api/internal/fir/...`

**Approve button opens but workflow doesn't resume:**
- This is a Wait-node issue — make sure n8n's `WEBHOOK_URL` env exactly matches the public HF URL with trailing slash

---

## Demo script (30 sec live)

> "Watch the legal-ethics guardrail in action. When a complainant submits an FIR, our system drafts it with the AI — BUT before it's treated as filed, it goes through a human-in-the-loop approval. The reviewer — a real lawyer — gets a Telegram message with the drafted FIR. They tap Approve or Reject. If they approve, the FIR is filed. If they reject, the complainant is told to revise. No AI-generated legal document hits the police station without a human signature."

**Live:**
1. Submit FIR in UI → "Status: Pending lawyer approval ⏳"
2. Reviewer's phone (held up to camera) buzzes → shows FIR preview + buttons
3. Tap ✅ Approve
4. UI auto-refreshes → "Status: ✅ Approved by reviewer at HH:MM"
