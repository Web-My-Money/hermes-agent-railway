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

    print("wmm-config: checked")


if __name__ == "__main__":
    main()
