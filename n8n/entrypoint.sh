#!/bin/sh
# entrypoint for Nyaya AI's n8n on Hugging Face Spaces.
#
# HF free tier has NO persistent storage — every container start is a fresh
# /home/node/.n8n. So we always re-import + publish + re-create credentials
# on each cold boot from env vars baked into the Space's Variables settings.
#
# Required env vars:
#   TELEGRAM_BOT_TOKEN  — bot token from BotFather (creates the credential)
#   TELEGRAM_CHAT_ID    — chat ID to send approval requests to
#   BACKEND_URL         — backend base URL (for callback)
#   ADMIN_INTERNAL_KEY  — shared secret for callback auth (matches backend)
#
# n8n 2.22.5 CLI: `update:workflow --all --active=true` is gone — we fetch
# IDs via `list:workflow` and call `publish:workflow --id=<id>` per workflow.

set -e

# ---------------------------------------------------------------------------
# (No credential setup needed — the FIR-approval workflow now uses a direct
# HTTP Request to Telegram's Bot API with TELEGRAM_BOT_TOKEN in the URL,
# bypassing n8n's Telegram credential system entirely.)
# ---------------------------------------------------------------------------

# Import all workflows from /workflows

echo "[entrypoint] importing workflows from /workflows..."
n8n import:workflow --separate --input=/workflows 2>&1 || true

# ---------------------------------------------------------------------------
# 3. Publish (activate) every imported workflow
# ---------------------------------------------------------------------------

echo "[entrypoint] publishing each workflow by ID..."
n8n list:workflow 2>/dev/null \
  | awk -F'|' 'NF>=2 && $1!="" {print $1}' \
  | while read -r id; do
      echo "  → publishing $id"
      n8n publish:workflow --id="$id" 2>&1 || true
    done

# ---------------------------------------------------------------------------
# 4. Register Telegram webhook so callback_query updates flow to our handler
#    workflow at /webhook/telegram-callback. Idempotent — Telegram accepts
#    re-setting the same URL.
# ---------------------------------------------------------------------------

if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$WEBHOOK_URL" ]; then
  TG_CB_URL="${WEBHOOK_URL%/}/webhook/telegram-callback"
  echo "[entrypoint] registering Telegram bot webhook → $TG_CB_URL"
  # Use node (always present in n8n image) instead of curl (may not be).
  TG_CB_URL="$TG_CB_URL" TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" node -e "
const https = require('https');
const data = JSON.stringify({ url: process.env.TG_CB_URL, allowed_updates: ['callback_query'] });
const req = https.request({
  hostname: 'api.telegram.org',
  path: '/bot' + process.env.TELEGRAM_BOT_TOKEN + '/setWebhook',
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
}, (res) => {
  let body = '';
  res.on('data', (c) => body += c);
  res.on('end', () => console.log('  Telegram setWebhook →', res.statusCode, body));
});
req.on('error', (err) => console.error('  setWebhook failed:', err.message));
req.write(data); req.end();
" 2>&1 || echo "  ✗ webhook registration step errored (callbacks won't work)"
fi

echo "[entrypoint] launching n8n..."
exec n8n start
