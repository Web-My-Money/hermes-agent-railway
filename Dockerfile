FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates ripgrep ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# WMM: agent CLI tooling. G Dog runs unattended in this container and its tool
# calls kept dying on `gh: command not found` / `railway: command not found`
# (observed repeatedly 2026-08-27 .. 2026-08-30), so it could read code but never
# ship a PR or inspect its own stack. Baked into the image rather than installed
# in entrypoint.sh so boots stay fast and a network blip cannot leave the agent
# without tools. Versions are pinned for the same reason the Hermes clone is.
ARG GH_CLI_VERSION=2.99.0
ARG RAILWAY_CLI_VERSION=5.48.0
RUN GH_TGZ="gh_${GH_CLI_VERSION}_linux_amd64" \
    && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_CLI_VERSION}/${GH_TGZ}.tar.gz" | tar -xz -C /tmp \
    && mv "/tmp/${GH_TGZ}/bin/gh" /usr/local/bin/gh \
    && rm -rf "/tmp/${GH_TGZ}" \
    && npm install -g "@railway/cli@${RAILWAY_CLI_VERSION}" \
    && gh --version \
    && railway --version

# WMM: build from our own fork, not upstream directly. Two reasons:
#   1. It is the only way a WMM patch can reach production — this repo carries no
#      Python source, so /opt/hermes-agent is whatever this clone pulls.
#   2. Upstream was cloned unpinned, so every image rebuild silently adopted
#      whatever NousResearch/main happened to be that day (observed 2026-08-24:
#      a rebuild moved production from 0.20.4 to 0.20.5 with no code change on
#      our side). The fork's main only moves when WMM merges.
# Rebase the fork on upstream deliberately; do not point this back at upstream.
RUN git clone --recurse-submodules --branch main https://github.com/Web-My-Money/hermes-agent.git /opt/hermes-agent

WORKDIR /opt/hermes-agent
RUN uv venv venv --python 3.11 \
    && VIRTUAL_ENV=/opt/hermes-agent/venv uv pip install -e ".[all]"

ENV PATH="/opt/hermes-agent/venv/bin:$PATH"

RUN mkdir -p /root/.hermes/{cron,sessions,logs,memories,skills,pairing,hooks,image_cache,audio_cache} \
    && cp cli-config.yaml.example /root/.hermes/config.yaml \
    && touch /root/.hermes/.env

COPY auth_proxy.py /auth_proxy.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
