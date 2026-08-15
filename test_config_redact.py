#!/usr/bin/env python3
"""Unit tests for config_redact.mask_config_response."""

import json
import sys

from config_redact import mask_config_response

COMPACT = dict(ensure_ascii=False, separators=(",", ":"))


def _enc(obj):
    return json.dumps(obj, **COMPACT).encode("utf-8")


def test_masks_all_three_secret_shapes():
    payload = {
        "custom_providers": [
            {"name": "openai", "api_key": "sk-very-secret-123", "base_url": "https://x"},
        ],
        "mcp_servers": {
            "filesystem": {
                "env": {"GITHUB_TOKEN": "ghp_super_secret", "CLEAR_TEXT": "public-val"},
                "command": "node",
            }
        },
        "dashboard": {"basic_auth": {"username": "admin", "password": "dash-secret-pass"}},
        "unchanged": {"level": 2, "labels": ["a", "b"], "active": True},
    }

    out = mask_config_response(_enc(payload))
    got = json.loads(out)

    provider = got["custom_providers"][0]
    assert "api_key" in provider, "api_key key must stay present"
    assert provider["api_key"] == "*" * len("sk-very-secret-123")
    assert provider["base_url"] == "https://x"
    assert provider["name"] == "openai"

    env = got["mcp_servers"]["filesystem"]["env"]
    assert env["GITHUB_TOKEN"] == "*" * len("ghp_super_secret")
    assert env["CLEAR_TEXT"] == "public-val"
    assert got["mcp_servers"]["filesystem"]["command"] == "node"

    ba = got["dashboard"]["basic_auth"]
    assert "password" in ba
    assert ba["password"] == "*" * len("dash-secret-pass")
    assert ba["username"] == "admin"

    assert got["unchanged"] == {"level": 2, "labels": ["a", "b"], "active": True}

    expected = {
        "custom_providers": [
            {"name": "openai", "api_key": "*" * 17, "base_url": "https://x"},
        ],
        "mcp_servers": {
            "filesystem": {
                "env": {"GITHUB_TOKEN": "*" * len("ghp_super_secret"), "CLEAR_TEXT": "public-val"},
                "command": "node",
            }
        },
        "dashboard": {"basic_auth": {"username": "admin", "password": "*" * 16}},
        "unchanged": {"level": 2, "labels": ["a", "b"], "active": True},
    }
    assert out == _enc(expected), (
        "redacted output must be byte-identical to compact encoding except masked values"
    )
    assert out != _enc(payload)


def test_empty_secret_value_left_intact():
    payload = {"custom_providers": [{"api_key": ""}], "dashboard": {}, "mcp_servers": {}}
    out = mask_config_response(_enc(payload))
    assert json.loads(out)["custom_providers"][0]["api_key"] == ""


def test_payload_without_secrets_passes_through_unchanged():
    payload = {"dashboard": {"basic_auth": {"username": "admin"}}, "feeds": [1, 2]}
    body = _enc(payload)
    assert mask_config_response(body) == body


def test_non_json_body_unchanged():
    body = b"not json at all"
    assert mask_config_response(body) == body


def test_empty_string_is_kept_empty():
    payload = {"dashboard": {"basic_auth": {"password": "", "username": "u"}}}
    out = mask_config_response(_enc(payload))
    assert json.loads(out)["dashboard"]["basic_auth"]["password"] == ""


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
