#!/usr/bin/env python3
"""WMM-managed keys in the volume's config.yaml, applied at boot before Hermes starts.

Runs from entrypoint.sh while nothing else holds the file (Hermes rewrites config.yaml
itself, so it must not be edited while the gateway runs). Every write goes through
`hermes config set`, which validates the key and keeps Hermes' own format.

Each rule only fills a gap and never overrides a deliberate choice, so a value changed in
the dashboard sticks:

1. skills.external_dirs includes the shared WMM skills (Web-My-Money/wmm-agents/skills).
2. platforms.telegram.unauthorized_dm_behavior defaults to "pair". When
   TELEGRAM_ALLOWED_USERS is set, Hermes ignores unknown DMs unless this is set per
   platform. Setting it lets a teammate DM G Dog, get a pairing code, and wait for Fran
   to approve it.
3. fallback_providers must not be only the primary model again. It was `gdog free` for
   both, so an outage of that combo had no second path. When every fallback entry
   repeats the primary model, the chain is replaced with HERMES_WMM_FALLBACK_MODEL on
   the same custom provider. That is a different model family on the same gateway;
   there is no second gateway to use.
4. Team access guard (fork patch Web-My-Money/hermes-agent#7). Fran
   (HERMES_OWNER_TELEGRAM_ID, default 8635020128) is the Telegram admin
   (platforms.telegram.allow_admin_from); everyone else who pairs is a teammate:
   - teammates may run only TEAM_SLASH_COMMANDS (no /approve, /yolo, /approvals,
     /config, /model, /restart, /update ...);
   - approvals.non_admin_mode: manual — a teammate's dangerous command needs approval,
     and approvals.non_admin_approver_chat sends that approval card to Fran's DM, so
     Fran decides, not the teammate. Fran's own mode (approvals.mode) is unchanged;
   - approvals.non_admin_deny blocks teammates outright from pairing (approving
     someone else), the allowlist, the config file and the secret-bearing quarantine.
   Each key is only filled when missing or empty. To turn the guard off, set
   approvals.non_admin_mode to "off" (any non-empty value is left alone).
5. Every plugin this repo ships (plugins/, copied into $HERMES_HOME/plugins by
   entrypoint.sh) is in plugins.enabled, unless it is listed in plugins.disabled.
   Currently wmm-idea-capture (the capture_idea tool).
6. Context compression stays under OmniRoute's "heavy request" line. OmniRoute counts a
   chat estimated at >= 32,000 tokens as heavy and admits only 4 of those at once, shared
   with the agents and crons, so long Telegram threads got 503 chat_admission_busy.
   G Dog's fixed floor (system prompt + tool schemas) is ~20-23K tokens on its own, so:
   - compression.threshold_tokens is a CEILING, HERMES_WMM_COMPRESSION_MAX_TOKENS
     (default 28000): a missing/null value or one above it is lowered to it; a lower
     value is left alone. This is the one rule that overrides a set value.
   - proactive_prune_tokens (the no-LLM tool-result prune), when on, is lowered to
     HERMES_WMM_PRUNE_MAX_TOKENS (default 24000) so big tool output is trimmed first.
   - Filled only when missing: tail_mode "legacy" with target_ratio 0.10 (a ~2.8K-token
     verbatim tail; "lean" keeps a 10K minimum tail that cannot fit under the ceiling on
     top of the floor), and protect_first_n 0 (the first messages of a weeks-old chat
     are not worth pinning).
"""
import json
import os
import shutil
import subprocess
import time

import yaml

HOME = os.environ.get("HERMES_HOME", "/root/.hermes")
CONFIG = os.path.join(HOME, "config.yaml")
HERMES = os.environ.get("HERMES_BIN", "hermes")
SKILLS_DIR = os.environ.get("WMM_AGENTS_SKILLS_DIR", "/opt/wmm-agents/skills")
FALLBACK_MODEL = os.environ.get("HERMES_WMM_FALLBACK_MODEL", "xai-oauth/grok-4.5")
OWNER_TELEGRAM_ID = os.environ.get("HERMES_OWNER_TELEGRAM_ID", "8635020128").strip()
# Session-local, non-destructive commands a paired teammate may use.
TEAM_SLASH_COMMANDS = ["new", "stop", "retry", "undo", "status", "compress", "title",
                       "queue", "steer", "btw", "usage", "context"]
# fnmatch globs (case-insensitive) matched against teammates' terminal commands only.
COMPRESSION_MAX_TOKENS = int(os.environ.get("HERMES_WMM_COMPRESSION_MAX_TOKENS", "28000"))
PRUNE_MAX_TOKENS = int(os.environ.get("HERMES_WMM_PRUNE_MAX_TOKENS", "24000"))
WMM_PLUGINS_DIR = os.environ.get("WMM_PLUGINS_DIR", "/opt/wmm-gdog/plugins")
TEAM_DENY = ["*pairing*", "*TELEGRAM_ALLOWED_USERS*", "*allow_admin_from*", "*config.yaml*",
             "*hermes config*", "*non_admin_*", "*secret-bearing*", "*/.hermes/secrets*"]


_backed_up = False


def setk(key, value):
    global _backed_up
    if not _backed_up:  # one timestamped copy, only on boots that change something
        backup = f"{CONFIG}.bak-wmm-config-{time.strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(CONFIG, backup)
        print(f"wmm-config: backed up to {backup}")
        _backed_up = True
    arg = value if isinstance(value, str) else json.dumps(value)
    r = subprocess.run([HERMES, "config", "set", key, arg], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"WARN: wmm-config: could not set {key}: {(r.stderr or r.stdout).strip()[:300]}")
    else:
        print(f"wmm-config: set {key}")


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    dirs = list((cfg.get("skills") or {}).get("external_dirs") or [])
    if SKILLS_DIR not in dirs:
        setk("skills.external_dirs", dirs + [SKILLS_DIR])

    telegram = (cfg.get("platforms") or {}).get("telegram") or {}
    if "unauthorized_dm_behavior" not in telegram:
        setk("platforms.telegram.unauthorized_dm_behavior", "pair")

    model = cfg.get("model") or {}
    primary = str(model.get("default") or "")
    chain = cfg.get("fallback_providers") or []
    if primary and chain and all(str((e or {}).get("model") or "") == primary for e in chain):
        provider = (chain[0] or {}).get("provider") or model.get("provider")
        setk("fallback_providers", [{"provider": provider, "model": FALLBACK_MODEL}])

    if OWNER_TELEGRAM_ID:
        if not telegram.get("allow_admin_from"):
            setk("platforms.telegram.allow_admin_from", [OWNER_TELEGRAM_ID])
        if not telegram.get("user_allowed_commands"):
            setk("platforms.telegram.user_allowed_commands", TEAM_SLASH_COMMANDS)
        approvals = cfg.get("approvals") or {}
        if not approvals.get("non_admin_mode"):
            setk("approvals.non_admin_mode", "manual")
        if not approvals.get("non_admin_deny"):
            setk("approvals.non_admin_deny", TEAM_DENY)
        if not approvals.get("non_admin_approver_chat"):
            setk("approvals.non_admin_approver_chat", {"telegram": OWNER_TELEGRAM_ID})

    plugins = cfg.get("plugins") or {}
    enabled = list(plugins.get("enabled") or [])
    disabled = set(plugins.get("disabled") or [])
    ours = sorted(d for d in (os.listdir(WMM_PLUGINS_DIR) if os.path.isdir(WMM_PLUGINS_DIR) else [])
                  if os.path.isfile(os.path.join(WMM_PLUGINS_DIR, d, "plugin.yaml")))
    missing = [p for p in ours if p not in enabled and p not in disabled]
    if missing:
        setk("plugins.enabled", enabled + missing)

    comp = cfg.get("compression") or {}
    tt = _int_or_none(comp.get("threshold_tokens"))
    if tt is None or tt <= 0 or tt > COMPRESSION_MAX_TOKENS:
        setk("compression.threshold_tokens", COMPRESSION_MAX_TOKENS)
    prune = _int_or_none(comp.get("proactive_prune_tokens"))
    if prune is not None and prune > PRUNE_MAX_TOKENS:  # 0/unset = prune off: left alone
        setk("compression.proactive_prune_tokens", PRUNE_MAX_TOKENS)
    if "tail_mode" not in comp:
        setk("compression.tail_mode", "legacy")
    if "target_ratio" not in comp:
        setk("compression.target_ratio", 0.10)
    if "protect_first_n" not in comp:
        setk("compression.protect_first_n", 0)

    print("wmm-config: checked")


if __name__ == "__main__":
    main()
