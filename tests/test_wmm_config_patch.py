"""Fallback rule of wmm_config_patch.py (rule 3: a fallback chain must not only repeat the primary).

Run:  python -m unittest tests.test_wmm_config_patch -v      (needs PyYAML, which the image has)

`hermes config set` is never executed: setk() is replaced with a recorder.
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml
except ImportError:  # wmm_config_patch.py itself imports yaml; the image has it, a bare dev venv may not
    yaml = None

PATCH_FILE = Path(__file__).resolve().parent.parent / "wmm_config_patch.py"


def load_patch(home, extra_env=None):
    """Fresh copy of wmm_config_patch.py (module constants are read from the env at import)."""
    env = {"HERMES_HOME": home, "WMM_AGENTS_SKILLS_DIR": "/nonexistent-skills",
           "WMM_PLUGINS_DIR": "/nonexistent-plugins", "HERMES_OWNER_TELEGRAM_ID": ""}
    env.update(extra_env or {})
    with mock.patch.dict(os.environ, env, clear=False):
        os.environ.pop("HERMES_WMM_FALLBACK_MODEL", None)
        if extra_env and "HERMES_WMM_FALLBACK_MODEL" in extra_env:
            os.environ["HERMES_WMM_FALLBACK_MODEL"] = extra_env["HERMES_WMM_FALLBACK_MODEL"]
        spec = importlib.util.spec_from_file_location("wmm_config_patch_under_test", PATCH_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def run_main(config, extra_env=None):
    """Run main() against `config` and return the (key, value) pairs it tried to set."""
    with tempfile.TemporaryDirectory() as home:
        with open(os.path.join(home, "config.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f)
        module = load_patch(home, extra_env)
        calls = []
        module.setk = lambda key, value: calls.append((key, value))
        module.main()
        return module, dict(calls)


PRIMARY = "gdog free"
PROVIDER = "custom:Omniroute"


@unittest.skipIf(yaml is None, "PyYAML not installed")
class FallbackRule(unittest.TestCase):
    def test_default_fallback_is_unchanged(self):
        module, _ = run_main({"model": {"default": PRIMARY, "provider": PROVIDER}})
        self.assertEqual(module.FALLBACK_MODEL, "xai-oauth/grok-4.5")

    def test_chain_that_only_repeats_the_primary_gets_the_default(self):
        _, calls = run_main({"model": {"default": PRIMARY, "provider": PROVIDER},
                             "fallback_providers": [{"provider": PROVIDER, "model": PRIMARY}]})
        self.assertEqual(calls["fallback_providers"], [{"provider": PROVIDER, "model": "xai-oauth/grok-4.5"}])

    def test_env_override_wins_over_the_default(self):
        _, calls = run_main({"model": {"default": PRIMARY, "provider": PROVIDER},
                             "fallback_providers": [{"provider": PROVIDER, "model": PRIMARY}]},
                            {"HERMES_WMM_FALLBACK_MODEL": "cx/gpt-5.6-terra-medium"})
        self.assertEqual(calls["fallback_providers"],
                         [{"provider": PROVIDER, "model": "cx/gpt-5.6-terra-medium"}])

    def test_existing_distinct_fallback_is_left_alone(self):
        _, calls = run_main({"model": {"default": PRIMARY, "provider": PROVIDER},
                             "fallback_providers": [{"provider": PROVIDER, "model": "HermesAux"}]})
        self.assertNotIn("fallback_providers", calls)


@unittest.skipIf(yaml is None, "PyYAML not installed")
class McpLazyRule(unittest.TestCase):
    """Rule 9: MCP servers start lazily unless they already say otherwise."""

    SERVERS = {"github": {"command": "npx"}, "wmm-credentials-gateway": {"command": "node"}}

    def test_servers_without_lazy_get_lazy_true(self):
        _, calls = run_main({"mcp_servers": dict(self.SERVERS)})
        self.assertIs(calls["mcp_servers.github.lazy"], True)
        self.assertIs(calls["mcp_servers.wmm-credentials-gateway.lazy"], True)

    def test_explicit_lazy_false_is_left_alone(self):
        _, calls = run_main({"mcp_servers": {"github": {"command": "npx", "lazy": False}}})
        self.assertNotIn("mcp_servers.github.lazy", calls)

    def test_disabled_server_is_left_alone(self):
        _, calls = run_main({"mcp_servers": {"github": {"command": "npx", "enabled": False}}})
        self.assertNotIn("mcp_servers.github.lazy", calls)

    def test_env_switch_turns_the_rule_off(self):
        _, calls = run_main({"mcp_servers": dict(self.SERVERS)}, {"HERMES_WMM_MCP_LAZY": "0"})
        self.assertFalse([k for k in calls if k.startswith("mcp_servers.")])

    def test_no_mcp_servers_block_is_fine(self):
        _, calls = run_main({})
        self.assertFalse([k for k in calls if k.startswith("mcp_servers.")])


if __name__ == "__main__":
    unittest.main()
