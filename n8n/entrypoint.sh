#!/bin/sh
# Local-mode entrypoint for Nyaya AI's n8n.
#
# Every container start:
#   1. Strips the `tags` field from each workflow JSON. n8n's `import:workflow`
#      enforces a UNIQUE constraint on tag_entity.name — re-using the same tag
#      ("nyaya-ai") across all 7 trips that constraint and aborts the import.
#      Tags aren't load-bearing for us, so we drop them inline.
#   2. Imports all /workflows/*.json into n8n's SQLite DB. Idempotent: re-runs
#      replace by ID, so editing a workflow JSON + `docker compose restart n8n`
#      picks up the change.
#   3. Activates every imported workflow.
#   4. (If TELEGRAM_BOT_TOKEN + WEBHOOK_URL are set) registers the Telegram bot
#      webhook so callback_query updates flow to /webhook/telegram-callback.
#   5. Launches n8n.
#
# Env vars (set in docker-compose.yml or .env):
#   TELEGRAM_BOT_TOKEN  — bot token from @BotFather
#   TELEGRAM_CHAT_ID    — chat ID that receives FIR / verdict notifications
#   BACKEND_URL         — backend base URL (e.g. http://backend:8000 in compose)
#   ADMIN_INTERNAL_KEY  — shared secret for backend callback auth
#   WEBHOOK_URL         — n8n public base URL (set by compose for telegram-callback)

set -e

# ---------------------------------------------------------------------------
# 1. Strip global tags so import doesn't trip SQLite's UNIQUE constraint.
# ---------------------------------------------------------------------------
if [ -d /workflows ]; then
  echo "[entrypoint] stripping tags from /workflows/*.json (idempotent)..."
  for f in /workflows/*.json; do
    [ -f "$f" ] || continue
    node -e "const fs=require('fs');const p='$f';try{const d=JSON.parse(fs.readFileSync(p,'utf8'));if(d.tags){delete d.tags;fs.writeFileSync(p,JSON.stringify(d,null,2));}}catch(e){console.error('skip',p,e.message);}"
  done
fi

# ---------------------------------------------------------------------------
# 2. Import all workflows from /workflows
# ---------------------------------------------------------------------------
echo "[entrypoint] importing workflows from /workflows..."
n8n import:workflow --separate --input=/workflows 2>&1 || true

# ---------------------------------------------------------------------------
# 3. Activate every imported workflow
# ---------------------------------------------------------------------------
echo "[entrypoint] activating each workflow by ID..."
n8n list:workflow 2>/dev/null \
  | awk -F'|' 'NF>=2 && $1!="" {print $1}' \
  | while read -r id; do
      echo "  -> activating $id"
      n8n update:workflow --id="$id" --active=true 2>&1 \
        || n8n publish:workflow --id="$id" 2>&1 \
        || true
    done

# ---------------------------------------------------------------------------
# 4. Register Telegram bot webhook so the inline-button callback updates land
#    on our handler workflow at /webhook/telegram-callback.
# ---------------------------------------------------------------------------
if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$WEBHOOK_URL" ]; then
  TG_CB_URL="${WEBHOOK_URL%/}/webhook/telegram-callback"
  echo "[entrypoint] registering Telegram bot webhook -> $TG_CB_URL"
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
  res.on('end', () => console.log('  Telegram setWebhook ->', res.statusCode, body));
});
req.on('error', (err) => console.error('  setWebhook failed:', err.message));
req.write(data); req.end();
" 2>&1 || echo "  webhook registration step errored (callbacks won't work)"
fi

echo "[entrypoint] launching n8n..."
exec n8n start
