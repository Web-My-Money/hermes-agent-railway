#!/usr/bin/env python3
"""Redact secrets from the Hermes ``GET /api/config`` JSON response.

The proxy must not leak long-lived tokens to any authenticated dashboard
session. Masking keeps the key present and the surrounding shape intact so the
dashboard still renders; only the secret's value is replaced.
"""

import json

_MASK = "*"


def _mask(value):
    return _MASK * len(value)


def _redact(data):
    """Mask the three secret shapes in-place. Returns True if anything changed."""
    masked = False

    providers = data.get("custom_providers")
    if isinstance(providers, list):
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            api_key = provider.get("api_key")
            if isinstance(api_key, str) and api_key:
                provider["api_key"] = _mask(api_key)
                masked = True

    servers = data.get("mcp_servers")
    if isinstance(servers, dict):
        for config in servers.values():
            if not isinstance(config, dict):
                continue
            env = config.get("env")
            if isinstance(env, dict):
                for key, value in list(env.items()):
                    if isinstance(value, str) and value:
                        env[key] = _mask(value)
                        masked = True

    dashboard = data.get("dashboard")
    if isinstance(dashboard, dict):
        basic_auth = dashboard.get("basic_auth")
        if isinstance(basic_auth, dict):
            password = basic_auth.get("password")
            if isinstance(password, str) and password:
                basic_auth["password"] = _mask(password)
                masked = True

    return masked


def mask_config_response(body):
    """Return ``body`` with config secrets masked.

    If nothing needed masking the original bytes are returned unchanged, so the
    common (already-clean) path round-trips byte-for-byte. When a secret is
    found the JSON is re-encoded compactly (the format the upstream server uses),
    preserving key order and all non-secret fields.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return body

    if not _redact(data):
        return body

    return json.dumps(
        data, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
