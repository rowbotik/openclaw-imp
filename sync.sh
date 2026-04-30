#!/bin/bash
set -euo pipefail

PI_HOST="${PI_HOST:-imp-zero.local}"
PI_USER="${PI_USER:-pi}"
REMOTE_DIR="${REMOTE_DIR:-/home/pi/openclaw-imp}"
SERVICE_NAME="${SERVICE_NAME:-openclaw-imp}"

rsync -avz --delete \
  --exclude='__pycache__' \
  --exclude='.lgd-*' \
  --exclude='.git' \
  --exclude='.env' \
  ./ "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/"

ssh "${PI_USER}@${PI_HOST}" "
  if [ ! -f '${REMOTE_DIR}/.env' ]; then
    cp '${REMOTE_DIR}/.env.example' '${REMOTE_DIR}/.env'
    echo 'Created ${REMOTE_DIR}/.env from .env.example; fill in OPENAI_API_KEY, OPENCLAW_TOKEN, and OPENCLAW_BASE_URL before starting the service.'
    exit 2
  fi
  sudo cp '${REMOTE_DIR}/openclaw-imp.service' /etc/systemd/system/ &&
  sudo cp '${REMOTE_DIR}/openclaw-imp-dashboard.service' /etc/systemd/system/ &&
  sudo cp '${REMOTE_DIR}/openclaw-imp-dashboard.sudoers' /etc/sudoers.d/openclaw-imp-dashboard &&
  sudo chmod 440 /etc/sudoers.d/openclaw-imp-dashboard &&
  sudo visudo -cf /etc/sudoers.d/openclaw-imp-dashboard &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable '${SERVICE_NAME}' &&
  sudo systemctl enable openclaw-imp-dashboard &&
  sudo systemctl restart '${SERVICE_NAME}' &&
  sudo systemctl restart openclaw-imp-dashboard &&
  sleep 2 &&
  sudo journalctl -u '${SERVICE_NAME}' -n 30 --no-pager &&
  sudo journalctl -u openclaw-imp-dashboard -n 20 --no-pager
"
