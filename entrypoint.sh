#!/usr/bin/env bash
set -e

# WMM: configure a git credential helper so git operations issued from
# Hermes's terminal-tool sandbox (and this script's own AUTO_UPDATE pull
# below) can authenticate against GitHub using GH_TOKEN. Without this,
# in-container git calls fail with "could not read Username for
# 'https://github.com'" because no credential source is ever configured.
# This does not print or log the token value.
git config --global credential.helper 'store --file=/root/.git-credentials'
if [ -n "$GH_TOKEN" ]; then
  printf 'https://x-access-token:%s@github.com\n' "$GH_TOKEN" > /root/.git-credentials
  chmod 600 /root/.git-credentials
  echo "git-credential-bootstrap: configured"
else
  echo "git-credential-bootstrap: skipped (GH_TOKEN not set)"
fi

AUTO_UPDATE="${AUTO_UPDATE:-true}"

if [ "$AUTO_UPDATE" = "true" ]; then
  echo "Checking for Hermes updates..."
  cd /opt/hermes-agent
  if git pull --recurse-submodules 2>&1 | grep -v 'Already up to date'; then
    echo "Updating dependencies..."
    VIRTUAL_ENV=/opt/hermes-agent/venv uv pip install -e ".[all]" --quiet
    echo "Update complete."
  else
    echo "Already up to date."
  fi
fi

hermes dashboard --host 127.0.0.1 --port 9119 --no-open &

exec python /auth_proxy.py
