# n8n image for Hugging Face Spaces.
# Listens on port 7860 (HF requirement), workflows baked into the image
# because free-tier Spaces have no persistent storage.

FROM n8nio/n8n:latest
USER root

COPY workflows /workflows
COPY entrypoint.sh /entrypoint.sh

# Strip the `tags` field from each workflow JSON. n8n's import is per-workflow
# but tags are global — re-using "nyaya-ai" tag across all 6 trips SQLite's
# UNIQUE constraint on tag_entity.name. Tags aren't load-bearing for us; drop
# them at build time so importing all 6 succeeds.
RUN for f in /workflows/*.json; do \
      node -e "const fs=require('fs');const p='$f';const d=JSON.parse(fs.readFileSync(p,'utf8'));delete d.tags;fs.writeFileSync(p,JSON.stringify(d,null,2));"; \
    done \
 && chmod +x /entrypoint.sh \
 && mkdir -p /home/node/.n8n \
 && chown -R node:node /home/node/.n8n /workflows

USER node

ENV N8N_PORT=7860 \
    N8N_HOST=0.0.0.0 \
    N8N_PROTOCOL=https \
    GENERIC_TIMEZONE=Asia/Kolkata \
    N8N_DIAGNOSTICS_ENABLED=false \
    N8N_BLOCK_ENV_ACCESS_IN_NODE=false \
    N8N_USER_FOLDER=/home/node/.n8n

EXPOSE 7860

ENTRYPOINT ["/entrypoint.sh"]
