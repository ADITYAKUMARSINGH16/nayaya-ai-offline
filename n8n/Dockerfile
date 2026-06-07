# Local n8n image for docker-compose.
# Workflows live at /workflows (mounted from ./n8n/workflows on the host so
# editing a JSON + `docker compose restart n8n` picks it up without a rebuild).
# Entrypoint imports + activates all of them on every boot; n8n_data volume
# means the owner account survives between restarts (unlike HF Spaces).

FROM n8nio/n8n:latest
USER root

COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
 && mkdir -p /home/node/.n8n \
 && chown -R node:node /home/node/.n8n

USER node

# Port / host / protocol come from docker-compose's n8n.environment block so
# this image is portable (works on both local docker and HF Spaces).
ENV N8N_USER_FOLDER=/home/node/.n8n \
    N8N_DIAGNOSTICS_ENABLED=false \
    N8N_BLOCK_ENV_ACCESS_IN_NODE=false

ENTRYPOINT ["/entrypoint.sh"]
